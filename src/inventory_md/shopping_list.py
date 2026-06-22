"""
Shopping list generator for inventory system.

Compares wanted-items.md (target stock levels) with inventory.json to generate
a shopping list organized by section.

Supports dated wanted-items files (wanted-items-YYYY-MM-DD[-recipe-name].md)
for temporary shopping needs like recipe ingredients.
"""

import glob
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import vocabulary as vocab_module


def parse_amount(value: str | None) -> tuple[float | None, str | None]:
    """Parse a mass/volume string into (amount, unit).

    Volume is normalized to liters (``"l"``), mass to grams (``"g"``).
    Returns ``(None, None)`` for invalid or missing input.
    """
    if not value:
        return None, None

    value = value.lower().strip()
    match = re.match(r"^([\d.]+)\s*([a-z]*)", value)
    if not match:
        return None, None

    amount = float(match.group(1))
    unit = match.group(2) or None

    if unit == "kg":
        return amount * 1000, "g"
    elif unit == "ml":
        return amount / 1000, "l"
    elif unit == "cl":
        return amount / 100, "l"
    elif unit == "dl":
        return amount / 10, "l"
    elif unit in ("g", "l"):
        return amount, unit
    elif unit is None:
        return amount, None
    else:
        return amount, unit


def format_amount(amount: float, unit: str | None) -> str:
    """Format amount for human-readable display."""
    if unit == "g" and amount >= 1000:
        return f"{amount / 1000:.1f}kg"
    elif unit == "g":
        return f"{amount:.0f}g"
    elif unit == "l" and amount >= 1:
        return f"{amount:.1f}l"
    elif unit == "l":
        return f"{amount * 1000:.0f}ml"
    elif unit:
        return f"{amount:.4g}{unit}"
    else:
        return f"{amount:.4g}"


@dataclass
class DesiredItem:
    """An item from wanted-items.md with target quantities."""

    tag: str
    description: str
    section: str = ""
    target_qty: float | None = None
    target_mass_g: float | None = None
    target_volume_l: float | None = None


@dataclass
class InventoryItem:
    """An item from inventory.json."""

    tag: str
    item_id: str
    description: str
    qty: float = 1.0
    mass_g: float | None = None
    volume_l: float | None = None
    bb: str | None = None
    location: str | None = None


@dataclass
class Section:
    """A section from the wanted-items file."""

    name: str
    items: list[DesiredItem] = field(default_factory=list)


def parse_wanted_items(content: str) -> list[Section]:
    """Extract desired items from wanted-items.md, organized by section.

    Accepts lines starting with ``* tag:`` (legacy) or ``* category:``
    (preferred).  The value may be a full concept path
    (``food/vegetables/potatoes``) or a leaf name (``potatoes``).
    """
    sections = []
    current_section = Section(name="Uncategorized")

    for line in content.split("\n"):
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            if current_section.items:
                sections.append(current_section)
            current_section = Section(name=header_match.group(1).strip())
            continue

        line = line.strip()
        if not (line.startswith("* tag:") or line.startswith("* category:")):
            continue

        tag_match = re.search(r"(?:tag|category):(\S+)", line)
        if not tag_match:
            continue
        tag = tag_match.group(1)

        desc_match = re.search(r" - (.+?)(?:\s+target:|$)", line)
        if desc_match:
            description = desc_match.group(1).strip()
        else:
            tag_parts = tag.split(",")[0].split("/")
            description = tag_parts[-1].replace("-", " ").replace("_", " ").title()

        target_qty = None
        target_mass_g = None
        target_volume_l = None

        qty_match = re.search(r"target:qty:(\S+)", line)
        if qty_match:
            amount, unit = parse_amount(qty_match.group(1))
            if unit == "g":
                target_mass_g = amount
            elif unit == "l":
                target_volume_l = amount
            elif amount is not None:
                target_qty = amount

        mass_match = re.search(r"mass:(\S+)", line)
        if mass_match:
            amount, unit = parse_amount(mass_match.group(1))
            if unit == "g" and amount is not None and target_mass_g is None:
                target_mass_g = amount

        volume_match = re.search(r"volume:(\S+)", line)
        if volume_match:
            amount, unit = parse_amount(volume_match.group(1))
            if unit == "l" and amount is not None and target_volume_l is None:
                target_volume_l = amount

        current_section.items.append(
            DesiredItem(
                tag=tag,
                description=description,
                section=current_section.name,
                target_qty=target_qty,
                target_mass_g=target_mass_g,
                target_volume_l=target_volume_l,
            )
        )

    if current_section.items:
        sections.append(current_section)

    return sections


def parse_inventory_for_shopping(
    inventory_data: dict,
    concepts: dict | None = None,
    lang: str = "en",
) -> list[InventoryItem]:
    """Extract tagged/categorised items from inventory.json data.

    ``inventory_data`` is the loaded inventory.json dict.
    ``concepts`` is an optional vocabulary concepts dict; when provided,
    category leaf names are resolved to canonical concept IDs.
    ``lang`` is used for path-alias resolution.

    Handles both new-format inventory.json (``mass_g``/``volume_l`` as floats,
    ``qty`` as float) and old-format (``mass``/``volume`` as strings,
    ``qty`` as string).
    """
    # Build a mapping from container id to container for location path resolution
    containers_list = inventory_data.get("containers", [])
    container_by_id: dict[str, dict] = {c["id"]: c for c in containers_list if c.get("id")}

    def _container_path(container_id: str) -> str:
        """Return a slash-joined path of container IDs from root to this container."""
        parts = []
        seen = set()
        cid = container_id
        while cid and cid not in seen:
            seen.add(cid)
            parts.append(cid)
            parent = container_by_id.get(cid, {}).get("parent")
            cid = parent
        return " / ".join(reversed(parts))

    items = []
    for container in containers_list:
        for item_data in container.get("items", []):
            meta = item_data.get("metadata", {})

            categories = meta.get("categories", [])

            if not categories:
                continue

            resolved = []
            for cat in categories:
                if concepts:
                    canonical = vocab_module.resolve_category(cat, concepts, lang)
                    resolved.append(canonical if canonical is not None else cat.lower())
                else:
                    resolved.append(cat.lower())
            tag = ",".join(resolved)
            if not tag:
                continue

            qty_raw = meta.get("qty")
            try:
                qty = float(qty_raw) if qty_raw is not None else 1.0
            except (TypeError, ValueError):
                qty = 1.0

            # mass: new format has mass_g (float), old format has mass (string)
            mass_g = None
            if "mass_g" in meta:
                try:
                    mass_g = float(meta["mass_g"])
                except (TypeError, ValueError):
                    pass
            elif "mass" in meta:
                amount, unit = parse_amount(str(meta["mass"]))
                if unit == "g" and amount is not None:
                    mass_g = amount

            # volume: new format has volume_l (float), old format has volume (string)
            volume_l = None
            if "volume_l" in meta:
                try:
                    volume_l = float(meta["volume_l"])
                except (TypeError, ValueError):
                    pass
            elif "volume" in meta:
                amount, unit = parse_amount(str(meta["volume"]))
                if unit == "l" and amount is not None:
                    volume_l = amount

            bb = meta.get("bb")
            container_id = container.get("id")
            location = _container_path(container_id) if container_id else None

            items.append(
                InventoryItem(
                    tag=tag,
                    item_id=item_data.get("id") or "",
                    description=item_data.get("name") or "",
                    qty=qty,
                    mass_g=mass_g,
                    volume_l=volume_l,
                    bb=bb,
                    location=location,
                )
            )

    return items


def tag_matches(
    desired_tag: str,
    inventory_tag: str,
    concepts: dict | None = None,
) -> bool:
    """Check if an inventory tag/category is matched by a desired tag.

    Supports:
    - Exact match: ``food/grains/pasta`` matches ``food/grains/pasta``
    - Ancestor match: ``food/grains`` matches ``food/grains/pasta``
    - Comma-separated tags on either side (any desired matches any inventory)
    - Vocabulary-aware narrower lookup: ``food/nuts`` matches ``peanuts`` when
      concepts is provided and peanuts.broader includes food/nuts (directly or
      transitively).
    """
    desired_tags = [t.strip().lower() for t in desired_tag.split(",")]
    inventory_tags = [t.strip().lower() for t in inventory_tag.split(",")]

    for dt in desired_tags:
        for it in inventory_tags:
            if dt == it or it.startswith(dt + "/"):
                return True
            if concepts and vocab_module.is_descendant_of(it, dt, concepts):
                return True

    return False


def find_matches(
    desired: DesiredItem,
    inventory: list[InventoryItem],
    concepts: dict | None = None,
) -> list[InventoryItem]:
    """Find inventory items matching a desired item."""
    return [item for item in inventory if tag_matches(desired.tag, item.tag, concepts)]


def evaluate_item(
    desired: DesiredItem,
    inventory: list[InventoryItem],
    concepts: dict | None = None,
) -> tuple[str, str]:
    """Evaluate stock status for a desired item.

    Returns ``(status, detail_text)`` where status is ``"ok"``, ``"low"``,
    or ``"missing"``.  Items past their best-before date still count toward
    stock — inspecting and discarding expired items is a separate activity.
    """
    matches = find_matches(desired, inventory, concepts)

    total_qty = sum(m.qty for m in matches)
    total_mass_g = sum((m.mass_g or 0) * m.qty for m in matches)
    total_volume_l = sum((m.volume_l or 0) * m.qty for m in matches)

    if desired.target_mass_g is not None:
        have, need, unit = total_mass_g, desired.target_mass_g, "g"
        is_satisfied = have >= need
    elif desired.target_volume_l is not None:
        have, need, unit = total_volume_l, desired.target_volume_l, "l"
        is_satisfied = have >= need
    else:
        have, need, unit = total_qty, desired.target_qty or 1.0, None
        is_satisfied = have >= need

    if not matches:
        if unit:
            detail = f"need {format_amount(need, unit)}"
        elif need > 1:
            detail = f"need {need:.4g}"
        else:
            detail = ""
        return "missing", f"{detail} - not in inventory" if detail else "not in inventory"

    if total_qty == 0:
        return "missing", "out of stock"

    if not is_satisfied:
        have_str = format_amount(have, unit) if unit else f"{have:.4g}"
        need_str = format_amount(need, unit) if unit else f"{need:.4g}"
        if unit and have == 0 and total_qty > 0:
            have_str = f"{have_str} ({total_qty:.4g} items without {unit} data)"
        return "low", f"have {have_str}, need {need_str}"

    return "ok", ""


def find_dated_wanted_files(base_path: Path) -> list[Path]:
    """Find dated wanted-items files (``wanted-items-YYYY-MM-DD[-recipe-name].md``), sorted oldest first."""
    directory = base_path.parent
    dated_files = []
    for filepath in glob.glob(str(directory / "wanted-items-*.md")):
        path = Path(filepath)
        if re.match(r"wanted-items-\d{4}-\d{2}-\d{2}(?:-.*)?\.md$", path.name):
            dated_files.append(path)
    return sorted(dated_files)


def merge_sections(all_sections: list[list[Section]]) -> list[Section]:
    """Merge sections from multiple wanted-items files; same-named sections are combined."""
    merged: dict[str, Section] = {}
    for sections in all_sections:
        for section in sections:
            if section.name in merged:
                merged[section.name].items.extend(section.items)
            else:
                merged[section.name] = Section(name=section.name, items=list(section.items))
    return list(merged.values())


def generate_shopping_list(
    wanted_path: Path,
    inventory_json_path: Path,
    include_dated: bool = False,
    vocab_path: Path | None = None,
    lang: str = "en",
) -> str:
    """Generate shopping list markdown from wanted-items.md and inventory.json.

    ``vocab_path`` defaults to ``vocabulary.json`` in the same directory as
    ``inventory_json_path``.  ``lang`` is used for path-alias resolution.
    """
    if vocab_path is None:
        candidate = inventory_json_path.parent / "vocabulary.json"
        if candidate.exists():
            vocab_path = candidate

    concepts = None
    if vocab_path is not None and vocab_path.exists():
        concepts = vocab_module.load_local_vocabulary(vocab_path)

    inventory_data = json.loads(inventory_json_path.read_text(encoding="utf-8"))
    inv_items = parse_inventory_for_shopping(inventory_data, concepts=concepts, lang=lang)

    all_sections = [parse_wanted_items(wanted_path.read_text(encoding="utf-8"))]
    if include_dated:
        for dated_path in find_dated_wanted_files(wanted_path):
            if dated_path.exists():
                all_sections.append(parse_wanted_items(dated_path.read_text(encoding="utf-8")))

    sections: list[Section] = merge_sections(all_sections) if include_dated else all_sections[0]

    # Resolve wanted-item categories/tags to canonical concept IDs
    if concepts:
        for section in sections:
            for desired in section.items:
                canonical = vocab_module.resolve_category(desired.tag, concepts, lang)
                if canonical is not None:
                    desired.tag = canonical

    lines = ["# Shopping List", "", f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

    total_missing = 0
    total_low = 0
    total_ok = 0

    for section in sections:
        section_items = []

        for desired in section.items:
            status, detail = evaluate_item(desired, inv_items, concepts)

            if status == "missing":
                total_missing += 1
                text = f"[!] {desired.description} ({detail})" if detail else f"[!] {desired.description}"
                section_items.append((0, text))
            elif status == "low":
                total_low += 1
                section_items.append((1, f"[ ] {desired.description}: {detail}"))
            else:
                total_ok += 1

        if section_items:
            lines.append(f"## {section.name}")
            lines.append("")
            section_items.sort(key=lambda x: x[0])
            for _, text in section_items:
                lines.append(text)
            lines.append("")

    lines += ["---", "", f"**Summary:** {total_missing} missing, {total_low} low stock, {total_ok} fully stocked"]

    return "\n".join(lines)
