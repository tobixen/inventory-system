#!/usr/bin/env python3
"""Build a human-correctable staging file from a shopping receipt + barcode scan.

This is the deterministic first stage of the shopping pipeline. It does only
mechanical work:

* parse a shop receipt (currently Lidl JSON) into one staging row per line item;
* classify barcode-extraction output photos as barcode / expiry / label;
* gather candidate EANs per receipt line via tingbok's reverse receipt-name
  lookup (``GET /api/ean/search``).

It deliberately does NOT decide which EAN a line is, nor read best-before dates
from photos — those are judgement calls left to a later AI review step that edits
the emitted staging YAML. The staging file is the correction checkpoint before
any irreversible action (tingbok PUT, inventory edit, commit).

Usage:
    shop_import.py --receipt ~/regnskap/lidl_receipts.json \\
        --barcodes-json barcodes.json --out staging/shopping-2026-05-28.yaml

    # produce barcodes.json first with:
    #   extract_barcodes.py --json PHOTOS... > barcodes.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bb_dates import find_dates  # date parsing shared with extract_barcodes

try:
    import niquests as requests
except ImportError:  # pragma: no cover - fallback
    try:
        import requests
    except ImportError:  # pragma: no cover
        requests = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

DEFAULT_TINGBOK_URL = "https://tingbok.plann.no"

#: Receipt name suffix Lidl prints for weighed (per-kilogram) goods.
_KG_SUFFIX = "НА КГ"

Searcher = Callable[..., list[dict[str, Any]]]


def parse_price(value: str | float) -> float:
    """Parse a receipt price/quantity, accepting comma or dot decimals."""
    if isinstance(value, int | float):
        return float(value)
    return float(str(value).strip().replace(",", "."))


def _iso_date(value: str) -> str:
    """Normalise a Lidl ``YYYY.MM.DD`` purchase date to ``YYYY-MM-DD``."""
    return value.strip().replace(".", "-")


def _new_item_row(receipt_name: str, price: float, qty: float, unit: str) -> dict[str, Any]:
    """A staging row with the review scaffold fields defaulted to unfilled.

    ``price`` is the unit price in ``unit`` (per-kg for weighed lines); ``line_total``
    is the receipt's printed line amount and is authoritative downstream. See
    scripts/staging.py for the full field semantics.
    """
    return {
        "receipt_name": receipt_name,
        "price": price,
        "qty": qty,
        "unit": unit,
        "line_total": round(price * qty, 2),
        # ---- filled during review (AI/human) ----
        "ean": None,
        "ean_candidates": [],
        "name": None,
        "category": None,
        "bb": None,
        "bb_source": None,
        "location": None,
        "inventory_id": None,
        "add_to_inventory": True,
        "to_tingbok": None,
        "photos": [],
        "needs_review": True,
        "notes": "",
    }


def parse_lidl_receipt(
    receipt: dict[str, Any], shop: str = "Lidl Varna", source: str = "lidl_receipts.json"
) -> dict[str, Any]:
    """Parse a receipt dict into a staging structure (no candidates).

    Accepts both the Lidl JSON schema (``purchase_date``/``total_price_no_saving``,
    item ``price`` = unit price) and a hand-transcribed receipt (``date``/``shop``/
    ``currency``/``total``, item rows with explicit ``unit``, ``unit_price`` and
    ``price`` = the printed line total).  Header keys present in the receipt win
    over the ``shop``/``source`` arguments.
    """
    items: list[dict[str, Any]] = []
    for raw in receipt.get("items", []):
        name = raw["name"]
        qty = parse_price(raw.get("quantity", "1"))
        if "unit_price" in raw:
            price = parse_price(raw["unit_price"])
            line_total = parse_price(raw["price"])
        else:
            price = parse_price(raw["price"])
            line_total = round(price * qty, 2)
        unit = raw.get("unit") or ("kg" if name.upper().rstrip().endswith(_KG_SUFFIX) else "pcs")
        row = _new_item_row(name, price, qty, unit)
        row["line_total"] = line_total
        items.append(row)

    return {
        "session": _iso_date(receipt.get("purchase_date") or receipt.get("date") or ""),
        "shop": receipt.get("shop") or shop,
        "store": receipt.get("store"),
        "currency": receipt.get("currency", "EUR"),
        "receipt_total": parse_price(receipt.get("total_price_no_saving", receipt.get("total", "0"))),
        "source": source,
        "items": items,
        "loose_photos": [],
    }


def find_date_candidates(text: str) -> list[str]:
    """Extract ISO date candidates from free text (shared bb_dates parser)."""
    return find_dates(text)


def classify_photo_result(result: dict[str, Any]) -> dict[str, Any]:
    """Classify one ``extract_barcodes.py`` result as barcode / expiry / label.

    This is a heuristic guess to help the reviewer; the AI step confirms it.
    A photo-derived best-before (from ``extract_barcodes --best-before``) is
    surfaced as ``bb`` regardless of kind, since it often rides the barcode shot.
    """
    filename = Path(result["file"]).name
    bb = result.get("best_before")

    if result.get("type") != "OCR":
        product = result.get("product") or {}
        photo = {"file": filename, "kind": "barcode", "ean": result.get("data"), "product": product.get("name")}
        if bb:
            photo["bb"] = bb
        return photo

    texts = [result.get("ocr_title") or "", result.get("data") or ""]
    texts += [r.get("text", "") for r in result.get("ocr_results", [])]
    dates: list[str] = []
    for text in texts:
        for iso in find_date_candidates(text):
            if iso not in dates:
                dates.append(iso)
    if bb or dates:
        photo = {"file": filename, "kind": "expiry", "ocr_date_candidates": dates}
        if bb:
            photo["bb"] = bb
        return photo
    return {"file": filename, "kind": "label", "ocr_title": result.get("ocr_title") or result.get("data")}


def _expiry_date(photo: dict[str, Any]) -> str | None:
    """Best best-before date an expiry photo offers, or None.

    Prefers the OCR pass's own ``bb`` pick; else the latest date candidate
    (best-before is usually the furthest-out date on a pack — lot/production
    dates are earlier).
    """
    if photo.get("bb"):
        return photo["bb"]
    dates = photo.get("ocr_date_candidates") or []
    return max(dates) if dates else None


def _pair_following_expiry(photos: list[dict[str, Any]]) -> None:
    """Carry an expiry-only photo's date back onto the preceding barcode photo.

    A best-before is often shot in the frame *immediately after* the barcode
    rather than on the barcode itself. When a barcode photo has no ``bb`` of its
    own and is directly followed by an ``expiry`` photo, attach that date as the
    barcode's ``bb`` and record the source frame in ``bb_from`` (the pairing is
    a positional guess, so the reviewer can see where it came from). Mutates in
    place.
    """
    for prev, cur in zip(photos, photos[1:], strict=False):
        if prev.get("kind") != "barcode" or prev.get("bb"):
            continue
        if cur.get("kind") != "expiry":
            continue
        date = _expiry_date(cur)
        if date:
            prev["bb"] = date
            prev["bb_from"] = cur["file"]


def build_loose_photos(barcode_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify every barcode-extraction result into a loose_photos list."""
    photos = [classify_photo_result(r) for r in barcode_results]
    _pair_following_expiry(photos)
    return photos


def _tingbok_searcher(base_url: str = DEFAULT_TINGBOK_URL) -> Searcher:
    """Return a searcher that queries tingbok's reverse receipt-name endpoint."""

    def search(receipt_name: str, shop: str | None = None) -> list[dict[str, Any]]:
        if requests is None:  # pragma: no cover
            return []
        try:
            params = {"receipt_name": receipt_name}
            if shop:
                params["shop"] = shop
            resp = requests.get(f"{base_url}/api/ean/search", params=params, timeout=15)
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception as exc:  # pragma: no cover - network best-effort
            print(f"Warning: tingbok search failed for {receipt_name!r}: {exc}", file=sys.stderr)
            return []

    return search


def build_staging(
    receipt: dict[str, Any],
    *,
    shop: str = "Lidl Varna",
    source: str = "lidl_receipts.json",
    searcher: Searcher,
    barcode_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the full staging structure: parsed rows + candidates + photos."""
    staging = parse_lidl_receipt(receipt, shop=shop, source=source)
    staging["loose_photos"] = build_loose_photos(barcode_results or [])

    for item in staging["items"]:
        # No shop filter: receipt-name observations are often recorded with no
        # shop, and the same product seen at another shop is still a valid
        # candidate. The reviewer picks; recall matters more than precision here.
        matches = searcher(item["receipt_name"])
        item["ean_candidates"] = [
            {
                "ean": m["ean"],
                "name": m.get("name"),
                "source": "tingbok_receipt_name",
                "score": m.get("score"),
            }
            for m in matches
        ]
    return staging


def dump_yaml(staging: dict[str, Any]) -> str:
    """Serialise the staging structure to human-editable YAML."""
    if yaml is None:  # pragma: no cover
        return json.dumps(staging, ensure_ascii=False, indent=2)
    return yaml.safe_dump(staging, allow_unicode=True, sort_keys=False, width=100)


def main() -> None:  # pragma: no cover - thin CLI wiring
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path.home() / "regnskap" / "lidl_receipts.json",
        help="Path to lidl_receipts.json (latest entry is used)",
    )
    parser.add_argument("--barcodes-json", type=Path, default=None, help="JSON output from extract_barcodes.py --json")
    parser.add_argument("--shop", default="Lidl Varna", help="Shop name recorded in the staging file")
    parser.add_argument("--tingbok-url", default=DEFAULT_TINGBOK_URL)
    parser.add_argument("--no-tingbok", action="store_true", help="Skip tingbok candidate lookup")
    parser.add_argument("--out", type=Path, default=None, help="Staging file to write (default: stdout)")
    args = parser.parse_args()

    receipts = json.loads(args.receipt.read_text(encoding="utf-8"))
    receipt = receipts[-1] if isinstance(receipts, list) else receipts

    barcode_results: list[dict[str, Any]] = []
    if args.barcodes_json:
        barcode_results = json.loads(args.barcodes_json.read_text(encoding="utf-8"))

    searcher: Searcher = (lambda name, shop=None: []) if args.no_tingbok else _tingbok_searcher(args.tingbok_url)
    staging = build_staging(
        receipt, shop=args.shop, source=args.receipt.name, searcher=searcher, barcode_results=barcode_results
    )

    text = dump_yaml(staging)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        n = len(staging["items"])
        flagged = sum(1 for i in staging["items"] if not i["ean_candidates"])
        print(f"Wrote {args.out} — {n} items, {flagged} with no EAN candidate (need review).")
    else:
        print(text)


if __name__ == "__main__":
    main()
