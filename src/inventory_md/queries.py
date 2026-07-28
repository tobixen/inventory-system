"""Read-only queries over a parsed inventory (``inventory.json``).

Consolidates the logic that previously lived in ``scripts/find_expiring_items.py``
and ``scripts/lookup_items.py`` so the container-walking, best-before handling and
food/category detection have a single home and can be unit-tested and shipped with
the package. The ``inventory-md expiring`` and ``inventory-md lookup`` subcommands
build on these helpers.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from . import barcodes, vocabulary
from .parser import normalize_bb_date


def iter_items(data: dict) -> Iterator[tuple[dict, str, str, str]]:
    """Yield ``(item, container_id, parent_id, location)`` for every inventory item.

    ``location`` is ``"<container>, <parent>"`` when a parent is present, else just
    the container id.
    """
    for container in data.get("containers", []) or []:
        container_id = container.get("id", "unknown")
        parent_id = container.get("parent", "")
        location = f"{container_id}, {parent_id}" if parent_id else container_id
        for item in container.get("items", []):
            yield item, container_id, parent_id, location


def normalize_bb(bb: str | None) -> str | None:
    """Normalize a best-before tag to an ISO ``YYYY-MM-DD`` string, or ``None``.

    Strips a trailing ``:EST`` marker, then delegates date padding to
    ``parser.normalize_bb_date`` (``YYYY-MM`` → last day of month; ``YYYY`` →
    Dec 31). Returns ``None`` for empty or unparseable values.
    """
    if not bb:
        return None
    if bb.endswith(":EST"):
        bb = bb[:-4]
    bb = normalize_bb_date(bb)
    try:
        date.fromisoformat(bb)
    except ValueError:
        return None
    return bb


def bb_status(bb: str | None) -> str:
    """Human-readable best-before status string (mirrors the expiry report wording)."""
    if not bb:
        return "no bb"
    normalized = normalize_bb(bb)
    if normalized is None:
        return f"bb:{bb} (malformed)"
    days = (date.fromisoformat(normalized) - date.today()).days
    if days < 0:
        return f"bb:{bb} [EXPIRED {-days}d ago]"
    if days <= 30:
        return f"bb:{bb} [{days}d left ⚠️]"
    return f"bb:{bb} [{days}d left]"


def _load_food_vocabulary(inventory_path: Path) -> dict[str, vocabulary.Concept]:
    """Load vocabulary.json next to the inventory, with broader links made traversable."""
    return vocabulary.load_local_vocabulary(inventory_path.parent / "vocabulary.json")


def _category_matches(categories: list[str], target: str, concepts: dict[str, vocabulary.Concept], lang: str) -> bool:
    """Return True if any of ``categories`` is ``target`` or a descendant of it.

    With a vocabulary, matching is hierarchy-aware (e.g. ``food/grains/rice`` matches
    ``rice``, and ``rice`` matches a parent like ``grains``). Without a vocabulary,
    falls back to a case-insensitive substring match on the raw category strings.
    """
    if not concepts:
        needle = target.lower()
        return any(needle in cat.lower() for cat in categories)
    target_id = vocabulary.resolve_category(target, concepts, lang) or target
    for cat in categories:
        cid = vocabulary.resolve_category(cat, concepts, lang) or cat
        if vocabulary.is_descendant_of(cid, target_id, concepts):
            return True
    return False


def _is_food(categories: list[str], concepts: dict[str, vocabulary.Concept], lang: str) -> bool:
    """Return True if any category is ``food`` or a descendant of it in the vocabulary.

    Without a vocabulary, falls back to "has any category" (best effort).
    """
    if not concepts:
        return bool(categories)
    return _category_matches(categories, "food", concepts, lang)


def find_expiring_items(
    inventory_path: Path,
    food_only: bool = False,
    category: str | None = None,
    lang: str = "en",
) -> list[dict[str, Any]]:
    """Return items that have a best-before date, sorted oldest-first.

    Each dict has: id, name, container, parent, location, bb, days, expired, inferred.
    Items with a malformed best-before date are skipped (a warning is printed).
    ``food_only`` restricts to the food hierarchy; ``category`` restricts to a single
    category (and its descendants). Both use ``vocabulary.json`` when present.
    """
    with open(inventory_path, encoding="utf-8") as f:
        data = json.load(f)

    concepts = _load_food_vocabulary(inventory_path) if (food_only or category) else {}
    today = date.today()
    items: list[dict[str, Any]] = []

    for item, container_id, parent_id, location in iter_items(data):
        meta = item.get("metadata", {})

        if food_only and not _is_food(meta.get("categories", []), concepts, lang):
            continue

        if category and not _category_matches(meta.get("categories", []), category, concepts, lang):
            continue

        raw_bb = meta.get("bb")
        if not raw_bb:
            continue
        bb = normalize_bb(raw_bb)
        if bb is None:
            print(f"Warning: Item with ID {item.get('id')} has a malformed best-before date ({raw_bb})")
            continue

        days_until = (date.fromisoformat(bb) - today).days
        items.append(
            {
                "id": item.get("id") or (item.get("name") or "unknown")[:20],
                "name": item.get("name", ""),
                "container": container_id,
                "parent": parent_id,
                "location": location,
                "bb": bb,
                "days": days_until,
                "expired": days_until < 0,
                "inferred": meta.get("bb_inferred", False),
            }
        )

    items.sort(key=lambda x: x["days"])
    return items


def lookup_items(inventory_path: Path, ids: list[str], matches: list[str]) -> list[dict[str, Any]]:
    """Return items whose id is in ``ids`` or whose id/name contains any ``matches`` text.

    Unlike :func:`find_expiring_items`, this also returns items with no best-before
    date (e.g. fresh produce), which is what assembling a recipe ingredient list needs.
    """
    with open(inventory_path, encoding="utf-8") as f:
        data = json.load(f)

    id_set = set(ids)
    needles = [m.lower() for m in matches]
    results: list[dict[str, Any]] = []
    for item, _container_id, _parent_id, location in iter_items(data):
        item_id = item.get("id") or ""
        name = item.get("name", "") or ""
        hay = f"{item_id} {name}".lower()
        if item_id in id_set or any(n in hay for n in needles):
            results.append(
                {
                    "id": item_id or name[:20],
                    "name": name,
                    "location": location,
                    "bb": item.get("metadata", {}).get("bb"),
                }
            )
    return results


def find_by_ean(inventory_path: Path, ean: str) -> list[dict[str, Any]]:
    """Return every item whose barcode matches ``ean``.

    Both ``ean:`` and ``isbn:`` are searched: an ISBN-13 *is* an EAN-13, and
    the barcode extractor writes books out as ``ISBN:``, so a book scanned off
    the shelf would otherwise never find its own inventory line.

    Matching goes through :func:`barcodes.ean_matches`, so separators are
    ignored and a bare number finds a shop-prefixed entry — but two different
    shops' article numbers never match each other.  All copies are returned;
    "do I already have this, and how old is the one I have" is the question
    this answers.
    """
    if not (ean or "").strip():
        return []

    with open(inventory_path, encoding="utf-8") as f:
        data = json.load(f)

    results: list[dict[str, Any]] = []
    for item, container_id, _parent_id, location in iter_items(data):
        meta = item.get("metadata", {})
        stored = next(
            (str(meta[key]) for key in ("ean", "isbn") if meta.get(key) and barcodes.ean_matches(str(meta[key]), ean)),
            None,
        )
        if stored is None:
            continue
        name = item.get("name", "") or ""
        results.append(
            {
                "id": item.get("id") or name[:20],
                "name": name,
                "container": container_id,
                "location": location,
                "ean": str(stored),
                "bb": meta.get("bb"),
            }
        )
    return results


def container_items(
    inventory_path: Path,
    container_id: str,
    include_children: bool = True,
) -> list[dict[str, Any]]:
    """Return every item in container ``container_id``.

    With ``include_children`` (default), items in direct sub-containers (those
    whose ``parent`` is ``container_id``) are included too, so inspecting a
    location group like ``pantry`` also surfaces what is in ``pantry-fridge``.

    Each dict has: id, name, container, location, bb. Returns an empty list for an
    unknown container id.
    """
    with open(inventory_path, encoding="utf-8") as f:
        data = json.load(f)

    results: list[dict[str, Any]] = []
    for item, c_id, parent_id, location in iter_items(data):
        if c_id == container_id or (include_children and parent_id == container_id):
            name = item.get("name", "") or ""
            results.append(
                {
                    "id": item.get("id") or name[:20],
                    "name": name,
                    "container": c_id,
                    "location": location,
                    "bb": item.get("metadata", {}).get("bb"),
                }
            )
    return results


def render_container(container_id: str, results: list[dict[str, Any]]) -> str:
    """Render a container listing (mirrors the lookup report wording)."""
    lines = [f"Items in container {container_id}:", ""]
    for r in results:
        lines.append(f"  {r['id']}")
        lines.append(f"    {r['name']}")
        lines.append(f"    Location: {r['location']}")
        lines.append(f"    {bb_status(r['bb'])}")
        lines.append("")
    return "\n".join(lines)


def filter_expiring(
    items: list[dict[str, Any]],
    before: str | None = None,
    limit: int | None = None,
    show_all: bool = False,
) -> list[dict[str, Any]]:
    """Apply the expiry-report selection rules.

    Precedence matches the original script: ``before`` wins, then ``limit``, then
    (by default) only already-expired items, unless ``show_all`` is set.
    """
    if before:
        if len(before) == 7:
            before += "-01"
        cutoff = date.fromisoformat(before)
        return [i for i in items if date.fromisoformat(i["bb"]) < cutoff]
    if limit is not None:
        return items[:limit]
    if not show_all:
        return [i for i in items if i["expired"]]
    return items


def render_expiring(items: list[dict[str, Any]]) -> str:
    """Render the expiry report (matches the historical script output)."""
    lines = ["Items to use/check first (by expiry date):", ""]
    for item in items:
        inferred_marker = " ~EST" if item["inferred"] else ""
        if item["expired"]:
            status = f"EXPIRED {-item['days']}d ago"
        elif item["days"] <= 30:
            status = f"{item['days']}d left ⚠️"
        else:
            status = f"{item['days']}d left"
        name = item["name"][:45] if len(item["name"]) > 45 else item["name"]
        lines.append(f"  {item['id']}")
        lines.append(f"    {name}")
        lines.append(f"    Location: {item['location']}")
        lines.append(f"    Expires: {item['bb']}{inferred_marker} [{status}]")
        lines.append("")
    return "\n".join(lines)


def render_lookup(results: list[dict[str, Any]]) -> str:
    """Render lookup results (matches the historical script output)."""
    lines: list[str] = []
    for r in results:
        lines.append(f"  {r['id']}")
        lines.append(f"    {r['name']}")
        lines.append(f"    Location: {r['location']}")
        lines.append(f"    {bb_status(r['bb'])}")
        lines.append("")
    return "\n".join(lines)


def expiring_command(
    inventory_path: Path,
    food_only: bool = False,
    category: str | None = None,
    limit: int | None = None,
    before: str | None = None,
    show_all: bool = False,
    lang: str = "en",
) -> int:
    """Implement ``inventory-md expiring``."""
    if not inventory_path.exists():
        print(f"Error: {inventory_path} not found", file=sys.stderr)
        print("Run: inventory-md parse inventory.md", file=sys.stderr)
        return 1

    items = find_expiring_items(inventory_path, food_only=food_only, category=category, lang=lang)
    items = filter_expiring(items, before=before, limit=limit, show_all=show_all)

    if not items:
        print("No matching items found.")
        return 0

    print(render_expiring(items), end="")
    return 0


def lookup_command(inventory_path: Path, ids: list[str], matches: list[str]) -> int:
    """Implement ``inventory-md lookup``."""
    if not inventory_path.exists():
        print(f"Error: {inventory_path} not found", file=sys.stderr)
        print("Run: inventory-md parse inventory.md", file=sys.stderr)
        return 1

    if not ids and not matches:
        print("Nothing to look up. Pass --id and/or --match (see --help).", file=sys.stderr)
        return 1

    results = lookup_items(inventory_path, ids, matches)
    if not results:
        print("No matching items found.")
        return 0

    print(render_lookup(results), end="")
    return 0


def container_command(
    inventory_path: Path,
    container_id: str,
    include_children: bool = True,
) -> int:
    """Implement ``inventory-md container``."""
    if not inventory_path.exists():
        print(f"Error: {inventory_path} not found", file=sys.stderr)
        print("Run: inventory-md parse inventory.md", file=sys.stderr)
        return 1

    with open(inventory_path, encoding="utf-8") as f:
        data = json.load(f)
    known = {c.get("id") for c in data.get("containers", [])}
    if container_id not in known:
        print(f"Error: no container with id {container_id!r}", file=sys.stderr)
        return 1

    results = container_items(inventory_path, container_id, include_children=include_children)
    if not results:
        print(f"Container {container_id} is empty.")
        return 0

    print(render_container(container_id, results), end="")
    return 0
