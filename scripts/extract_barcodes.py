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
    -h, --help      Show this help message

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
    except ImportError:
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
    # Same scripts/ dir; available when run as a script or imported with scripts on path.
    from bb_dates import extract_best_before
except ImportError:  # pragma: no cover
    extract_best_before = None


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


def extract_barcodes(image_path: Path) -> list[dict]:
    """
    Extract all barcodes and QR codes from an image.

    Returns list of dicts with: type, data, polygon
    """
    if not HAS_BARCODE_DEPS:
        raise RuntimeError("Barcode scanning requires pyzbar and pillow (pip install pyzbar pillow)")
    try:
        image = Image.open(image_path)
    except Exception as e:
        print(f"Error reading {image_path}: {e}", file=sys.stderr)
        return []

    # Decode all barcode types
    decoded = decode(image)

    results = []
    for barcode in decoded:
        results.append(
            {
                "type": barcode.type,  # EAN13, EAN8, UPCA, QRCODE, CODE128, etc.
                "data": barcode.data.decode("utf-8"),
                "polygon": [(p.x, p.y) for p in barcode.polygon] if barcode.polygon else None,
            }
        )

    return results


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
        # rotation_info crashes on some images).
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


def validate_ean_checksum(ean: str) -> bool:
    """Validate EAN/UPC check digit."""
    if not ean.isdigit():
        return False
    if len(ean) not in (8, 12, 13):
        return False

    # EAN-13/UPC-A checksum algorithm
    digits = [int(d) for d in ean]
    if len(ean) == 13:
        # EAN-13: odd positions * 1, even positions * 3
        total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        return check == digits[-1]
    elif len(ean) == 12:
        # UPC-A: odd positions * 3, even positions * 1
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        return check == digits[-1]
    elif len(ean) == 8:
        # EAN-8: same as EAN-13
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
        check = (10 - (total % 10)) % 10
        return check == digits[-1]
    return False


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

    # Check for EAN/UPC
    if barcode_type in ("EAN13", "EAN8", "UPCA", "UPCE"):
        if not validate_ean_checksum(data):
            print(f"Warning: Invalid checksum for {data}", file=sys.stderr)
            return False, ""
        return True, "ean"

    # Some barcodes encode EANs as other types
    if barcode_type == "CODE128" and data.isdigit() and len(data) in (8, 12, 13):
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
            return f"* EAN:{code} {desc}"
    else:
        # Check if it's an ISBN
        if is_isbn(code):
            return f"* tag:book ISBN:{normalize_isbn(code)} (unknown book)"
        return f"* EAN:{code} (unknown product, type: {barcode_type})"


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
    # Orientation is handled via the EXIF tag (extract_text_ocr); shoot labels
    # roughly upright. No brute-force rotation by default.
    ocr_rot = None

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
            barcodes = extract_barcodes(image_path)

        image_results: list[dict] = []
        ocr_results: list[dict] | None = None

        if not barcodes and enable_ocr:
            if not HAS_OCR:
                print("Warning: OCR requested but easyocr not installed", file=sys.stderr)
                print("Run: pip install easyocr", file=sys.stderr)
            else:
                ocr_results = extract_text_ocr(image_path, languages=ocr_langs, rotation_info=ocr_rot)
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
                }

                # Look up EANs (always via tingbok, no local caching)
                if do_lookup and is_ean(barcode["type"], barcode["data"]):
                    ean = barcode["data"]
                    product, was_cached = lookup_ean(ean, cache, use_cache)
                    result["product"] = product

                    # Only cache ISBNs locally; EANs go through tingbok
                    if not was_cached and use_cache and is_isbn(ean):
                        cache[ean] = product
                        cache_modified = True

                image_results.append(result)

        # Best-before pass: the date is usually on the SAME photo as the barcode,
        # so OCR runs here even for barcode images (where the OCR fallback above
        # didn't). Attaches best_before + candidates to every result for the image.
        if bb_mode and image_results and extract_best_before is not None:
            if not HAS_OCR:
                print("Warning: --best-before needs easyocr (pip install easyocr)", file=sys.stderr)
            else:
                if ocr_results is None:
                    ocr_results = extract_text_ocr(image_path, languages=ocr_langs, rotation_info=ocr_rot)
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

                barcode = {"type": result["type"], "data": data}
                print(format_for_inventory(barcode, result.get("product")), file=out_stream)
                print(f"    # Found in: {result['file']}", file=out_stream)
                print(file=out_stream)
    finally:
        if ns.out:
            out_stream.close()


if __name__ == "__main__":
    main()
