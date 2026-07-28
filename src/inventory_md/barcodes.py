"""Barcode-number helpers shared by the CLI and the photo extractor.

Nothing here touches images or the network — it is pure arithmetic and string
handling over EAN/UPC numbers.  It lives in the package (rather than in
``scripts/extract_barcodes.py``, where the checksum code originally sat) so
``inventory-md ean`` and ``check_quality`` can use the same rules without
importing the image-processing script.
"""

from __future__ import annotations

import re

# A shop-local article number is stored with a shop-name prefix so it cannot be
# mistaken for a real GTIN — see docs/ADDING-ITEMS.md.  The prefix must start
# with a letter; the number part is long enough not to match a stray suffix of
# a hyphenated ISBN.
_SHOP_PREFIXED = re.compile(r"^[a-z][a-z0-9_.]*-(\d{4,})$")


def validate_ean_checksum(ean: str) -> bool:
    """Validate an EAN-13 / EAN-8 / UPC-A check digit.

    Returns ``False`` for anything that is not 8, 12 or 13 digits.  Note that a
    passing checksum is *not* evidence of a correct read: a barcode misdecode
    recomputes the check digit over the corrupted digits (see
    :func:`is_parity_confusable`).
    """
    # ``isdigit()`` alone is True for superscripts and other Unicode numerics
    # that ``int()`` then rejects, so a barcode read as "²²²²²²²²" would raise
    # rather than simply fail validation.
    if not (ean.isascii() and ean.isdigit()):
        return False
    if len(ean) not in (8, 12, 13):
        return False

    digits = [int(d) for d in ean]
    if len(ean) == 13:
        # EAN-13: odd positions * 1, even positions * 3
        total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:-1]))
    else:
        # UPC-A and EAN-8: odd positions * 3, even positions * 1
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
    return (10 - (total % 10)) % 10 == digits[-1]


def is_parity_confusable(a: str, b: str) -> bool:
    """Return True if two codes look like the same barcode read two ways.

    EAN-13 encodes its left six digits in either L or G parity, and the
    *pattern* of those choices is what carries the leading (13th) digit — that
    digit has no bars of its own.  A couple of bar-width errors can therefore
    flip left-half digits into their opposite-parity twins and change the
    decoded leading digit, while the right half (single parity, self-contained)
    comes through byte-identical.  The checksum is then recomputed over the
    corrupted digits and passes.

    Observed specimen: ``5941132002140`` (real) and ``2931532002140``
    (phantom), from one photo of a Dr. Oetker vanilla sugar sachet.

    So: same length, identical right half, different left half — one of the two
    is a misdecode.  Two codes that fail this test are two different barcodes
    (a shelf photo with several products), not a conflict.
    """
    a, b = a.strip(), b.strip()
    if a == b or not a.isdigit() or not b.isdigit():
        return False
    if len(a) != len(b) or len(a) not in (8, 12, 13):
        return False
    half = len(a) // 2  # EAN-13/UPC-A → last 6, EAN-8 → last 4
    return a[-half:] == b[-half:]


# GS1 prefix ranges that a manufacturer's retail pack never carries: codes
# assigned by a member organisation for restricted (in-store) distribution, plus
# coupon and refund-receipt ranges.  Everything else — including 977 (ISSN),
# 978/979 (ISBN) and every country prefix — is a plausible thing to find printed
# on a product.
_RESTRICTED_GS1_PREFIXES = (
    (20, 29),  # restricted distribution, MO-defined (in-store codes)
    (40, 49),  # restricted distribution, MO-defined
    (50, 59),  # coupons
    (200, 299),  # restricted distribution, MO-defined
    (980, 999),  # refund receipts and coupons
)


def is_restricted_gs1_prefix(ean: str) -> bool:
    """Return True if a 13-digit code's GS1 prefix rules it out as a retail pack.

    Only meaningful for EAN-13 (``False`` for anything else, so a caller cannot
    use it as grounds to reject a shorter code).  It is also not grounds to
    reject a code on its own: a shop's in-store barcode is a legitimate
    restricted-prefix code.  It earns its keep inside a *conflict group*, where
    one candidate is a misdecode by definition and the prefix says which — for
    free and offline.  Observed: the phantom ``2931532002140`` (293) against the
    real ``5941132002140`` (594, Romania).
    """
    if len(ean) != 13 or not ean.isdigit():
        return False
    prefix = int(ean[:3])
    return any(low <= prefix <= high for low, high in _RESTRICTED_GS1_PREFIXES)


def _split_shop_prefix(value: str) -> tuple[str | None, str]:
    """Split ``lidl-40853712`` into ``("lidl", "40853712")``; else ``(None, value)``."""
    prefixed = _SHOP_PREFIXED.match(value)
    if not prefixed:
        return None, value
    return value[: prefixed.start(1) - 1], prefixed.group(1)


def _compact_digits(value: str) -> str | None:
    """Return the digits of a separator-written GTIN, or ``None`` if not one.

    ``5941-1320 02140`` → ``5941132002140``; ``lidl-40853712`` → ``None``,
    because stripping *that* hyphen would fuse a shop name onto a number.
    """
    stripped = re.sub(r"[\s\-]", "", value)
    if stripped and stripped.isascii() and stripped.isdigit():
        return stripped
    return None


def ean_matches(stored: str, query: str) -> bool:
    """Return True if a *stored* inventory barcode answers a lookup *query*.

    Barcodes get written down with separators (``5941-1320 02140``), and
    shop-local article numbers carry a shop prefix (``lidl-40853712``) so that
    two chains reusing the same number stay distinguishable — see
    docs/ADDING-ITEMS.md.  Matching therefore has a direction: a *bare* number
    read off a label may find a prefixed entry, but two differently-prefixed
    numbers must **not** find each other, which is exactly what stripping the
    prefix off both sides would do.

    An empty value on either side never matches.
    """
    s = (stored or "").strip().lower()
    q = (query or "").strip().lower()
    if not s or not q:
        return False
    if s == q:
        return True

    s_shop, s_number = _split_shop_prefix(s)
    q_shop, q_number = _split_shop_prefix(q)

    if s_shop is not None and q_shop is not None:
        # Both name a shop: the shop is part of the identity.
        return s_shop == q_shop and s_number == q_number

    s_digits = _compact_digits(s_number)
    q_digits = _compact_digits(q_number)
    if s_digits is None or q_digits is None:
        return False
    return s_digits == q_digits


# ---------------------------------------------------------------------------
# UPC-E
# ---------------------------------------------------------------------------
#
# A UPC-E check digit is computed over the *expanded* UPC-A, not over the eight
# characters as printed, so validating the raw payload with EAN-8 arithmetic
# rejects genuine reads.


def expand_upce(upce: str) -> str | None:
    """Expand an 8-digit UPC-E to its 12-digit UPC-A form, or ``None``.

    The last data digit selects where the suppressed zeroes go.  Returns
    ``None`` for anything that is not a well-formed UPC-E (wrong length,
    non-digits, or a number system other than 0 or 1).
    """
    if not (upce.isascii() and upce.isdigit()) or len(upce) != 8:
        return None
    system, body, check = upce[0], upce[1:7], upce[7]
    if system not in ("0", "1"):
        return None

    d1, d2, d3, d4, d5, d6 = body
    if d6 in ("0", "1", "2"):
        middle = f"{d1}{d2}{d6}0000{d3}{d4}{d5}"
    elif d6 == "3":
        middle = f"{d1}{d2}{d3}00000{d4}{d5}"
    elif d6 == "4":
        middle = f"{d1}{d2}{d3}{d4}00000{d5}"
    else:  # 5-9
        middle = f"{d1}{d2}{d3}{d4}{d5}0000{d6}"
    return f"{system}{middle}{check}"


def validate_upce_checksum(upce: str) -> bool:
    """Validate a UPC-E check digit by expanding to UPC-A first."""
    expanded = expand_upce(upce)
    return expanded is not None and validate_ean_checksum(expanded)
