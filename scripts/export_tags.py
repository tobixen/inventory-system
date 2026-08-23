#!/usr/bin/env python3
"""
Export Tag Statistics

Exports tag usage statistics from an inventory to various formats.

Usage:
    python export_tags.py [path/to/inventory.json] [--format FORMAT]

Formats:
    text (default) - Human-readable text output
    csv            - CSV format for spreadsheets
    json           - JSON format for further processing
"""

import csv
import json
import sys
from collections import Counter
from io import StringIO
from pathlib import Path


def load_inventory(path: Path) -> dict:
    """Load inventory data from JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def collect_tags(data: dict) -> Counter:
    """Collect all tags and their counts."""
    tags = Counter()

    for container in data.get("containers", []):
        # Container-level tags
        container_tags = container.get("metadata", {}).get("tags", [])
        tags.update(container_tags)

        # Item-level tags
        for item in container.get("items", []):
            item_tags = item.get("metadata", {}).get("tags", [])
            tags.update(item_tags)

    return tags


def format_text(tags: Counter) -> str:
    """Format tags as human-readable text."""
    lines = ["Tag Statistics", "=" * 40, ""]
    lines.append(f"Total unique tags: {len(tags)}")
    lines.append(f"Total tag usages: {sum(tags.values())}")
    lines.append("")
    lines.append(f"{'Tag':<30} {'Count':>6}")
    lines.append("-" * 40)

    for tag, count in tags.most_common():
        lines.append(f"{tag:<30} {count:>6}")

    return "\n".join(lines)


def format_csv(tags: Counter) -> str:
    """Format tags as CSV."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["tag", "count"])

    for tag, count in tags.most_common():
        writer.writerow([tag, count])

    return output.getvalue()


def format_json(tags: Counter) -> str:
    """Format tags as JSON."""
    data = {
        "total_unique": len(tags),
        "total_usages": sum(tags.values()),
        "tags": [{"tag": tag, "count": count} for tag, count in tags.most_common()],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def main():
    # Parse arguments
    output_format = "text"
    args = []

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] in ("--format", "-f") and i + 1 < len(sys.argv):
            output_format = sys.argv[i + 1]
            i += 2
        elif sys.argv[i].startswith("-"):
            i += 1
        else:
            args.append(sys.argv[i])
            i += 1

    # Determine inventory path
    if args:
        inventory_path = Path(args[0])
    else:
        inventory_path = Path("inventory.json")

    if not inventory_path.exists():
        print(f"Error: {inventory_path} not found", file=sys.stderr)
        sys.exit(1)

    # Load and process
    data = load_inventory(inventory_path)
    tags = collect_tags(data)

    # Format output
    formatters = {
        "text": format_text,
        "csv": format_csv,
        "json": format_json,
    }

    if output_format not in formatters:
        print(f"Error: Unknown format '{output_format}'", file=sys.stderr)
        print(f"Available formats: {', '.join(formatters.keys())}", file=sys.stderr)
        sys.exit(1)

    print(formatters[output_format](tags))


if __name__ == "__main__":
    main()
