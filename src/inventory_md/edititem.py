"""Edit fields on an existing item line in ``inventory.md``.

The third write path, alongside :mod:`inventory_md.additem` (append) and
:mod:`inventory_md.moveitem` (relocate).  ``add`` is append-only and ``move``
only changes an item's container, so correcting a field on a line that is
already in the file — a mistyped EAN, a best-before that turned up on a label
photo after the import, an estimate that was recorded as a hard date — used to
mean hand-editing the markdown, the last remaining reason to do so.

``edit_item`` rewrites a single unambiguous ``ID:`` bullet in place:

* fields already on the line are substituted where they stand, so the line's
  own field order and spacing survive
* new fields are inserted at their canonical position (the order
  :func:`additem.format_item_line` writes)
* passing an empty value removes a field
* indented sub-bullets, and every other line in the file, are untouched
* the same QA as ``add`` is folded into the write: category resolution, the
  food-without-``bb:`` check, and a refusal to touch an ID that matches more
  than one bullet
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import additem as _additem
from . import moveitem as _moveitem
from . import parser as _parser

# Canonical field order, mirroring additem.format_item_line().
_FIELD_ORDER = ("category", "id", "tag", "ean", "isbn", "bb", "qty", "mass", "volume", "price", "value")
_CANONICAL_SPELLING = {
    "category": "category",
    "id": "ID",
    "tag": "tag",
    "ean": "EAN",
    "isbn": "ISBN",
    "bb": "bb",
    "qty": "qty",
    "mass": "mass",
    "volume": "volume",
    "price": "price",
    "value": "value",
}
_REPEATABLE = frozenset({"category", "tag"})

_BULLET_RE = re.compile(r"^(\s*[*-]\s+)(.*)$")
# One whitespace-delimited token that is a metadata field, e.g. "bb:2026-07" or
# "(qty:2)" — the same shape parser.extract_metadata() recognises.
_FIELD_TOKEN_RE = re.compile(r"\(?(\w+):([^)\s]+)\)?")


@dataclass
class EditResult:
    """Outcome of an :func:`edit_item` call.

    ``errors`` being non-empty means nothing was written.  ``before``/``after``
    hold the item line as it was and as it would become.
    """

    item_id: str | None = None
    before: str | None = None
    after: str | None = None
    container: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: bool = False


@dataclass
class _Token:
    start: int
    end: int
    text: str
    key: str | None  # lowercase field key, or None for free-text (name) tokens


def _split_bullet(line: str) -> tuple[str, str]:
    """Split ``line`` into its bullet prefix (indent + marker) and its body."""
    m = _BULLET_RE.match(line)
    if not m:
        return "", line
    return m.group(1), m.group(2)


def _tokenize(body: str) -> list[_Token]:
    """Classify each whitespace-delimited token of ``body`` as field or free text.

    Follows :func:`parser.extract_metadata`: only known metadata keys count, and
    only ``category``/``tag`` repeat — a later ``ID:``/``EAN:``/… token is part of
    the description (a device id quoted in a name) and stays free text.
    """
    tokens: list[_Token] = []
    seen: set[str] = set()
    for m in re.finditer(r"\S+", body):
        text = m.group()
        fm = _FIELD_TOKEN_RE.fullmatch(text)
        key = fm.group(1).lower() if fm else None
        if key is not None and (key not in _parser._KNOWN_METADATA_KEYS or (key not in _REPEATABLE and key in seen)):
            key = None
        if key is not None and key not in _REPEATABLE:
            seen.add(key)
        tokens.append(_Token(m.start(), m.end(), text, key))
    return tokens


def field_value(line: str, key: str) -> str | None:
    """The raw value of field ``key`` on ``line``, or ``None`` if it has none.

    The value is returned verbatim, so ``bb`` keeps any ``:EST`` suffix.
    """
    key = key.lower()
    _prefix, body = _split_bullet(line)
    for token in _tokenize(body):
        if token.key == key:
            fm = _FIELD_TOKEN_RE.fullmatch(token.text)
            if fm:
                return fm.group(2)
    return None


def _insert_at(tokens: list[_Token], key: str, body_len: int) -> int:
    """Offset in the body where a new ``key`` field belongs.

    Right after the last field that precedes ``key`` in the canonical order; at
    the very start of the body when no such field is present.
    """
    rank = _FIELD_ORDER.index(key)
    pos = None
    for token in tokens:
        if token.key is None or token.key not in _FIELD_ORDER:
            continue
        if _FIELD_ORDER.index(token.key) < rank:
            pos = token.end
    if pos is not None:
        return pos
    return tokens[0].start if tokens else body_len


def rewrite_item_line(
    line: str,
    changes: dict[str, str | None],
    *,
    tags: list[str] | None = None,
    name: str | None = None,
) -> str:
    """Return ``line`` with the requested field changes applied.

    ``changes`` maps a lowercase field key to its new value, or to ``None`` to
    remove the field.  ``tags`` (when not ``None``) replaces the line's whole set
    of ``tag:`` fields; ``name`` (when not ``None``) replaces its free text.
    Untouched parts of the line — including their spacing — are preserved
    verbatim.
    """
    prefix, body = _split_bullet(line)
    tokens = _tokenize(body)
    # (start, end, replacement); start == end inserts.
    edits: list[tuple[int, int, str]] = []

    def _delete(token: _Token) -> tuple[int, int, str]:
        # Swallow the whitespace in front of the token so no double space is left.
        start = token.start
        while start > 0 and body[start - 1].isspace():
            start -= 1
        if start == 0:  # first token: eat the whitespace behind it instead
            end = token.end
            while end < len(body) and body[end].isspace():
                end += 1
            return (token.start, end, "")
        return (start, token.end, "")

    for key, value in changes.items():
        existing = [t for t in tokens if t.key == key]
        if existing:
            token = existing[0]
            if value is None:
                edits.append(_delete(token))
            else:
                edits.append((token.start, token.end, f"{_CANONICAL_SPELLING[key]}:{value}"))
        elif value is not None:
            at = _insert_at(tokens, key, len(body))
            text = f"{_CANONICAL_SPELLING[key]}:{value}"
            edits.append((at, at, f" {text}" if at > 0 else f"{text} "))

    if tags is not None:
        for token in [t for t in tokens if t.key == "tag"]:
            edits.append(_delete(token))
        if tags:
            at = _insert_at(tokens, "tag", len(body))
            text = " ".join(f"tag:{t}" for t in tags)
            edits.append((at, at, f" {text}" if at > 0 else f"{text} "))

    if name is not None:
        for token in [t for t in tokens if t.key is None]:
            edits.append(_delete(token))
        if name.strip():
            edits.append((len(body), len(body), f" {name.strip()}"))

    # Apply right to left so earlier offsets stay valid.  At equal starts the
    # wider span (a deletion) goes first, then the insertion fills its place.
    for start, end, text in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        body = body[:start] + text + body[end:]

    return prefix + body.strip()


def edit_item(
    md_path: Path,
    *,
    item_id: str,
    category: str | None = None,
    ean: str | None = None,
    isbn: str | None = None,
    bb: str | date | None = None,
    bb_est: bool | None = None,
    qty: str | None = None,
    mass: str | None = None,
    volume: str | None = None,
    price: str | None = None,
    value: str | None = None,
    tags: list[str] | None = None,
    name: str | None = None,
    check_bb: bool = True,
    strict: bool = False,
    lang: str | None = None,
    dry_run: bool = False,
    tingbok_url: str | None = None,
) -> EditResult:
    """Change fields on the existing item ``item_id`` in ``md_path``.

    Every field argument is optional: ``None`` leaves it alone, a value sets it,
    and an empty string removes it (``category`` cannot be removed).  ``bb_est``
    on its own flips the ``:EST`` marker on the date already on the line, which
    is how an estimate wrongly recorded as an assertion gets repaired.

    On any error nothing is written and :class:`EditResult` carries the reasons.
    With ``dry_run`` the new line is built and reported but the file is left
    untouched (``result.written`` stays ``False``).
    """
    result = EditResult(item_id=item_id)

    if not md_path.exists():
        result.errors.append(f"{md_path} not found")
        return result

    text = md_path.read_text(encoding="utf-8")
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()

    blocks = _moveitem.find_item_blocks(lines, item_id)
    if not blocks:
        result.errors.append(f"item ID:{item_id} not found as a bullet in {md_path.name}")
        return result
    if len(blocks) > 1:
        where = ", ".join(f"line {start + 1}" for start, _end in blocks)
        result.errors.append(
            f"item ID:{item_id} matches more than once in {md_path.name} ({where}) — "
            "IDs must be unique; fix the duplicate before editing"
        )
        return result

    index = blocks[0][0]
    line = lines[index]
    result.before = line
    result.container = _moveitem.container_of_line(lines, index)

    changes: dict[str, str | None] = {}
    for key, given in (
        ("ean", ean),
        ("isbn", isbn),
        ("qty", qty),
        ("mass", mass),
        ("volume", volume),
        ("price", price),
        ("value", value),
    ):
        if given is not None:
            changes[key] = given or None

    if category is not None:
        if not category.strip():
            result.errors.append("category cannot be removed; every item line needs one")
            return result
        changes["category"] = ",".join("/".join(p.lower() for p in c.split("/")) for c in category.split(","))

    # Best-before, in both its spellings.  A date given on the command line may
    # carry its own ``:EST``; bb_est alone re-flags the date already on the line.
    if bb is not None and str(bb).strip():
        try:
            bb_value, est = _additem.resolve_bb_est(bb, bb_est)
        except ValueError as exc:
            result.errors.append(str(exc))
            return result
        if bb_value is None or not _additem.validate_bb_format(bb_value):
            result.errors.append(f"invalid best-before format: {bb_value!r} (use YYYY, YYYY-MM or YYYY-MM-DD)")
            return result
        changes["bb"] = f"{bb_value}:EST" if est else bb_value
    elif bb is not None:  # empty string → remove
        if bb_est:
            result.errors.append("cannot mark a removed best-before as estimated")
            return result
        changes["bb"] = None
    elif bb_est is not None:
        current = field_value(line, "bb")
        if current is None:
            result.errors.append(f"item ID:{item_id} has no best-before to mark as estimated; pass a date with --bb")
            return result
        bb_value = current[: -len(":EST")] if current.endswith(":EST") else current
        changes["bb"] = f"{bb_value}:EST" if bb_est else bb_value

    if not changes and tags is None and name is None:
        result.errors.append("nothing to change — pass at least one field to edit")
        return result

    new_line = rewrite_item_line(line, changes, tags=tags, name=name)
    result.after = new_line

    # QA on the result, reading it back the way the parser will.
    parsed = _parser.extract_metadata(_split_bullet(new_line)[1])
    metadata = parsed["metadata"]
    if metadata.get("id") != item_id:
        result.errors.append(f"edit would change or lose the item ID (got {metadata.get('id')!r})")
        return result

    resolved_lang = lang or "en"
    categories = metadata.get("categories") or []
    if categories:
        unresolved, is_food = _additem.category_qa(
            md_path, ",".join(categories), lang=resolved_lang, tingbok_url=tingbok_url
        )
        if unresolved:
            msg = f"category does not resolve in local vocabulary: {', '.join(unresolved)}"
            (result.errors if strict else result.warnings).append(msg)
        if is_food and not metadata.get("bb") and check_bb:
            result.errors.append(
                f"food item '{','.join(categories)}' would be left without a best-before (bb:); "
                "supply --bb YYYY-MM (add --est to estimate) or pass --no-bb-check"
            )

    if result.errors:
        return result

    if new_line == line:
        result.warnings.append("line unchanged — nothing written")
        return result

    if dry_run:
        return result

    lines[index] = new_line
    new_text = "\n".join(lines)
    if had_trailing_newline:
        new_text += "\n"
    md_path.write_text(new_text, encoding="utf-8")
    result.written = True
    return result
