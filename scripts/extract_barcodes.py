#!/usr/bin/env python3
"""
Extract barcodes and QR codes from images and look up product information.

Requires: pip install pyzbar pillow niquests
Optional: pip install easyocr  (for OCR text extraction)

Usage:
    ./extract_barcodes.py image.jpg [image2.jpg ...]
    ./extract_barcodes.py photos/F-01/*.jpg
    ./extract_barcodes.py --lookup 5701234567890
    ./extract_barcodes.py --lookup 978-0-13-468599-1  # ISBN lookup
    ./extract_barcodes.py --ocr photos/*.jpg  # Use OCR when no barcode found

Options:
    --lookup EAN    Look up a single EAN/ISBN without image processing
    --no-lookup     Extract barcodes but skip online lookup
    --no-cache      Skip local ISBN cache, always query online
    --ocr           Enable OCR fallback when no barcode is detected
    --ocr-only      Only run OCR, skip barcode extraction
    --best-before   OCR every image (barcode ones too) and attach best_before
        --bb        date candidates — the date is usually on the barcode photo
    --json          Output as JSON
    --out PATH      Write output to PATH instead of stdout (avoids a shell
                    `>` redirect, which breaks Bash allowlist prefix-matching)
    --no-corroborate      Scan each image once instead of corroborating a read
                          across rescaled variants (faster, misdecode-prone)
    --no-scan-undecoded   Don't check barcode-less images for a barcode that
                          is present but unreadable
    -h, --help      Show this help message

Misdecode handling:
    A valid check digit is not evidence of a correct read — an EAN-13 parity
    misdecode recomputes the checksum over the corrupted digits.  Each image is
    therefore decoded several ways (see DECODE_VARIANTS), and reads landing on
    the same spot in the photo are candidates for one symbol.  A winner is
    picked by GS1 prefix plausibility, then by "which one resolves to a known
    product", then by corroboration with a clear margin.

    A losing read is only discarded when something explains it as a misread of
    the winner (see _explains_misdecode) — sharing a place in the photo is not
    proof, since a small sticker can sit on a big label.  Anything else, and the
    photo is emitted as a single `tag:TODO` review block listing every
    candidate, rather than as several equally plausible item lines.

Supported barcodes:
    - EAN-13, EAN-8, UPC-A, UPC-E (products) -> tingbok.plann.no
    - ISBN-10, ISBN-13 (books) -> Open Library, NB.no (Norwegian)

OCR Languages:
    By default OCR uses: English, Norwegian, Swedish, Russian.
    Models are downloaded on first use (~100MB).

Local Cache:
    ISBN lookups are cached in ean_cache.json in the current directory.
    EAN lookups always go to tingbok (which handles its own aggregation).
"""

import json
import sys
from pathlib import Path

try:
    from PIL import Image
    from pyzbar.pyzbar import decode

    HAS_BARCODE_DEPS = True
except ImportError:
    # Don't sys.exit at import time — that turns into a SystemExit during pytest
    # collection (and kills any importer). Degrade gracefully like the niquests /
    # easyocr blocks below; the CLI re-checks and exits with a friendly message,
    # and extract_barcodes() raises a clear error if actually called.
    Image = None
    decode = None
    HAS_BARCODE_DEPS = False

try:
    import niquests as requests

    HAS_REQUESTS = True
except ImportError:
    try:
        import requests

        # Without this the name stays unbound on the niquests-missing /
        # requests-present install, and every later `if HAS_REQUESTS` is a
        # NameError rather than a graceful degradation.
        HAS_REQUESTS = True
    except ImportError:
        requests = None
        HAS_REQUESTS = False

try:
    import easyocr

    HAS_OCR = True
    # Lazy-loaded reader (initialized on first use)
    _ocr_reader = None
except ImportError:
    HAS_OCR = False
    _ocr_reader = None


# Default cache file location
CACHE_FILE = Path("ean_cache.json")

try:
    # bb_dates lives in the package (not scripts/) so it can be imported by
    # purchase-pipeline, which parses receipt dates with the same parser.
    from inventory_md.bb_dates import extract_best_before
except ImportError:  # pragma: no cover
    extract_best_before = None

# Checksum and confusability arithmetic lives in the package so `inventory-md
# ean` and check_quality can share it. Re-exported here for callers (and tests)
# that only import this script.
from inventory_md.barcodes import (  # noqa: E402  (kept next to its sibling import)
    is_parity_confusable,
    is_restricted_gs1_prefix,
    validate_ean_checksum,
    validate_upce_checksum,
)


def load_cache(cache_path: Path) -> dict:
    """Load the local EAN cache."""
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load cache: {e}", file=sys.stderr)
    return {}


def save_cache(cache: dict, cache_path: Path):
    """Save the local EAN cache."""
    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Warning: Could not save cache: {e}", file=sys.stderr)


# Decoding the same photo more than once, differently, is how we tell a real
# read from a misdecode.  zbar's own uncertainty threshold is not reachable
# through pyzbar (it only sets ZBAR_CFG_ENABLE), so we corroborate at this
# level instead: rescaling re-quantises the bar widths and autocontrast changes
# the binarisation threshold, so a read that survived a bar-width error at one
# scale is unlikely to reproduce at another.  A code seen in only one variant
# is weak evidence.
DECODE_VARIANTS = ("original", "scale-0.6", "autocontrast")


_VARIANT_SCALE = 0.6


def _decode_variants(image: "Image.Image") -> list[tuple["Image.Image", float]]:
    """Return ``(image, scale)`` pairs for the renderings :func:`extract_barcodes` scans.

    ``scale`` maps a coordinate in the variant back to the original image, so
    every read can be located in one shared coordinate system.
    """
    from PIL import ImageOps

    base = ImageOps.exif_transpose(image)
    w, h = base.size
    small = base.resize((max(1, int(w * _VARIANT_SCALE)), max(1, int(h * _VARIANT_SCALE))), Image.LANCZOS)
    return [
        (base, 1.0),
        (small, _VARIANT_SCALE),
        (ImageOps.autocontrast(base.convert("L")), 1.0),
    ]


def extract_barcodes(image_path: Path, corroborate: bool = True) -> list[dict]:
    """
    Extract all barcodes and QR codes from an image.

    Returns list of dicts with: type, data, polygon, bbox, corroboration, variants.

    ``bbox`` is ``(left, top, right, bottom)`` in the original image's
    coordinates — where in the photo the code was read — and ``corroboration``
    is how many of the ``variants`` decode passes produced this exact code.
    :func:`resolve_candidates` uses both to pick between conflicting reads.
    With ``corroborate=False`` the image is scanned once (faster, but every code
    then looks equally trustworthy).
    """
    if not HAS_BARCODE_DEPS:
        raise RuntimeError("Barcode scanning requires pyzbar and pillow (pip install pyzbar pillow)")
    try:
        image = Image.open(image_path)
        image.load()
    except Exception as e:
        print(f"Error reading {image_path}: {e}", file=sys.stderr)
        return []

    from PIL import ImageOps

    variants = _decode_variants(image) if corroborate else [(ImageOps.exif_transpose(image), 1.0)]

    # Corroboration counts *variants that agreed*, not decoded occurrences: two
    # copies of the same product in one frame are one variant agreeing twice,
    # and counting them twice would make "3 of 3 decode passes" a lie and break
    # the margin rule that rests on it.
    seen_in: dict[tuple[str, str], set[int]] = {}
    found: dict[tuple[str, str], dict] = {}
    for index, (variant, scale) in enumerate(variants):
        for barcode in decode(variant):
            key = (barcode.type, barcode.data.decode("utf-8"))
            seen_in.setdefault(key, set()).add(index)
            if key in found:
                continue
            # Polygons are reported verbatim only for the original image; a
            # rescaled read still contributes its location, mapped back.
            polygon = None
            bbox = None
            if barcode.polygon:
                xs = [p.x / scale for p in barcode.polygon]
                ys = [p.y / scale for p in barcode.polygon]
                bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
                if index == 0:
                    polygon = [(p.x, p.y) for p in barcode.polygon]
            found[key] = {
                "type": key[0],  # EAN13, EAN8, UPCA, QRCODE, CODE128, etc.
                "data": key[1],
                "polygon": polygon,
                "bbox": bbox,
            }

    results = []
    for key, entry in found.items():
        entry["corroboration"] = len(seen_in[key])
        entry["variants"] = len(variants)
        results.append(entry)

    return results


def bbox_overlap_fraction(a: tuple | None, b: tuple | None) -> float:
    """Overlap of two ``(left, top, right, bottom)`` boxes, over the smaller area.

    Over the *smaller* area rather than the union, because a misdecode is often
    read from a subset of the symbol's scanlines and so gets a box nested inside
    the good read's.  Returns 0.0 when either box is missing or degenerate.
    """
    if not a or not b:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    if area_a <= 0 or area_b <= 0:
        return 0.0
    overlap_w = min(ax1, bx1) - max(ax0, bx0)
    overlap_h = min(ay1, by1) - max(ay0, by0)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    return (overlap_w * overlap_h) / min(area_a, area_b)


# Two reads whose boxes overlap this much are reads of one physical symbol.
_SAME_SYMBOL_OVERLAP = 0.5


def _same_symbol(a: dict, b: dict) -> bool:
    """Return True if two candidates look like reads of the same barcode.

    Location is the primary evidence: reads of one symbol land in one place, and
    two symbols in a shelf photo do not.  It also catches misdecodes the digits
    cannot — a corrupted *right* half leaves no parity signature, which is how
    3800874988780 slipped past as a third peer read of the sausage label.  When a
    box is missing (a code that decoded without a polygon), fall back to the
    digit signature.
    """
    if a.get("bbox") and b.get("bbox"):
        return bbox_overlap_fraction(a["bbox"], b["bbox"]) >= _SAME_SYMBOL_OVERLAP
    return is_parity_confusable(a["data"], b["data"])


def _confusable_groups(candidates: list[dict]) -> list[list[dict]]:
    """Partition candidates into connected groups of same-symbol reads.

    Proper connected components, not "join the first group that matches" —
    overlap is not transitive, so a wide box bridging two disjoint ones has to
    merge all three regardless of the order they arrive in.  The old loop never
    merged existing groups, which made the result depend on input order.
    """
    parent = list(range(len(candidates)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if _same_symbol(candidates[i], candidates[j]):
                parent[find(i)] = find(j)

    groups: dict[int, list[dict]] = {}
    for i, candidate in enumerate(candidates):
        groups.setdefault(find(i), []).append(candidate)
    return list(groups.values())


# How much better-corroborated a candidate must be before corroboration alone
# decides a conflict.  On IMG_20260715_123606.jpg the phantom 3200274928780 beat
# the real 3800214928780 by 3 reads to 2 — a majority, and wrong.  So a bare
# majority is not enough: require a clean sweep (with three variants, 3-vs-1).
_CORROBORATION_MARGIN = 2


def _explains_misdecode(loser: str, winner: str, resolves) -> bool:
    """Return True if ``loser`` is accounted for as a bad read of ``winner``.

    Sharing a place in the photo makes two codes *candidates* for one symbol; it
    does not prove it, because a small sticker can sit on a big label.  One of
    these has to hold before a loser is dropped rather than flagged:

    * the parity signature — same length, identical right half, which is what an
      EAN-13 left-half misdecode looks like;
    * a restricted-distribution GS1 prefix, which a retail pack never carries;
    * the winner resolves to a known product and the loser resolves to nothing,
      the case of a right-half misdecode that leaves no parity signature.
    """
    return (
        is_parity_confusable(loser, winner)
        or is_restricted_gs1_prefix(loser)
        or (resolves(winner) and not resolves(loser))
    )


def _resolve_group(members: list[dict], candidates: list[dict], resolver) -> None:
    """Decide a single confusable group, annotating ``candidates`` in place.

    Evidence in decreasing order of trustworthiness:

    1. **GS1 prefix.** Exactly one candidate whose prefix a retail pack could
       carry — free, offline, and unaffected by what any database happens to
       know.
    2. **Product resolution.** Exactly one candidate that ``resolver`` knows.
       Strong, but it costs a lookup and a database can be contaminated by an
       earlier run that pushed a phantom back to it.
    3. **Corroboration**, and only by a clean margin. It is the weakest signal:
       a misdecode that reproduces at one scale tends to reproduce at the next.

    If none of them settles it, nobody wins and the caller gets a review flag.
    """
    # Deterministic order: best corroborated first, then lexical.
    members = sorted(members, key=lambda c: (-c["corroboration"], c["data"]))
    datas = sorted(c["data"] for c in members)

    # A lone candidate is never checked against a product database (see
    # resolve_candidates), and within a group each code is asked about at most
    # once. A resolver that raises reports a network fault, not a verdict: it
    # must not abort a batch scan that has already read dozens of photos.
    verdicts: dict[str, bool] = {}

    def resolves(code: str) -> bool:
        if code not in verdicts:
            if resolver is None:
                verdicts[code] = False
            else:
                try:
                    verdicts[code] = bool(resolver(code))
                except Exception as e:  # noqa: BLE001 — any lookup failure means "unknown"
                    print(f"Warning: product lookup failed for {code}: {e}", file=sys.stderr)
                    verdicts[code] = False
        return verdicts[code]

    winner = None
    why = ""
    plausible = [c for c in members if not is_restricted_gs1_prefix(c["data"])]
    if len(plausible) == 1:
        winner = plausible[0]
        others = ", ".join(d for d in datas if d != winner["data"])
        why = f"the only candidate whose GS1 prefix a retail pack can carry; {others} is restricted-distribution"
    else:
        resolved = [c for c in members if resolves(c["data"])]
        if len(resolved) == 1:
            winner = resolved[0]
            why = "the only candidate that resolves to a known product"

    if winner is None and members[0]["corroboration"] - members[1]["corroboration"] >= _CORROBORATION_MARGIN:
        winner = members[0]
        why = f"{winner['corroboration']} of {winner.get('variants', 1)} decode passes agreed"

    # Winning is not enough to delete the others. Reads are grouped by where they
    # sit in the photo, and two *different* products can share that space — a
    # small sticker on a big label, one package lying over another. Discard a
    # loser only when something actually explains it as a misread of the winner;
    # otherwise the group is ambiguous and a human has to look, because the
    # alternative is deleting a real product from the output.
    if winner is not None:
        unexplained = [d for d in datas if d != winner["data"] and not _explains_misdecode(d, winner["data"], resolves)]
        if unexplained:
            winner = None

    if winner is not None:
        losers = [d for d in datas if d != winner["data"]]
        for candidate in candidates:
            if candidate["data"] == winner["data"]:
                candidate["status"] = "ok"
                candidate["discarded"] = losers
            elif candidate["data"] in datas:
                candidate["status"] = "rejected"
                candidate["status_reason"] = f"conflicts with {winner['data']} ({why})"
        return

    representative = members[0]["data"]
    for candidate in candidates:
        if candidate["data"] == representative:
            candidate["status"] = "needs_review"
            candidate["alternatives"] = datas
            candidate["status_reason"] = "conflicting barcode reads; cannot tell which one is the misdecode"
        elif candidate["data"] in datas:
            candidate["status"] = "rejected"
            candidate["status_reason"] = f"reported as an alternative under {representative}"


def resolve_candidates(candidates: list[dict], resolver=None) -> list[dict]:
    """Annotate one image's barcode candidates with a ``status``.

    ``status`` is ``ok`` (use it), ``needs_review`` (the caller must look) or
    ``rejected`` (a losing read, kept only so ``--json`` shows what happened).

    Two codes are treated as conflicting only when they are parity-confusable
    (:func:`is_parity_confusable`) — a photo of a shelf with several different
    products is not a conflict and stays untouched.  A conflict is decided by
    corroboration first, and only if that ties by ``resolver(code)``, an
    optional callable returning a product record or ``None``.

    Returns new dicts; the input is not modified.
    """
    annotated = [dict(c) for c in candidates]
    for candidate in annotated:
        candidate.setdefault("corroboration", 1)
        candidate["status"] = "ok"

    # Only product codes can be parity-misdecoded; QR/CODE128 payloads pass through.
    best_per_code: dict[str, dict] = {}
    for candidate in annotated:
        if not is_lookupable(candidate["type"], candidate["data"])[0]:
            continue
        previous = best_per_code.get(candidate["data"])
        if previous is None or candidate["corroboration"] > previous["corroboration"]:
            best_per_code[candidate["data"]] = candidate

    if len(best_per_code) < 2:
        return annotated

    for group in _confusable_groups([best_per_code[d] for d in sorted(best_per_code)]):
        if len(group) > 1:
            _resolve_group(group, annotated, resolver)

    return annotated


# Thresholds for the "there is a barcode here I could not read" heuristic.
# A barcode band is (a) busy along each row and (b) near-identical from one row
# to the next, because the bars run the full height of the symbol. Text is busy
# too, but loses that vertical coherence every few rows.
_STRIPE_MIN_TRANSITIONS = 20
_STRIPE_MIN_ROWS = 20
_STRIPE_ROW_AGREEMENT = 0.9
_STRIPE_ANALYSIS_SIZE = 512


def looks_like_undecoded_barcode(image_path: Path) -> bool:
    """Return True if the image seems to contain a barcode that zbar did not read.

    Motivating specimen: a diving-mask label torn straight through the right-hand
    quiet zone (which zbar requires), with a striated thermal print texture.  The
    digits are plainly legible to a human and zbar returns nothing at all — no
    amount of crop/rotation retrying helps.  Silence is the worst possible
    answer there, because the photo then looks like it simply had no barcode.

    This detects *presence*, not the specific defect: a hit means "damaged,
    occluded, blurred, or missing quiet zone — go look", not "quiet zone torn".
    """
    if not HAS_BARCODE_DEPS:
        return False
    try:
        from PIL import ImageOps

        img = ImageOps.exif_transpose(Image.open(image_path)).convert("L")
    except Exception:
        return False

    img.thumbnail((_STRIPE_ANALYSIS_SIZE, _STRIPE_ANALYSIS_SIZE))
    width, height = img.size
    if width < 40 or height < _STRIPE_MIN_ROWS:
        return False

    pixels = ImageOps.autocontrast(img).load()

    run = 0
    previous: list[int] | None = None
    for y in range(height):
        row = [1 if pixels[x, y] > 127 else 0 for x in range(width)]
        transitions = sum(1 for x in range(1, width) if row[x] != row[x - 1])
        if transitions < _STRIPE_MIN_TRANSITIONS:
            run, previous = 0, None
            continue
        if previous is None:
            run = 1
        else:
            agreement = sum(1 for x in range(width) if row[x] == previous[x]) / width
            run = run + 1 if agreement >= _STRIPE_ROW_AGREEMENT else 1
        if run >= _STRIPE_MIN_ROWS:
            return True
        previous = row

    return False


def get_ocr_reader(languages: list[str] | None = None) -> "easyocr.Reader | None":
    """
    Get or initialize the OCR reader (lazy loading).

    Args:
        languages: List of language codes. Default: ['en', 'no', 'sv', 'ru']

    Returns:
        easyocr.Reader instance or None if OCR not available.
    """
    global _ocr_reader

    if not HAS_OCR:
        return None

    if _ocr_reader is None:
        if languages is None:
            languages = ["en", "no", "sv", "ru"]
        print(f"Initializing OCR with languages: {languages}", file=sys.stderr)
        _ocr_reader = easyocr.Reader(languages, gpu=False)

    return _ocr_reader


def extract_text_ocr(
    image_path: Path,
    languages: list[str] | None = None,
    min_confidence: float = 0.3,
    rotation_info: list[int] | None = None,
    angles: list[int] | None = None,
) -> list[dict]:
    """
    Extract text from an image using OCR.

    Args:
        image_path: Path to the image file.
        languages: List of language codes for OCR.
        min_confidence: Minimum confidence threshold (0-1).

    Returns:
        List of dicts with: text, confidence, bbox (bounding box coordinates).
    """
    reader = get_ocr_reader(languages)
    if reader is None:
        return []

    try:
        import numpy as np
        from PIL import ImageOps

        # Honour the EXIF orientation tag — PIL/easyocr otherwise read the raw
        # sensor orientation, so a photo that looks upright in the gallery is
        # fed to OCR sideways/upside-down. This is the main orientation fix
        # (assuming labels are shot roughly upright). Downscale big phone photos.
        img = ImageOps.exif_transpose(Image.open(image_path).convert("RGB"))
        if max(img.size) > 2600:
            img.thumbnail((2600, 2600))

        # Optional extra orientations (PIL-rotated ourselves; easyocr's own
        # rotation_info crashes on some images). An explicit `angles` list wins
        # (used by extract_text_ocr_oriented to OCR one orientation at a time);
        # otherwise 0° plus any legacy `rotation_info` extras.
        if angles is None:
            angles = [0, *(rotation_info or [])]
        extracted = []
        for angle in angles:
            arr = np.asarray(img.rotate(-angle, expand=True) if angle else img)
            for bbox, text, confidence in reader.readtext(arr):
                if confidence >= min_confidence:
                    # Coerce numpy types (from array input) to JSON-serialisable natives.
                    extracted.append(
                        {
                            "text": text,
                            "confidence": float(confidence),
                            "bbox": [[int(p[0]), int(p[1])] for p in bbox],
                        }
                    )
        return extracted
    except Exception as e:
        print(f"OCR failed for {image_path}: {e}", file=sys.stderr)
        return []


def _text_quality(ocr_results: list[dict]) -> float:
    """Heuristic quality score for one OCR pass.

    Summed confidence over tokens carrying >=3 alphanumeric characters. A photo
    shot sideways/upside-down OCRs into a scatter of 1-2 char fragments that
    score ~0; a correctly-oriented label or receipt scores several points. Used
    by extract_text_ocr_oriented to pick the best rotation.
    """
    score = 0.0
    for r in ocr_results:
        text = r.get("text", "")
        if sum(c.isalnum() for c in text) >= 3:
            score += float(r.get("confidence", 0.0))
    return score


def extract_text_ocr_oriented(
    image_path: Path,
    languages: list[str] | None = None,
    min_confidence: float = 0.3,
    accept_score: float = 3.0,
) -> list[dict]:
    """OCR with automatic rotation retry for photos shot sideways/upside-down.

    Runs the EXIF-corrected 0° orientation first; if its text quality is poor
    (a sign the photo is physically rotated with a missing/wrong EXIF tag), it
    retries at 90°/270°/180° and returns the results from the best-scoring
    orientation. Upright photos incur no extra cost — they clear ``accept_score``
    on the first pass. See _text_quality for the scoring heuristic.
    """
    best = extract_text_ocr(image_path, languages=languages, min_confidence=min_confidence, angles=[0])
    best_score = _text_quality(best)
    if best_score >= accept_score:
        return best
    for angle in (90, 270, 180):
        res = extract_text_ocr(image_path, languages=languages, min_confidence=min_confidence, angles=[angle])
        score = _text_quality(res)
        if score > best_score:
            best, best_score = res, score
            if best_score >= accept_score:
                break
    return best


def extract_title_from_ocr(ocr_results: list[dict], min_confidence: float = 0.5) -> str | None:
    """
    Try to extract a book title from OCR results.

    Heuristic: Look for the largest/most prominent text with high confidence.
    Usually book titles are in larger fonts.

    Args:
        ocr_results: Results from extract_text_ocr().
        min_confidence: Minimum confidence to consider.

    Returns:
        Best candidate for book title, or None.
    """
    if not ocr_results:
        return None

    # Filter by confidence and sort by text length (longer text more likely to be title)
    candidates = [r for r in ocr_results if r["confidence"] >= min_confidence]

    if not candidates:
        return None

    # Sort by a score: prefer longer text with higher confidence
    # Also prefer text that's not just numbers or single words
    def score(r):
        text = r["text"].strip()
        # Penalize very short text
        length_score = min(len(text) / 20, 1.0)
        # Penalize text that's mostly numbers
        alpha_ratio = sum(c.isalpha() for c in text) / max(len(text), 1)
        return r["confidence"] * length_score * alpha_ratio

    candidates.sort(key=score, reverse=True)

    # Return the best candidate if it looks like a title
    best = candidates[0]
    if len(best["text"].strip()) >= 3:
        return best["text"].strip()

    return None


def lookup_tingbok(ean: str) -> dict | None:
    """
    Look up an EAN using tingbok.plann.no (primary product database).

    Tingbok aggregates multiple sources (OpenFoodFacts, etc.) internally.
    Returns product info dict or None if not found.
    """
    if not HAS_REQUESTS:
        return None

    url = f"https://tingbok.plann.no/api/ean/{ean}"

    try:
        response = requests.get(
            url, timeout=10, headers={"User-Agent": "InventorySystem/1.0 (https://github.com/tobixen/inventory-md)"}
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return {
            "ean": ean,
            "name": data.get("name"),
            "brand": data.get("brand"),
            "quantity": data.get("quantity"),
            "categories": data.get("categories"),
            "image_url": data.get("image_url"),
            "source": "tingbok",
        }
    except requests.RequestException as e:
        print(f"tingbok lookup failed for {ean}: {e}", file=sys.stderr)
        return None


def normalize_isbn(isbn: str) -> str:
    """Remove hyphens and spaces from ISBN."""
    return isbn.replace("-", "").replace(" ", "")


def validate_isbn10_checksum(isbn: str) -> bool:
    """Validate ISBN-10 check digit."""
    if len(isbn) != 10:
        return False

    total = 0
    for i, char in enumerate(isbn[:-1]):
        if not char.isdigit():
            return False
        total += int(char) * (10 - i)

    # Last digit can be 'X' (represents 10)
    last = isbn[-1].upper()
    if last == "X":
        total += 10
    elif last.isdigit():
        total += int(last)
    else:
        return False

    return total % 11 == 0


def validate_isbn13_checksum(isbn: str) -> bool:
    """Validate ISBN-13 check digit (same as EAN-13)."""
    if len(isbn) != 13 or not isbn.isdigit():
        return False
    if not isbn.startswith(("978", "979")):
        return False
    return validate_ean_checksum(isbn)


def is_isbn(data: str) -> bool:
    """Check if a string is a valid ISBN-10 or ISBN-13."""
    normalized = normalize_isbn(data)

    if len(normalized) == 10:
        return validate_isbn10_checksum(normalized)
    elif len(normalized) == 13:
        return validate_isbn13_checksum(normalized)
    return False


def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert ISBN-10 to ISBN-13."""
    isbn10 = normalize_isbn(isbn10)
    if len(isbn10) != 10:
        return isbn10

    # Add 978 prefix and recalculate check digit
    base = "978" + isbn10[:-1]
    digits = [int(d) for d in base]
    total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    check = (10 - (total % 10)) % 10
    return base + str(check)


def lookup_openlibrary(isbn: str) -> dict | None:
    """
    Look up an ISBN using Open Library API.

    Returns book info dict or None if not found.
    """
    if not HAS_REQUESTS:
        return None

    normalized = normalize_isbn(isbn)

    # Convert ISBN-10 to ISBN-13 for consistency
    if len(normalized) == 10:
        isbn13 = isbn10_to_isbn13(normalized)
    else:
        isbn13 = normalized

    url = f"https://openlibrary.org/isbn/{normalized}.json"

    try:
        response = requests.get(
            url, timeout=10, headers={"User-Agent": "InventorySystem/1.0 (https://github.com/tobixen/inventory-md)"}
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        # Get author information (requires additional API call)
        authors = []
        for author_ref in data.get("authors", []):
            author_key = author_ref.get("key")
            if author_key:
                try:
                    author_resp = requests.get(
                        f"https://openlibrary.org{author_key}.json",
                        timeout=5,
                        headers={"User-Agent": "InventorySystem/1.0"},
                    )
                    if author_resp.status_code == 200:
                        author_data = author_resp.json()
                        authors.append(author_data.get("name", ""))
                except requests.RequestException:
                    pass

        return {
            "isbn": isbn13,
            "isbn_input": isbn,
            "name": data.get("title"),
            "authors": authors,
            "author": ", ".join(authors) if authors else None,
            "publisher": (data.get("publishers") or [None])[0],
            "publish_date": data.get("publish_date"),
            "pages": data.get("number_of_pages"),
            "subjects": [s.get("name") if isinstance(s, dict) else s for s in data.get("subjects", [])[:5]],
            "cover_id": data.get("covers", [None])[0],
            "source": "openlibrary",
            "type": "book",
        }
    except requests.RequestException as e:
        print(f"Open Library lookup failed for {isbn}: {e}", file=sys.stderr)
        return None


def lookup_nb_no(isbn: str) -> dict | None:
    """
    Look up an ISBN using Norwegian National Library (nb.no) API.

    Best for Norwegian books (ISBN starting with 978-82-).
    Returns book info dict or None if not found.
    """
    if not HAS_REQUESTS:
        return None

    normalized = normalize_isbn(isbn)

    # Convert ISBN-10 to ISBN-13 for consistency
    if len(normalized) == 10:
        isbn13 = isbn10_to_isbn13(normalized)
    else:
        isbn13 = normalized

    url = f"https://api.nb.no/catalog/v1/items?q=isbn:{normalized}"

    try:
        response = requests.get(
            url, timeout=10, headers={"User-Agent": "InventorySystem/1.0 (https://github.com/tobixen/inventory-md)"}
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        # Check if we got results
        embedded = data.get("_embedded", {})
        items = embedded.get("items", [])

        if not items:
            return None

        item = items[0]
        metadata = item.get("metadata", {})

        # Extract authors from creators (list of strings)
        creators = metadata.get("creators", [])
        authors = [c for c in creators if isinstance(c, str)]

        # Extract title
        title = metadata.get("title")

        # Extract publisher and date from originInfo (dict, not list)
        origin_info = metadata.get("originInfo", {})
        publisher = origin_info.get("publisher")
        publish_date = origin_info.get("issued")

        return {
            "isbn": isbn13,
            "isbn_input": isbn,
            "name": title,
            "authors": authors,
            "author": ", ".join(authors) if authors else None,
            "publisher": publisher,
            "publish_date": publish_date,
            "pages": None,  # Not available in this API response
            "subjects": [],
            "source": "nb.no",
            "type": "book",
        }
    except requests.RequestException as e:
        print(f"NB.no lookup failed for {isbn}: {e}", file=sys.stderr)
        return None


def lookup_isbn(isbn: str) -> dict | None:
    """
    Look up an ISBN using multiple APIs with fallback.

    Tries Open Library first, then Norwegian National Library for 978-82-* ISBNs.
    Returns book info dict or None if not found.
    """
    # Try Open Library first (international coverage)
    product = lookup_openlibrary(isbn)
    if product and product.get("name"):
        return product

    # For Norwegian ISBNs (978-82-*), try nb.no as fallback
    normalized = normalize_isbn(isbn)
    if normalized.startswith("97882"):
        product = lookup_nb_no(isbn)
        if product and product.get("name"):
            return product

    return None


def lookup_code(code: str, cache: dict, use_cache: bool = True) -> tuple[dict | None, bool]:
    """
    Look up an EAN or ISBN.

    EANs always query tingbok directly (no local caching).
    ISBNs check local cache first, then Open Library / NB.no.

    Returns (product_info, was_cached).
    """
    if is_isbn(code):
        cache_key = normalize_isbn(code)
        if use_cache and cache_key in cache:
            cached = cache[cache_key]
            if cached is None:
                return None, True
            return cached, True
        product = lookup_isbn(code)
        return product, False
    else:
        product = lookup_tingbok(code)
        return product, False


# Backwards compatibility alias
def lookup_ean(ean: str, cache: dict, use_cache: bool = True) -> tuple[dict | None, bool]:
    """Look up an EAN, checking cache first. (Alias for lookup_code)"""
    return lookup_code(ean, cache, use_cache)


def is_lookupable(barcode_type: str, data: str) -> tuple[bool, str]:
    """
    Check if barcode can be looked up online.

    Returns (can_lookup, code_type) where code_type is 'ean', 'isbn', or ''.
    """
    # Check for ISBN first (ISBN-13 starts with 978/979)
    normalized = normalize_isbn(data)
    if len(normalized) == 13 and normalized.startswith(("978", "979")):
        if validate_isbn13_checksum(normalized):
            return True, "isbn"
    if len(normalized) == 10 and validate_isbn10_checksum(normalized):
        return True, "isbn"

    # UPC-E's check digit covers the *expanded* UPC-A, not the eight characters
    # as printed, so EAN-8 arithmetic rejects genuine reads.
    if barcode_type == "UPCE":
        if not validate_upce_checksum(data):
            print(f"Warning: Invalid checksum for {data}", file=sys.stderr)
            return False, ""
        return True, "ean"

    # Check for EAN/UPC
    if barcode_type in ("EAN13", "EAN8", "UPCA"):
        if not validate_ean_checksum(data):
            print(f"Warning: Invalid checksum for {data}", file=sys.stderr)
            return False, ""
        return True, "ean"

    # Some barcodes encode EANs as other types
    if barcode_type == "CODE128" and data.isascii() and data.isdigit() and len(data) in (8, 12, 13):
        if not validate_ean_checksum(data):
            print(f"Warning: Invalid checksum for {data}", file=sys.stderr)
            return False, ""
        return True, "ean"

    return False, ""


def is_ean(barcode_type: str, data: str) -> bool:
    """Check if barcode is a valid product EAN/UPC that can be looked up. (Legacy)"""
    can_lookup, _ = is_lookupable(barcode_type, data)
    return can_lookup


def format_for_inventory(barcode: dict, product: dict | None) -> str:
    """Format barcode info for inventory.md."""
    code = barcode["data"]
    barcode_type = barcode["type"]

    if product and product.get("name"):
        name = product["name"]

        # Handle books differently
        if product.get("type") == "book":
            isbn = product.get("isbn", code)
            author = product.get("author", "")
            publisher = product.get("publisher", "")
            publish_date = product.get("publish_date", "")

            parts = [f"tag:book ISBN:{isbn}"]
            if author:
                parts.append(f'"{name}" by {author}')
            else:
                parts.append(f'"{name}"')
            if publisher:
                parts.append(f"({publisher}")
                if publish_date:
                    parts[-1] += f", {publish_date})"
                else:
                    parts[-1] += ")"
            elif publish_date:
                parts.append(f"({publish_date})")

            return "* " + " ".join(parts)
        else:
            # Regular product
            brand = product.get("brand", "")
            quantity = product.get("quantity", "")

            parts = []
            if brand:
                parts.append(brand)
            parts.append(name)
            if quantity:
                parts.append(f"({quantity})")

            desc = " ".join(parts)
            line = f"* EAN:{code} {desc}"
    else:
        # Check if it's an ISBN
        if is_isbn(code):
            line = f"* tag:book ISBN:{normalize_isbn(code)} (unknown book)"
        else:
            line = f"* EAN:{code} (unknown product, type: {barcode_type})"

    discarded = barcode.get("discarded")
    if discarded:
        line += f"\n    # Discarded conflicting read(s): {', '.join(discarded)}"
    return line


def format_flagged(result: dict) -> str:
    """Format a candidate the caller has to look at, as a single tag:TODO block.

    Conflicting reads are deliberately *not* emitted as peer item lines: two
    plausible-looking EANs side by side invite picking the wrong one, since
    both carry a valid check digit.
    """
    if result.get("type") == "NO_DECODE":
        return (
            "* tag:TODO (barcode-like pattern detected, but nothing decoded)\n"
            "    # The code may be torn, occluded, blurred, or missing the quiet\n"
            "    # zone zbar needs. Read the digits by hand, then: inventory-md ean EAN"
        )

    alternatives = result.get("alternatives") or [result["data"]]
    return (
        f"* tag:TODO EAN:{result['data']} (needs review — conflicting barcode reads)\n"
        f"    # Candidates: {', '.join(alternatives)}\n"
        "    # Identical right half, different left half: an EAN-13 parity misdecode\n"
        "    # recomputes the check digit, so every candidate here looks valid."
    )


def main():
    import argparse

    if not HAS_BARCODE_DEPS:
        print("Error: Required packages not installed.", file=sys.stderr)
        print("Run: pip install pyzbar pillow", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Extract and look up barcodes from images.")
    parser.add_argument("images", nargs="*", type=Path, metavar="IMAGE", help="Image file(s) to scan")
    parser.add_argument("--no-lookup", action="store_true", help="Skip product lookup")
    parser.add_argument("--no-cache", action="store_true", help="Ignore cached lookups")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--out",
        metavar="PATH",
        type=Path,
        help="Write output to PATH instead of stdout (avoids a shell > redirect)",
    )
    parser.add_argument("--ocr", action="store_true", help="Enable OCR fallback")
    parser.add_argument("--ocr-only", action="store_true", help="Use OCR only (implies --ocr)")
    parser.add_argument(
        "--best-before", "--bb", dest="bb_mode", action="store_true", help="Extract best-before dates (implies --ocr)"
    )
    parser.add_argument("--lookup", metavar="CODE", help="Look up a single EAN/ISBN")
    parser.add_argument(
        "--no-corroborate",
        action="store_true",
        help="Scan each image once instead of corroborating across rescaled variants (faster, misdecode-prone)",
    )
    parser.add_argument(
        "--no-scan-undecoded",
        action="store_true",
        help="Don't check barcode-less images for an unreadable barcode",
    )
    ns = parser.parse_args()

    do_lookup = not ns.no_lookup
    use_cache = not ns.no_cache
    output_json = ns.json
    single_lookup = ns.lookup
    enable_ocr = ns.ocr or ns.ocr_only or ns.bb_mode
    ocr_only = ns.ocr_only
    bb_mode = ns.bb_mode
    image_paths = ns.images

    # Load cache
    cache = load_cache(CACHE_FILE) if use_cache else {}
    cache_modified = False

    # Single EAN/ISBN lookup mode
    if single_lookup:
        # Determine cache key
        cache_key = normalize_isbn(single_lookup) if is_isbn(single_lookup) else single_lookup

        if not HAS_REQUESTS and cache_key not in cache:
            print("Error: requests package required for lookup", file=sys.stderr)
            print("Run: pip install requests", file=sys.stderr)
            sys.exit(1)

        product, was_cached = lookup_code(single_lookup, cache, use_cache)

        # Only cache ISBNs locally
        if not was_cached and use_cache and is_isbn(single_lookup):
            cache[cache_key] = product
            save_cache(cache, CACHE_FILE)

        if output_json:
            print(json.dumps(product, indent=2))
        elif product:
            if product.get("type") == "book":
                # Book output
                print(f"ISBN: {product.get('isbn', single_lookup)}")
                print(f"Title: {product.get('name', 'Unknown')}")
                print(f"Author: {product.get('author', 'Unknown')}")
                print(f"Publisher: {product.get('publisher', 'Unknown')}")
                print(f"Published: {product.get('publish_date', 'Unknown')}")
                print(f"Pages: {product.get('pages', 'Unknown')}")
                if product.get("subjects"):
                    print(f"Subjects: {', '.join(str(s) for s in product['subjects'][:3])}")
                print(f"Source: {product.get('source', 'unknown')}")
            else:
                # Product output
                print(f"EAN: {single_lookup}")
                print(f"Name: {product.get('name', 'Unknown')}")
                print(f"Brand: {product.get('brand', 'Unknown')}")
                print(f"Quantity: {product.get('quantity', 'Unknown')}")
                print(f"Categories: {product.get('categories', 'Unknown')}")
                print(f"Source: {product.get('source', 'unknown')}")
        else:
            code_type = "ISBN" if is_isbn(single_lookup) else "Product"
            print(f"{code_type} not found: {single_lookup}")
        sys.exit(0)

    if not image_paths:
        print("Error: No image files specified", file=sys.stderr)
        sys.exit(1)

    all_results = []
    # easyocr forbids mixing Cyrillic with non-English Latin scripts; Bulgarian
    # labels need bg+en. (The plain --ocr default stays as-is for Latin/book OCR.)
    ocr_langs = ["bg", "en"] if bb_mode else None
    # Orientation: extract_text_ocr_oriented honours the EXIF tag first, then
    # auto-rotates (90/270/180) and retries when a photo reads as garbage —
    # phone cameras often save labels/receipts physically rotated with no EXIF
    # orientation, which otherwise loses the best-before date entirely.

    n_images = len(image_paths)
    for idx, image_path in enumerate(image_paths, 1):
        # Per-photo progress to stderr — OCR is several seconds per photo, so
        # without this the script looks hung and invites busy-wait polling.
        print(f"[{idx}/{n_images}] scanning {image_path.name} ...", file=sys.stderr, flush=True)
        if not image_path.exists():
            print(f"Warning: {image_path} not found", file=sys.stderr)
            continue

        barcodes = []
        if not ocr_only:
            barcodes = extract_barcodes(image_path, corroborate=not ns.no_corroborate)
            # Resolve conflicting reads before anything downstream trusts them.
            # The resolver is a tie-breaker of last resort, so it is only wired
            # up when lookups are enabled at all.
            resolver = None
            if do_lookup and HAS_REQUESTS:
                resolver = lambda code: lookup_code(code, cache, use_cache)[0]  # noqa: E731
            barcodes = resolve_candidates(barcodes, resolver=resolver)

        image_results: list[dict] = []
        ocr_results: list[dict] | None = None

        if not barcodes and enable_ocr:
            if not HAS_OCR:
                print("Warning: OCR requested but easyocr not installed", file=sys.stderr)
                print("Run: pip install easyocr", file=sys.stderr)
            else:
                ocr_results = extract_text_ocr_oriented(image_path, languages=ocr_langs)
                if ocr_results:
                    title = extract_title_from_ocr(ocr_results)
                    all_text = " | ".join(r["text"] for r in ocr_results[:5])
                    image_results.append(
                        {
                            "file": str(image_path),
                            "type": "OCR",
                            "data": title or all_text[:100],
                            "product": None,
                            "ocr_results": ocr_results,
                            "ocr_title": title,
                        }
                    )
        elif barcodes:
            for barcode in barcodes:
                result = {
                    "file": str(image_path),
                    "type": barcode["type"],
                    "data": barcode["data"],
                    "product": None,
                    "status": barcode.get("status", "ok"),
                    "corroboration": barcode.get("corroboration"),
                    "variants": barcode.get("variants"),
                }
                for key in ("status_reason", "alternatives", "discarded"):
                    if barcode.get(key):
                        result[key] = barcode[key]

                # Look up EANs (always via tingbok, no local caching). Losing
                # reads are kept for --json but not looked up or reported.
                if do_lookup and result["status"] == "ok" and is_ean(barcode["type"], barcode["data"]):
                    ean = barcode["data"]
                    product, was_cached = lookup_ean(ean, cache, use_cache)
                    result["product"] = product

                    # Only cache ISBNs locally; EANs go through tingbok
                    if not was_cached and use_cache and is_isbn(ean):
                        cache[ean] = product
                        cache_modified = True

                image_results.append(result)

        if not barcodes and not ocr_only and not ns.no_scan_undecoded and looks_like_undecoded_barcode(image_path):
            # Don't let a photo whose barcode is torn or blurred pass as a photo
            # that simply had no barcode.
            image_results.append(
                {
                    "file": str(image_path),
                    "type": "NO_DECODE",
                    "data": "",
                    "product": None,
                    "status": "needs_review",
                    "status_reason": "barcode-like pattern present, but nothing decoded",
                }
            )

        # Best-before pass: the date is usually on the SAME photo as the barcode,
        # so OCR runs here even for barcode images (where the OCR fallback above
        # didn't). Attaches best_before + candidates to every result for the image.
        if bb_mode and image_results and extract_best_before is not None:
            if not HAS_OCR:
                print("Warning: --best-before needs easyocr (pip install easyocr)", file=sys.stderr)
            else:
                if ocr_results is None:
                    ocr_results = extract_text_ocr_oriented(image_path, languages=ocr_langs)
                bb = extract_best_before(ocr_results or [])
                for r in image_results:
                    r["best_before"] = bb["best"]
                    r["best_before_candidates"] = bb["candidates"]

        all_results.extend(image_results)

    # Save cache if modified
    if cache_modified:
        save_cache(cache, CACHE_FILE)

    out_stream = open(ns.out, "w", encoding="utf-8") if ns.out else sys.stdout
    try:
        if output_json:
            print(json.dumps(all_results, indent=2), file=out_stream)
        else:
            # Human-readable output
            seen_eans = set()

            for result in all_results:
                data = result["data"]

                # Losing reads of a conflict are reported under the winner (or
                # under the needs-review block), never as an item of their own.
                if result.get("status") == "rejected":
                    continue

                if result["type"] == "NO_DECODE" or result.get("status") == "needs_review":
                    print(format_flagged(result), file=out_stream)
                    print(f"    # Found in: {result['file']}", file=out_stream)
                    print(file=out_stream)
                    continue

                # Handle OCR results differently
                if result["type"] == "OCR":
                    print("* tag:TODO (OCR detected text)", file=out_stream)
                    if result.get("ocr_title"):
                        print(f"    # Possible title: {result['ocr_title']}", file=out_stream)
                    else:
                        print(f"    # Text detected: {data[:80]}...", file=out_stream)
                    print(f"    # Found in: {result['file']}", file=out_stream)
                    print(file=out_stream)
                    continue

                if data in seen_eans:
                    continue
                seen_eans.add(data)

                barcode = {"type": result["type"], "data": data, "discarded": result.get("discarded")}
                print(format_for_inventory(barcode, result.get("product")), file=out_stream)
                print(f"    # Found in: {result['file']}", file=out_stream)
                print(file=out_stream)
    finally:
        if ns.out:
            out_stream.close()


if __name__ == "__main__":
    main()
