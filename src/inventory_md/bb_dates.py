#!/usr/bin/env python3
"""Best-before date extraction from OCR text.

Product photos usually carry the best-before date next to (or on the same image
as) the barcode. This turns OCR text into normalised ISO date candidates and
picks the most likely best-before, preferring dates next to a best-before
keyword. Pure and dependency-free so it's easy to test; the OCR itself lives in
extract_barcodes.py.

Handled date formats (European day-first):
    YYYY-MM-DD · DD.MM.YYYY · DD-MM-YYYY · DD MM YYYY · DD.MM.YY · MM.YYYY
"""

from __future__ import annotations

import re
from typing import Any

# Best-before markers (lowercased/casefolded). Bulgarian, English, German.
_BB_KEYWORDS = (
    "най-добър",
    "годен до",
    "срок на годност",
    "best before",
    "best-before",
    "best by",
    "use by",
    "bbe",
    "exp",
    "expiry",
    "expiration",
    "mindestens haltbar",
    "mhd",
)

# Date patterns, most specific first; each yields (groups) -> ISO via a builder.
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_FULL = re.compile(r"\b(\d{1,2})[.\-/ ](\d{1,2})[.\-/ ](\d{4})\b")  # DD MM YYYY
_SHORT = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b")  # DD MM YY
_MONTH_YEAR = re.compile(r"\b(\d{1,2})[.\-/](\d{4})\b")  # MM YYYY


def _valid_ymd(y: int, m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2099


def _iso(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def _find_with_spans(text: str) -> list[tuple[int, str]]:
    """Return (start_offset, iso) for every date found, in text order."""
    found: list[tuple[int, str]] = []
    claimed: list[tuple[int, int]] = []  # spans already consumed, to avoid double-matching

    def overlaps(a: int, b: int) -> bool:
        return any(a < e and s < b for s, e in claimed)

    for m in _ISO.finditer(text):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
        if _valid_ymd(y, mo, d):
            found.append((m.start(), _iso(y, mo, d)))
            claimed.append((m.start(), m.end()))
    for m in _FULL.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        if d <= 12 < mo:  # only the second field is a valid day -> it's MM DD
            d, mo = mo, d
        if _valid_ymd(y, mo, d):
            found.append((m.start(), _iso(y, mo, d)))
            claimed.append((m.start(), m.end()))
    for m in _SHORT.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        d, mo, yy = int(m[1]), int(m[2]), int(m[3])
        if d <= 12 < mo:
            d, mo = mo, d
        y = 2000 + yy
        if _valid_ymd(y, mo, d):
            found.append((m.start(), _iso(y, mo, d)))
            claimed.append((m.start(), m.end()))
    for m in _MONTH_YEAR.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        mo, y = int(m[1]), int(m[2])
        if 1 <= mo <= 12 and 2000 <= y <= 2099:
            found.append((m.start(), f"{y:04d}-{mo:02d}"))
            claimed.append((m.start(), m.end()))

    found.sort(key=lambda t: t[0])
    return found


def find_dates(text: str) -> list[str]:
    """All ISO date candidates in *text*, in order of appearance, deduplicated."""
    out: list[str] = []
    for _, iso in _find_with_spans(text):
        if iso not in out:
            out.append(iso)
    return out


def _as_text(blocks: str | list[dict[str, Any]] | list[str]) -> str:
    """Join OCR blocks (dicts with 'text', or strings) into one searchable string."""
    if isinstance(blocks, str):
        return blocks
    # Joined with a space (not a separator) so a date split across OCR blocks
    # — e.g. "10" + "02 2028" — still reads as one "10 02 2028".
    parts = [(b.get("text", "") if isinstance(b, dict) else str(b)) for b in blocks]
    return " ".join(parts)


def extract_best_before(blocks: str | list[dict[str, Any]] | list[str], window: int = 30) -> dict[str, Any]:
    """Pick the most likely best-before date from OCR text.

    A date is flagged ``near_keyword`` when a best-before marker appears within
    *window* characters before it. The chosen ``best`` is the latest
    keyword-adjacent date, else the latest date overall (best-before is usually
    the furthest-out date on a pack; production/lot dates are earlier). Returns
    ``{"best": iso|None, "candidates": [{date, near_keyword}]}``.
    """
    text = _as_text(blocks)
    low = text.casefold()
    spans = _find_with_spans(text)

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for start, iso in spans:
        if iso in seen:
            continue
        seen.add(iso)
        before = low[max(0, start - window) : start]
        near = any(kw in before for kw in _BB_KEYWORDS)
        candidates.append({"date": iso, "near_keyword": near})

    if not candidates:
        return {"best": None, "candidates": []}

    keyworded = [c["date"] for c in candidates if c["near_keyword"]]
    best = max(keyworded) if keyworded else max(c["date"] for c in candidates)
    return {"best": best, "candidates": candidates}
