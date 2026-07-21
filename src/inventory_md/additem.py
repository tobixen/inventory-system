"""Add an item line to a container in ``inventory.md``.

This is the write path the process-shopping skill calls in Stage 3 instead of
hand-editing the markdown.  It folds the relevant quality checks into the write
step:

* duplicate ``ID:`` detection (across all containers and items)
* food-without-best-before check (hard error unless disabled)
* category resolution against the local vocabulary (warning, or error in
  ``strict`` mode), with a tingbok fallback for categories new to this
  inventory when ``tingbok_url`` is given

The actual field parsing, container location, and food classification are reused
from :mod:`inventory_md.parser`, :mod:`inventory_md.queries` and
:mod:`inventory_md.vocabulary` rather than reimplemented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import parser as _parser
from . import queries as _queries
from . import vocabulary as _vocabulary

# YYYY, YYYY-MM, YYYY-MM-DD or YYYY-MM-DDTHH:MM
_BB_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2})?)?)?$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class AddResult:
    """Outcome of an :func:`add_item` call.

    ``errors`` being non-empty means nothing was written.  ``warnings`` are
    advisory; the line was still written when only warnings are present.
    """

    item_id: str | None = None
    item_line: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: bool = False


def validate_bb_format(bb: str) -> bool:
    """True if ``bb`` is a recognised best-before format."""
    return bool(_BB_RE.match(bb))


def _coerce_bb(bb: str | date | None) -> str | None:
    """Normalise a best-before value to its string form.

    Staging files are YAML, and YAML loads an unquoted ``bb: 2027-02-12`` as a
    ``datetime.date`` — accept those instead of crashing in the regex check.
    """
    if isinstance(bb, datetime):  # before date: datetime is a date subclass
        return bb.strftime("%Y-%m-%dT%H:%M")
    if isinstance(bb, date):
        return bb.isoformat()
    return bb


def resolve_bb_est(bb: str | date | None, bb_est: bool | None = None) -> tuple[str | None, bool]:
    """Reconcile the two spellings of "this best-before is an estimate".

    An estimate can be expressed inline as a ``:EST`` suffix on the date
    (``bb: 2026-09:EST``) or out of band as a separate boolean
    (``bb: 2026-09`` plus ``bb_est: true``).  Both must produce the same
    ``bb:DATE:EST`` line — recording a guess as a hard fact is the one outcome
    that must never happen silently.

    ``bb_est=None`` means *unspecified*: the suffix alone decides.  An explicit
    flag that contradicts the suffix (``2026-09:EST`` with ``bb_est=False``) is a
    :class:`ValueError`, never a silent pick.

    Returns ``(bb_without_suffix, is_estimated)``.
    """
    if bb_est is not None and not isinstance(bb_est, bool):
        raise ValueError(f"bb_est must be true or false, got {bb_est!r}")

    bb = _coerce_bb(bb)
    suffix_est = False
    if isinstance(bb, str) and bb.endswith(":EST"):
        bb = bb[: -len(":EST")]
        suffix_est = True

    if suffix_est and bb_est is False:
        raise ValueError(
            f"best-before {bb!r} carries a :EST suffix but bb_est is false — "
            "an estimate cannot also be an assertion; drop one of the two"
        )

    return bb, bool(bb_est) if bb_est is not None else suffix_est


def _drop_tingbok_resolvable(labels: list[str], lang: str, tingbok_url: str) -> list[str]:
    """Filter out category labels that resolve in tingbok's vocabulary.

    The local vocabulary only knows categories already used in this inventory,
    so the first use of a perfectly valid category would otherwise warn (or fail
    ``--strict``) on every add.  When tingbok is unreachable the local verdict
    stands.  Stubs tingbok returns for unknown labels don't count as resolved.
    """
    try:
        remote = _vocabulary.resolve_vocabulary_from_tingbok(labels, tingbok_url, lang)
    except Exception:
        return labels
    known = {cid: c for cid, c in remote.items() if c.source == "tingbok"}
    return [label for label in labels if _vocabulary.resolve_category(label, known, lang) is None]


def category_qa(
    md_path: Path,
    category: str,
    *,
    lang: str = "en",
    tingbok_url: str | None = None,
) -> tuple[list[str], bool]:
    """Category checks shared by the ``add`` and ``edit`` write paths.

    Returns ``(unresolved_labels, is_food)`` for a comma-separated ``category``
    string: the labels that resolve neither in the inventory's local vocabulary
    nor (when ``tingbok_url`` is given) in tingbok's, and whether the category
    denotes food — which is what makes a missing ``bb:`` an error.
    """
    concepts = _queries._load_food_vocabulary(md_path)
    labels = [c for c in category.split(",") if c]
    unresolved = [c for c in labels if _vocabulary.resolve_category(c, concepts, lang) is None]
    if unresolved and tingbok_url:
        unresolved = _drop_tingbok_resolvable(unresolved, lang, tingbok_url)
    return unresolved, _queries._is_food(labels, concepts, lang)


def slugify(text: str) -> str:
    """Lowercase, ASCII-ish, hyphen-separated slug; empty parts dropped."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug


def collect_existing_ids(data: dict[str, Any]) -> set[str]:
    """All ``ID:`` values currently in use (containers and items)."""
    ids: set[str] = set()
    for container in data.get("containers", []):
        if container.get("id"):
            ids.add(container["id"])
        for item in container.get("items", []):
            if item.get("id"):
                ids.add(item["id"])
    return ids


def generate_item_id(
    category: str,
    name: str | None,
    existing_ids: set[str],
    *,
    is_food: bool = False,
    today: date | None = None,
) -> str:
    """Derive a readable, unique item ID.

    Base slug comes from the leaf of the first category (e.g. ``carrots`` →
    ``carrots-2026-05-09``, per ADDING-ITEMS).  Food items get the purchase date
    appended.  A numeric suffix is added on collision.  ``name`` is accepted for
    callers that want to pass it but is currently unused for the base slug.
    """
    leaf = category.split(",")[0].split("/")[-1]
    base = slugify(leaf) or "item"
    if is_food:
        day = (today or date.today()).isoformat()
        base = f"{base}-{day}"

    candidate = base
    n = 2
    while candidate in existing_ids:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def format_item_line(
    category: str,
    item_id: str,
    *,
    ean: str | None = None,
    isbn: str | None = None,
    bb: str | None = None,
    bb_est: bool = False,
    qty: Any | None = None,
    mass: str | None = None,
    volume: str | None = None,
    price: str | None = None,
    value: str | None = None,
    tags: list[str] | None = None,
    name: str | None = None,
) -> str:
    """Build a canonical item bullet line.

    Field order follows the process-shopping Stage-3 convention:
    ``category ID tag EAN ISBN bb qty mass volume price value NAME``, with the
    human-readable name last.  Category path components are lowercased.
    """
    cats = ",".join("/".join(p.lower() for p in c.split("/")) for c in category.split(","))
    parts = [f"category:{cats}", f"ID:{item_id}"]
    for tag in tags or []:
        parts.append(f"tag:{tag}")
    if ean:
        parts.append(f"EAN:{ean}")
    if isbn:
        parts.append(f"ISBN:{isbn}")
    if bb:
        parts.append(f"bb:{bb}:EST" if bb_est else f"bb:{bb}")
    if qty is not None:
        parts.append(f"qty:{qty}")
    if mass:
        parts.append(f"mass:{mass}")
    if volume:
        parts.append(f"volume:{volume}")
    if price:
        parts.append(f"price:{price}")
    if value:
        parts.append(f"value:{value}")
    if name:
        parts.append(name.strip())
    return "* " + " ".join(parts)


def insertion_index(lines: list[str], container_id: str) -> int:
    """Return the line index at which a new bullet should be spliced.

    The slot is after the last existing list item in the container's section,
    or immediately after the heading (and its blank line) if the container has
    no items yet.  Raises :class:`ValueError` if the container is not found.
    """
    located = _parser.find_container_section(lines, container_id)
    if located is None:
        raise ValueError(f"Container ID:{container_id} not found")
    start, end, _level = located

    last_bullet = None
    for i in range(start + 1, end):
        stripped = lines[i].lstrip()
        if stripped.startswith(("* ", "- ")):
            last_bullet = i

    if last_bullet is not None:
        return last_bullet + 1
    # No items yet: insert right after the heading, skipping one blank line
    # so the bullet doesn't glue onto the heading.
    insert_at = start + 1
    if insert_at < end and not lines[insert_at].strip():
        insert_at += 1
    return insert_at


def insert_item_line(lines: list[str], container_id: str, item_line: str) -> list[str]:
    """Return ``lines`` with ``item_line`` inserted into the named container.

    The line is placed after the last existing list item in the container's
    section, or immediately after the heading (and its blank line) if the
    container has no items yet.  Raises :class:`ValueError` if the container is
    not found.
    """
    insert_at = insertion_index(lines, container_id)
    return lines[:insert_at] + [item_line] + lines[insert_at:]


def add_item(
    md_path: Path,
    *,
    container_id: str,
    category: str,
    item_id: str | None = None,
    ean: str | None = None,
    isbn: str | None = None,
    bb: str | date | None = None,
    bb_est: bool | None = None,
    qty: Any | None = None,
    mass: str | None = None,
    volume: str | None = None,
    price: str | None = None,
    value: str | None = None,
    tags: list[str] | None = None,
    name: str | None = None,
    check_bb: bool = True,
    strict: bool = False,
    lang: str | None = None,
    today: date | None = None,
    dry_run: bool = False,
    tingbok_url: str | None = None,
) -> AddResult:
    """Validate and append an item line to ``md_path``.

    On any error nothing is written and :class:`AddResult` carries the reasons.
    With ``dry_run`` the line is validated and built but the file is left
    untouched (``result.written`` stays ``False``).
    """
    result = AddResult()

    if not md_path.exists():
        result.errors.append(f"{md_path} not found")
        return result

    data = _parser.parse_inventory(md_path)
    existing_ids = collect_existing_ids(data)

    # Container must exist.  Matching is case-insensitive, but the *stored*
    # spelling is what gets handed to the writer, so the section lookup later on
    # is an exact hit rather than a fuzzy one.
    want = container_id.casefold()
    matches = [c["id"] for c in data.get("containers", []) if c.get("id") and c["id"].casefold() == want]
    if not matches:
        result.errors.append(f"Container ID:{container_id} not found in {md_path.name}")
        return result
    container_id = matches[0]

    # Category resolution against the local vocabulary, with a tingbok fallback:
    # categories new to this inventory are fine if tingbok knows them.
    resolved_lang = lang or "en"
    unresolved, is_food = category_qa(md_path, category, lang=resolved_lang, tingbok_url=tingbok_url)
    if unresolved:
        msg = f"category does not resolve in local vocabulary: {', '.join(unresolved)}"
        (result.errors if strict else result.warnings).append(msg)

    # Best-before format and food check.  ``:EST`` may arrive as a suffix on the
    # date or as the separate ``bb_est`` flag; the two must not disagree.
    try:
        bb, est = resolve_bb_est(bb, bb_est)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result
    bb_est = est
    if bb is not None and not validate_bb_format(bb):
        result.errors.append(f"invalid best-before format: {bb!r} (use YYYY, YYYY-MM or YYYY-MM-DD)")

    if is_food and not bb and check_bb:
        result.errors.append(
            f"food item '{category}' has no best-before (bb:); supply bb:YYYY-MM "
            "(append :EST to estimate) or pass --no-bb-check"
        )

    # ID: validate or generate.
    if item_id is None:
        item_id = generate_item_id(category, name, existing_ids, is_food=is_food, today=today)
    elif item_id in existing_ids:
        result.errors.append(f"duplicate ID: '{item_id}' is already in use")

    result.item_id = item_id

    if result.errors:
        return result

    item_line = format_item_line(
        category,
        item_id,
        ean=ean,
        isbn=isbn,
        bb=bb,
        bb_est=bb_est,
        qty=qty,
        mass=mass,
        volume=volume,
        price=price,
        value=value,
        tags=tags,
        name=name,
    )
    result.item_line = item_line

    if dry_run:
        return result

    text = md_path.read_text(encoding="utf-8")
    newline = "\n"
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()
    new_lines = insert_item_line(lines, container_id, item_line)
    new_text = newline.join(new_lines)
    if had_trailing_newline:
        new_text += newline
    md_path.write_text(new_text, encoding="utf-8")
    result.written = True
    return result
