"""Move an existing item line from one container to another in ``inventory.md``.

This is the relocation counterpart to :mod:`inventory_md.additem`.  Reorganising
physical storage (repacking boxes, moving a shelf's contents into a crate) is a
recurring chore; doing it by hand-editing the markdown is error-prone — it is
easy to duplicate a line instead of moving it, or to orphan an item's indented
sub-bullets.  ``move_item`` locates the bullet by its ``ID:`` token, carries any
deeper-indented continuation lines with it, and splices the block into the target
container using the same insertion rule as ``add`` (:func:`additem.insertion_index`).

Only items that exist as a single ``ID:``-tagged bullet can be moved; free-text
list entries without an ID are out of scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import additem as _additem
from . import parser as _parser

_BULLET_PREFIXES = ("* ", "- ")
_HEADING_ID_RE = re.compile(r"^(#{1,6})\s+.*?ID:(\S+)")


@dataclass
class MoveResult:
    """Outcome of a :func:`move_item` call.

    ``errors`` being non-empty means nothing was written.
    """

    item_id: str | None = None
    item_line: str | None = None
    from_container: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: bool = False


def _is_bullet(line: str) -> bool:
    return line.lstrip().startswith(_BULLET_PREFIXES)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def find_item_blocks(lines: list[str], item_id: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` line indices for every item bullet ``ID:item_id``.

    Each block spans the bullet line plus any immediately following lines that are
    indented deeper than it (its sub-bullets / continuation lines).  The match is
    exact: ``ID:item_id`` must be a whole token (``rice`` does not match
    ``rice-1``) and the line must be a list bullet, so container headings carrying
    the same ID token are ignored.  IDs are meant to be unique, so more than one
    hit means the inventory is inconsistent — callers that rewrite a line
    (``edit``) refuse rather than guess.
    """
    token = re.compile(r"(?:^|\s)ID:" + re.escape(item_id) + r"(?=\s|$)")
    blocks: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        if not _is_bullet(line) or not token.search(line):
            continue
        indent = _indent(line)
        end = i + 1
        while end < len(lines):
            nxt = lines[end]
            if nxt.strip() and _is_bullet(nxt) and _indent(nxt) > indent:
                end += 1
            else:
                break
        blocks.append((i, end))
    return blocks


def find_item_block(lines: list[str], item_id: str) -> tuple[int, int] | None:
    """The first block of :func:`find_item_blocks`, or ``None`` if there is none."""
    blocks = find_item_blocks(lines, item_id)
    return blocks[0] if blocks else None


def container_of_line(lines: list[str], line_index: int) -> str | None:
    """The ID of the nearest enclosing container heading above ``line_index``."""
    for i in range(line_index - 1, -1, -1):
        m = _HEADING_ID_RE.match(lines[i])
        if m:
            return m.group(2)
    return None


def move_item(
    md_path: Path,
    *,
    item_id: str,
    container_id: str,
    dry_run: bool = False,
) -> MoveResult:
    """Move the item ``item_id`` into the container ``container_id``.

    On any error nothing is written and :class:`MoveResult` carries the reason.
    With ``dry_run`` the move is validated and the moved line reported, but the
    file is left untouched (``result.written`` stays ``False``).
    """
    result = MoveResult(item_id=item_id)

    if not md_path.exists():
        result.errors.append(f"{md_path} not found")
        return result

    data = _parser.parse_inventory(md_path)

    if not any(c.get("id") == container_id for c in data.get("containers", [])):
        result.errors.append(f"Container ID:{container_id} not found in {md_path.name}")
        return result

    text = md_path.read_text(encoding="utf-8")
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()

    block = find_item_block(lines, item_id)
    if block is None:
        result.errors.append(f"item ID:{item_id} not found as a bullet in {md_path.name}")
        return result

    start, end = block
    moved = lines[start:end]
    result.item_line = moved[0]
    result.from_container = container_of_line(lines, start)

    if dry_run:
        return result

    remaining = lines[:start] + lines[end:]
    try:
        insert_at = _additem.insertion_index(remaining, container_id)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    new_lines = remaining[:insert_at] + moved + remaining[insert_at:]
    new_text = "\n".join(new_lines)
    if had_trailing_newline:
        new_text += "\n"
    md_path.write_text(new_text, encoding="utf-8")
    result.written = True
    return result
