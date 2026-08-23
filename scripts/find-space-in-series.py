#!/usr/bin/env python3
"""
Find Free IDs in a Container Series

Container IDs are typically a prefix plus a running number, and the same box
gets written down in several ways over time ("C-01", "C1", "c 007").  This
prints the numbers of a series that are *not* in use yet, so a newly packed
box can be given a free ID without reading through the whole inventory.

The IDs it prints are in the canonical spelling — uppercase prefix, dash,
two digits — regardless of how the existing ones happen to be written.

Usage:
    ./find-space-in-series.py C                     # all free numbers in C-01..C-99
    ./find-space-in-series.py C -n 1                # just the next free one
    ./find-space-in-series.py TC ~/inv/inventory.json --max 20

Options:
    --max N          Highest number in the series (default 99)
    --start N        Lowest number in the series (default 1; pass 0 for a
                     series that numbers from zero, as FM-0 does)
    -n, --count N    Print at most N free IDs (default: all)
    -h, --help       Show this help message

Exit codes:
    0 - at least one free ID found
    1 - the series is full
    2 - bad arguments, or inventory file missing or unreadable
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

# "C-01", "C 1", "C_007" and "c1" are all the same box; anything after the
# number ("C-01-shelf") is a different ID and not part of the series.
SEPARATORS = "-_ "

# Container numbers are conventionally written with two digits (C-01), even
# when the series is short.  A --max of 100 or more widens this, so that the
# IDs of one series still sort as text.
MIN_WIDTH = 2


def container_ids(inventory: dict) -> list[str]:
    """All container IDs in the inventory, skipping containers without a usable one."""
    if not isinstance(inventory, dict):
        raise ValueError("inventory is not a JSON object")
    return [c["id"] for c in inventory.get("containers", []) if isinstance(c.get("id"), str) and c["id"].strip()]


def used_numbers(ids: Iterable[str], prefix: str) -> dict[int, set[str]]:
    """Map each taken number of ``prefix``'s series to the ID spellings claiming it.

    The prefix matches case-insensitively, the separator is optional and
    leading zeros are ignored, so ``C1``, ``c-01`` and ``C 001`` all count as
    number 1 — zero padding *should* carry no meaning.  Where it turns out to,
    two real boxes land on one number and the caller can say so.

    The match is anchored at both ends: ``TC-01`` is not in the ``C`` series,
    and ``C-10`` does not make ``C-01`` look taken.
    """
    pattern = re.compile(rf"{re.escape(prefix)}[{SEPARATORS}]?([0-9]+)", re.IGNORECASE)
    taken: dict[int, set[str]] = {}
    for cid in ids:
        match = pattern.fullmatch(cid.strip())
        if match:
            taken.setdefault(int(match.group(1)), set()).add(cid.strip())
    return taken


def free_numbers(used: Iterable[int], start: int, stop: int) -> Iterable[int]:
    """Yield the numbers in ``start``..``stop`` (both inclusive) that are not used.

    Lazy, so a mistyped ``--max`` costs nothing until the numbers are consumed.
    """
    return (n for n in range(start, stop + 1) if n not in used)


def format_id(prefix: str, number: int, width: int) -> str:
    """Render one ID the canonical way: uppercase prefix, dash, zero-padded number."""
    return f"{prefix.upper()}-{number:0{width}d}"


def load_inventory(path: Path) -> dict:
    """Load inventory data from JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be zero or greater, not {number}")
    return number


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be one or greater, not {number}")
    return number


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print the unused IDs of a numbered container series.",
        epilog="Example: find-space-in-series.py C -n 1  →  the next free C container",
    )
    parser.add_argument("prefix", help="Series prefix, e.g. C (matched case-insensitively)")
    parser.add_argument(
        "inventory",
        nargs="?",
        type=Path,
        default=Path("inventory.json"),
        help="Path to inventory.json (default: inventory.json in the current directory)",
    )
    parser.add_argument(
        "--start",
        type=_nonnegative,
        default=1,
        help="Lowest number in the series (default: 1; pass 0 for a series numbering from zero)",
    )
    parser.add_argument(
        "--max",
        type=_nonnegative,
        default=99,
        dest="stop",
        help="Highest number in the series (default: 99)",
    )
    parser.add_argument("-n", "--count", type=_positive, help="Print at most this many free IDs (default: all)")

    args = parser.parse_args(argv)
    if not args.prefix.strip():
        parser.error("prefix must not be empty")
    if args.stop < args.start:
        parser.error(f"--max ({args.stop}) is below --start ({args.start})")
    return args


def warn_about_collisions(taken: dict[int, set[str]]) -> None:
    """Report numbers that two differently-spelled IDs both claim.

    Zero padding is meant to be insignificant, so a collision means either one
    box written two ways or — the case worth knowing about — two boxes that
    need relabelling.
    """
    for number, spellings in sorted(taken.items()):
        if len(spellings) > 1:
            print(
                f"Warning: {', '.join(sorted(spellings))} all mean number {number} — "
                "one box written several ways, or several boxes needing relabelling.",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        ids = container_ids(load_inventory(args.inventory))
    except FileNotFoundError:
        print(
            f"Error: {args.inventory} not found. Run: inventory-md parse inventory.md",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as e:  # ValueError covers json.JSONDecodeError
        print(f"Error: could not read {args.inventory}: {e}", file=sys.stderr)
        return 2

    taken = used_numbers(ids, args.prefix)
    warn_about_collisions(taken)

    width = max(MIN_WIDTH, len(str(args.stop)))
    printed = 0
    for number in free_numbers(taken, args.start, args.stop):
        print(format_id(args.prefix, number, width))
        printed += 1
        if args.count is not None and printed >= args.count:
            break

    if not printed:
        print(
            f"No free ID in {args.prefix.upper()} {args.start}-{args.stop} — raise --max or pick another prefix.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
