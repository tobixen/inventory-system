#!/usr/bin/env python3
"""
Inventory Data Quality Checker

Checks an inventory.json file for data quality issues including:
- Duplicate container IDs
- Missing parent references
- Items tagged TODO
- Items without a category
- Items whose category doesn't resolve in the vocabulary / tingbok
- Empty containers
- Missing descriptions

Usage:
    python check_quality.py [--tingbok-url URL] [--no-tingbok] [--fix-categories] [path/to/inventory.json]

If no path is provided, looks for inventory.json in current directory.
Tingbok URL defaults to https://tingbok.plann.no.
Language is read from inventory-md.yaml next to the inventory file.

Exit codes:
    0 - No issues found
    1 - Issues found (printed to stdout)
    2 - File not found or other error
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    from inventory_md import vocabulary as _vocabulary
    from inventory_md.config import CONFIG_FILENAMES as _CONFIG_FILENAMES
    from inventory_md.config import Config as _Config
    from inventory_md.parser import validate_inventory as _validate_inventory

    _VOCAB_AVAILABLE = True
except ImportError:
    _VOCAB_AVAILABLE = False
    _CONFIG_FILENAMES = ("inventory-md.yaml", "inventory-md.json")
    _validate_inventory = None

DEFAULT_TINGBOK_URL = "https://tingbok.plann.no"

# Categories considered too broad to be useful: a more specific child should be
# preferred (e.g. ``tomatoes`` instead of ``vegetables``). Broad categories are
# nearly useless for the shopping-list generator and expiry tracking, so by
# default they fail QA. A product may legitimately fall back to a broad/parent
# category when *no* narrower concept fits — exempt that item with one of
# OVERRIDE_BROAD_TAGS, or disable the check globally with
# --allow-broad-categories. Extend this set as needed; matching is on the
# category's leaf component (the part after the last "/"), case-insensitively.
DEFAULT_BROAD_CATEGORIES = {
    "food",
    "foods",
    "drink",
    "drinks",
    "beverage",
    "beverages",
    "vegetable",
    "vegetables",
    "fruit",
    "fruits",
    "nut",
    "nuts",
    "meat",
    "meats",
    "fish",
    "seafood",
    "dairy",
    "cheese",
    "grain",
    "grains",
    "cereal",
    "cereals",
    "legume",
    "legumes",
    "bakery",
    "snack",
    "snacks",
    "sweets",
    "candy",
    "produce",
    "groceries",
    "misc",
}

# Per-item metadata tags that exempt an item from the broad-category check.
OVERRIDE_BROAD_TAGS = ("category-broad-ok", "broad-category-ok")

_NB_LANGS = {"nb", "no", "nn"}


def load_inventory(path: Path) -> dict:
    """Load inventory data from JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_inventory_lang(inventory_path: Path) -> str:
    """Read the lang setting from a config file next to the inventory file."""
    if not _VOCAB_AVAILABLE:
        return "en"
    for name in _CONFIG_FILENAMES:
        cfg_path = inventory_path.parent / name
        if cfg_path.exists():
            try:
                return _Config(path=cfg_path).lang
            except Exception:
                pass
    return "en"


def _nb_eq(a: str, b: str) -> bool:
    """Treat nb/no/nn as equivalent for language comparison."""
    if a == b:
        return True
    return a in _NB_LANGS and b in _NB_LANGS


def _preferred_label(concept_data: dict, lang: str) -> str:
    """Return the preferred category string for a concept in the given language.

    For English: the canonical concept ID.
    For other languages: the first altLabel in that language, falling back to the ID.
    """
    canonical = concept_data.get("id", "")
    if lang == "en":
        return canonical
    alt_labels = concept_data.get("altLabel", {})
    for alt_lang, labels in alt_labels.items():
        if _nb_eq(alt_lang, lang) and labels:
            return labels[0]
    return canonical


def _is_valid_label_for_lang(label: str, concept_data: dict, lang: str) -> bool:
    """Check whether a label is the canonical form for the given language.

    For English: label must equal the concept ID (or its leaf component).
    For other languages: label must appear in altLabels[lang].
    """
    canonical = concept_data.get("id", "")
    label_lower = label.lower()
    if lang == "en":
        return label_lower == canonical.lower() or label_lower == canonical.split("/")[-1].lower()
    alt_labels = concept_data.get("altLabel", {})
    for alt_lang, labels in alt_labels.items():
        if _nb_eq(alt_lang, lang):
            if any(lbl.lower() == label_lower for lbl in labels):
                return True
    return False


def check_todo_items(data: dict) -> list:
    """Find items tagged with TODO."""
    containers = data.get("containers", [])
    issues = []

    for container in containers:
        for item in container.get("items", []):
            tags = item.get("metadata", {}).get("tags", [])
            if "TODO" in tags:
                name = item.get("name") or item.get("raw_text", "")
                issues.append(f"TODO item in {container['id']}: {name[:50]}")
    return issues


def check_items_without_category(data: dict) -> list:
    """Find items without any category."""
    containers = data.get("containers", [])
    count = sum(1 for c in containers for item in c.get("items", []) if not item.get("metadata", {}).get("categories"))
    if not count:
        return []
    return [f"Items without category: {count} items have no category"]


def check_broad_categories(data: dict, broad: set[str]) -> list:
    """Flag items whose category is too broad to be useful.

    A category is too broad when its leaf component (after the last ``/``) is in
    ``broad`` — e.g. ``vegetables`` or ``food/vegetables``. Broad buckets are
    almost useless for the shopping-list generator and expiry tracking, so a
    specific child (``tomatoes``) should be preferred. An item may legitimately
    keep a broad/parent category when *no* narrower concept fits; exempt it with
    one of OVERRIDE_BROAD_TAGS, or disable the check with --allow-broad-categories.
    """
    offenders: list[str] = []
    for container in data.get("containers", []):
        for item in container.get("items", []):
            md = item.get("metadata", {})
            if any(t in md.get("tags", []) for t in OVERRIDE_BROAD_TAGS):
                continue
            for cat in md.get("categories", []):
                parts = cat.strip().lower().split("/")
                leaf = parts[-1]
                # Broad if the leaf is a broad bucket AND it's either a bare
                # category or rooted at ``food`` — so a non-food path like
                # ``hardware/nut`` is NOT broad even though its leaf ("nut")
                # collides with food "nuts".
                if leaf in broad and (len(parts) == 1 or parts[0] == "food"):
                    ident = item.get("id") or (item.get("name") or "")[:30]
                    offenders.append(f"{ident} (category:{cat})")
                    break
    if not offenders:
        return []
    sample = "; ".join(offenders[:8])
    more = "" if len(offenders) <= 8 else f"; … (+{len(offenders) - 8} more)"
    return [
        f"Broad categories ({len(offenders)}): use a specific child or exempt with "
        f"tag {OVERRIDE_BROAD_TAGS[0]!r} (or --allow-broad-categories) — {sample}{more}"
    ]


def _under_food(concept_id: str) -> bool:
    """True if *concept_id* is ``food`` itself or sits on a ``food/`` path."""
    return concept_id == "food" or concept_id.startswith("food/")


def _is_food_concept(concept_data: dict | None, ancestors_of=None) -> bool:
    """True if a resolved concept is under the food hierarchy.

    Food concepts have an id like ``food/...`` or a ``broader`` path rooted at
    ``food`` (e.g. ``chickpeas`` → broader ``food/legumes``). Non-food (e.g.
    ``dishwasher_detergent`` → ``product/chemical_product/...``) returns False.

    The ``broader`` test only reaches one level, so a concept two hops from food
    (``soybeans`` → ``legumes`` → ``food/legumes``) used to come back as
    non-food and its missing best-before went unreported.  *ancestors_of* is an
    optional ``(concept_id) -> list[str] | None`` — normally tingbok's
    ``/ancestors`` endpoint — consulted when the shallow test says no.  It
    returning ``None`` (no such concept, or tingbok unreachable) leaves the
    shallow answer standing, so an offline run is no worse than before.
    """
    if not concept_data:
        return False
    cid = concept_data.get("id") or ""
    if _under_food(cid):
        return True
    if any(_under_food(b) for b in (concept_data.get("broader") or [])):
        return True
    if ancestors_of is not None and cid:
        return any(_under_food(a) for a in (ancestors_of(cid) or ()))
    return False


def check_food_without_bb(data: dict, is_food) -> list:
    """Flag food items that have no best-before date.

    ``is_food`` is a callable ``(category_leaf) -> bool``. An item is a food
    product if any of its categories is food; every food product should carry a
    best-before (``bb``) date.
    """
    offenders: list[str] = []
    for container in data.get("containers", []):
        for item in container.get("items", []):
            md = item.get("metadata", {})
            if md.get("bb"):
                continue
            if any(is_food(cat) for cat in md.get("categories", [])):
                offenders.append(item.get("id") or (item.get("name") or "")[:30])
    if not offenders:
        return []
    sample = ", ".join(offenders[:5])
    more = "" if len(offenders) <= 5 else ", …"
    return [f"Food items without best-before: {len(offenders)} items — e.g. {sample}{more}"]


def _category_is_food(cat: str, resolve, ancestors_of=None) -> bool:
    """Whether a category string denotes food.

    An explicit path is trusted by its root: ``food/...`` is food, anything else
    (``hardware/nuts``, ``product/...``) is not — this disambiguates leaves like
    ``nuts`` that resolve to ``food/nuts`` but are written ``hardware/nuts`` for
    fasteners. A bare leaf is resolved via *resolve* and checked for a food
    ancestor, using *ancestors_of* when the concept's own ``broader`` does not
    settle it.
    """
    if "/" in cat:
        return cat.split("/", 1)[0] == "food"
    return _is_food_concept(resolve(cat), ancestors_of=ancestors_of)


def _make_food_classifier(base: str | None):
    """Return a cached ``is_food(category) -> bool`` backed by tingbok."""
    cache: dict[str, bool] = {}

    def resolve(leaf: str) -> dict | None:
        return _lookup_tingbok(leaf, base) if base else None

    def ancestors_of(concept_id: str) -> list | None:
        if not base or not _VOCAB_AVAILABLE:
            return None
        return _vocabulary.fetch_ancestors_from_tingbok(
            concept_id, base, cache_dir=_vocabulary.default_tingbok_cache_dir()
        )

    def is_food(cat: str) -> bool:
        if cat not in cache:
            cache[cat] = _category_is_food(cat, resolve, ancestors_of=ancestors_of)
        return cache[cat]

    return is_food


def _lookup_tingbok(leaf: str, base: str) -> dict | None:
    """GET /api/lookup/{leaf}; return parsed JSON or None on 404/error."""
    import niquests

    try:
        resp = niquests.get(f"{base}/api/lookup/{leaf}", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def check_unresolvable_categories(
    data: dict,
    concepts: dict,
    lang: str,
    tingbok_url: str | None,
) -> tuple[list, list, dict[str, str]]:
    """Check that every category resolves, and suggest canonical/lang fixes.

    Returns:
        (warnings, infos, fix_map)
        fix_map: {old_category: new_category} for --fix-categories
    """
    containers = data.get("containers", [])

    # Collect unique categories that don't resolve locally
    locally_unresolved: Counter = Counter()
    for container in containers:
        for item in container.get("items", []):
            for cat in item.get("metadata", {}).get("categories", []):
                if _vocabulary.resolve_category(cat, concepts, lang=lang) is None:
                    locally_unresolved[cat] += 1

    if not locally_unresolved:
        return [], [], {}

    base = tingbok_url.rstrip("/") if tingbok_url else None
    unresolvable: Counter = Counter()
    infos: list[str] = []
    fix_map: dict[str, str] = {}

    for cat, n in locally_unresolved.items():
        parts = cat.split("/")

        if len(parts) == 1:
            # Simple label: look it up directly
            concept_data = _lookup_tingbok(cat, base) if base else None
            if concept_data is None:
                unresolvable[cat] = n
                continue
            if _is_valid_label_for_lang(cat, concept_data, lang):
                # Already the right form for this language
                continue
            preferred = _preferred_label(concept_data, lang)
            if preferred.lower() != cat.lower():
                infos.append(f"Non-canonical category {cat!r} ({n}×) → consider using {preferred!r}")
                fix_map[cat] = preferred
        else:
            # Path: validate each component and hierarchy
            path_warnings, path_infos, path_fixes = _check_category_path(cat, n, lang, base, concepts)
            unresolvable.update(path_warnings)
            infos.extend(path_infos)
            fix_map.update(path_fixes)

    warnings = []
    if unresolvable:
        total = sum(unresolvable.values())
        top = ", ".join(f"{cat!r} ({n})" for cat, n in unresolvable.most_common(5))
        warnings.append(f"Unresolvable categories: {total} items use unknown categories — top: {top}")

    return warnings, infos, fix_map


def _check_category_path(
    cat: str,
    n: int,
    lang: str,
    base: str | None,
    concepts: dict,
) -> tuple[Counter, list[str], dict[str, str]]:
    """Validate a multi-component category path.

    Checks:
    - Each component resolves to a concept
    - Each concept is a valid broader of the next
    - Each component is the preferred label for the inventory language

    Returns (unresolvable_counter, infos, fix_map).
    """
    parts = cat.split("/")
    resolved: list[dict | None] = []

    if base:
        for part in parts:
            resolved.append(_lookup_tingbok(part, base))
    else:
        resolved = [None] * len(parts)

    # Check each component resolves
    unresolvable: Counter = Counter()
    bad_parts = [p for p, r in zip(parts, resolved, strict=False) if r is None]
    if bad_parts:
        unresolvable[cat] = n
        return unresolvable, [], {}

    # Validate hierarchy: each concept should be broader than the next
    hierarchy_ok = True
    for i in range(len(resolved) - 1):
        parent_id = resolved[i]["id"]
        child_broader = resolved[i + 1].get("broader", [])
        if parent_id not in child_broader:
            hierarchy_ok = False
            break

    if not hierarchy_ok:
        return Counter({cat: n}), [f"Invalid category path {cat!r} ({n}×): hierarchy mismatch"], {}

    # Check each component is the preferred label for lang, build fix if needed
    preferred_parts = [_preferred_label(r, lang) for r in resolved]
    preferred_path = "/".join(preferred_parts)

    infos: list[str] = []
    fix_map: dict[str, str] = {}

    if preferred_path.lower() != cat.lower():
        infos.append(f"Non-canonical path {cat!r} ({n}×) → consider using {preferred_path!r}")
        fix_map[cat] = preferred_path

    return Counter(), infos, fix_map


def _separator_key(concept_id: str) -> str:
    """Concept ID with dashes, underscores and spaces removed, casefolded."""
    return re.sub(r"[-_ ]", "", concept_id.casefold())


def _singular_key(key: str) -> str:
    """A crude singular form of an already separator-normalised key.

    Deliberately crude, because it only ever compares IDs that both exist: a
    rule that over-fires in the abstract can only produce a false report when
    the inventory genuinely contains both spellings.  Words of three characters
    or fewer after the strip are left alone, so ``gas`` is not read as a plural
    of ``ga``.
    """
    for suffix, replacement in (("ies", "y"), ("es", ""), ("s", "")):
        if key.endswith(suffix) and len(key) - len(suffix) >= 3:
            return key[: -len(suffix)] + replacement
    return key


#: Known false negatives of :func:`_singular_key`: it is applied to both sides
#: of a candidate pair, so a singular that itself ends in ``s`` is stripped too
#: and the pair never meets — ``glass``/``glasses``, ``lens``/``lenses``,
#: ``dress``/``dresses``.  Left alone deliberately: a stemmer good enough to
#: tell those apart is a bigger thing than this report, which is advisory and
#: is read by someone who can see the two IDs anyway.


def _duplicate_concept_groups(concepts: dict) -> tuple[list[list[str]], list[list[str]]]:
    """Return (separator-variant groups, plural-variant groups) of concept IDs.

    The whole ID is normalised, not just the leaf: upstream taxonomies reach one
    concept by many ancestor chains — ``book`` sits under 30 different paths in
    a real vocabulary — and those are the same concept, not a typo.

    Every ID is considered for both rules.  Excluding the members of a separator
    group from the plural pass loses a third spelling: given ``bike-clamp``,
    ``bike_clamp`` and ``bike-clamps``, the report would name the first two and
    never mention the third, so the reader fixes the report rather than the
    category.  A plural group that adds nothing to a separator group already
    reported is dropped, so nothing is said twice.
    """
    by_separator: dict[str, list[str]] = {}
    for cid in concepts:
        by_separator.setdefault(_separator_key(cid), []).append(cid)

    separator_groups = [sorted(ids) for key, ids in sorted(by_separator.items()) if len(ids) > 1]
    already_reported = {frozenset(g) for g in separator_groups}

    by_singular: dict[str, list[str]] = {}
    for key, ids in by_separator.items():
        by_singular.setdefault(_singular_key(key), []).extend(ids)
    plural_groups = [
        sorted(ids)
        for key, ids in sorted(by_singular.items())
        if len(ids) > 1 and frozenset(ids) not in already_reported
    ]

    return separator_groups, plural_groups


def check_duplicate_concepts(concepts: dict) -> list:
    """Flag concept IDs that differ only in separator or in plural form.

    ``cling-film`` and ``clingfilm``, ``bike-clamp`` and ``bike_clamp``,
    ``lentil`` and ``lentils`` are each one category written two ways, and each
    spelling then carries half the items.

    Both spellings usually come back marked tingbok-sourced, which is why this
    does not filter by source: `bike_hardware` is in tingbok's vocabulary and
    `bike-hardware` is not, but the inventory wrote the latter, tingbok resolved
    it on its own, and the result is two concepts.  Measured against
    `~/solveig-inventory` on 2026-09-01: 65 groups, 46 of them with both
    spellings marked tingbok-sourced.

    Reported, not repaired.  Which spelling is canonical — dashes or
    underscores, singular or plural — is an open question in tingbok's own
    consistency TODO, and normalising them here would decide it by accident.
    """
    separator_groups, plural_groups = _duplicate_concept_groups(concepts)

    issues: list[str] = []
    for groups, detail in ((separator_groups, "separator"), (plural_groups, "plural form")):
        if not groups:
            continue
        sample = "; ".join(" + ".join(g) for g in groups[:8])
        more = "" if len(groups) <= 8 else f"; … (+{len(groups) - 8} more)"
        issues.append(f"Category IDs differing only in {detail} ({len(groups)}): {sample}{more}")
    return issues


def check_empty_containers(data: dict) -> list:
    """Find containers with no items."""
    containers = data.get("containers", [])
    empty = [c["id"] for c in containers if not c.get("items")]

    if not empty:
        return []

    return [f"Empty containers: {len(empty)} ({', '.join(empty[:10])}{'...' if len(empty) > 10 else ''})"]


def check_missing_descriptions(data: dict) -> list:
    """Find containers without descriptions."""
    containers = data.get("containers", [])
    missing = [c["id"] for c in containers if not c.get("description", "").strip()]

    if not missing:
        return []

    return [f"Missing descriptions: {len(missing)} containers have no description"]


def check_containers_without_images(data: dict) -> list:
    """Find containers without any images."""
    containers = data.get("containers", [])
    no_images = [c["id"] for c in containers if not c.get("images")]

    if not no_images:
        return []

    return [f"No images: {len(no_images)} containers have no photos"]


# An EAN already namespaced with a shop name, e.g. ``biltema-463491`` or
# ``lidl-20241988``. A real GTIN never contains a hyphen, so a hyphenated key
# is a shop-prefixed local code (matching tingbok's own convention).
_SHOP_PREFIXED_EAN = re.compile(r"^[A-Za-z][A-Za-z0-9]*-")


def check_shop_specific_eans(data: dict) -> list:
    """Flag shop-local article numbers stored as a bare, un-prefixed EAN.

    GS1 reserves the "2" prefix (the whole first-digit-2 range) for
    restricted / in-store / variable-measure codes. Such numbers are assigned
    by the shop and are *not globally unique* — different chains reuse the same
    number for different products — so they must be namespaced as
    ``EAN:<shop>-<code>`` (e.g. ``lidl-20241988``, ``biltema-463491``) to avoid
    cross-shop collisions. tingbok stores them under shop-prefixed keys; the
    bare code may still resolve upstream (many Lidl codes are in Open Food
    Facts), which is exactly why the shop namespace is needed to disambiguate.

    Two kinds of shop-local code are flagged:

    * **In-store barcodes** in the GS1 restricted range (first digit ``2``),
      e.g. Lidl weighed-goods codes like ``20241988``.
    * **Shop article numbers** that are not a valid GTIN length (8/12/13/14
      digits), e.g. Biltema's ``463491`` (from ``Art. 46-3491``). These aren't
      scannable barcodes at all, just catalogue numbers.

    Values already carrying a ``<shop>-`` prefix pass; ordinary global GTINs
    (valid length, first digit != 2) pass.
    """
    issues = []
    for container in data.get("containers", []):
        for item in container.get("items", []):
            ean = item.get("metadata", {}).get("ean")
            if not ean or _SHOP_PREFIXED_EAN.match(ean) or not ean.isdigit():
                continue
            if ean.startswith("2"):
                reason = "in-store code (GS1 restricted range)"
            elif len(ean) not in (8, 12, 13, 14):
                reason = "shop article number (not a GTIN length)"
            else:
                continue
            name = item.get("name") or item.get("raw_text", "")
            item_id = item.get("id", "?")
            issues.append(
                f"Shop-local EAN lacks shop-name prefix in {container['id']}: "
                f"{item_id} EAN:{ean} ({name[:40]}) — {reason}, use EAN:<shop>-{ean}"
            )
    return issues


def load_vocabulary(inventory_path: Path, tingbok_url: str | None) -> dict:
    """Load vocabulary from tingbok and local files next to the inventory."""
    if not _VOCAB_AVAILABLE:
        return {}
    try:
        concepts = _vocabulary.load_global_vocabulary(tingbok_url=tingbok_url)
        local_vocab_path = inventory_path.parent / "vocabulary.json"
        if local_vocab_path.exists():
            local = _vocabulary.load_local_vocabulary(local_vocab_path)
            concepts.update(local)
        return concepts
    except Exception as e:
        print(f"[WARN] Could not load vocabulary: {e}", file=sys.stderr)
        return {}


def apply_fixes(inventory_path: Path, fix_map: dict[str, str]) -> int:
    """Apply category replacements to inventory.md in-place.

    ``inventory_path`` is the ``.json`` path (as passed everywhere else);
    the ``.md`` source file is derived from it.  Returns the number of
    individual ``category:`` tags replaced.

    Edits the markdown source rather than the generated JSON so fixes survive
    the next ``inventory-md parse`` run.
    """
    md_path = inventory_path.with_suffix(".md")
    if not md_path.exists():
        print(f"apply_fixes: {md_path} not found — cannot apply fixes", file=sys.stderr)
        return 0

    text = md_path.read_text(encoding="utf-8")
    count = 0
    for old, new in fix_map.items():
        # Match category:OLD only at a token boundary (followed by whitespace or EOL)
        # so category:rice doesn't clobber category:rice-old.
        pattern = r"(?<=\bcategory:)" + re.escape(old) + r"(?=[\s\n]|$)"
        replaced, n = re.subn(pattern, new, text)
        count += n
        text = replaced

    md_path.write_text(text, encoding="utf-8")
    return count


def run_all_checks(
    data: dict,
    concepts: dict,
    lang: str,
    tingbok_url: str | None,
    *,
    allow_broad: bool = False,
    broad_categories: set[str] | None = None,
) -> tuple[dict, dict[str, str]]:
    """Run all quality checks and return (results, fix_map)."""
    warnings = (
        list(check_todo_items(data)) + list(check_items_without_category(data)) + list(check_shop_specific_eans(data))
    )
    infos = check_empty_containers(data) + check_missing_descriptions(data) + check_containers_without_images(data)
    fix_map: dict[str, str] = {}

    if concepts:
        cat_warnings, cat_infos, cat_fixes = check_unresolvable_categories(data, concepts, lang, tingbok_url)
        warnings += cat_warnings
        infos += cat_infos
        fix_map.update(cat_fixes)
        # Advisory: which spelling is canonical is not settled, so this is INFO.
        infos += check_duplicate_concepts(concepts)

    if tingbok_url:
        base = tingbok_url.rstrip("/")
        warnings += check_food_without_bb(data, _make_food_classifier(base))

    errors = list(_validate_inventory(data)) if _validate_inventory else []
    if not allow_broad:
        errors += check_broad_categories(data, broad_categories or DEFAULT_BROAD_CATEGORIES)

    results = {
        "errors": errors,
        "warnings": warnings,
        "info": infos,
    }
    return results, fix_map


def print_results(results: dict) -> bool:
    """Print check results. Returns True if there are errors or warnings."""
    has_issues = False

    if results["errors"]:
        has_issues = True
        print("ERRORS:")
        for error in results["errors"]:
            print(f"  [ERROR] {error}")
        print()

    if results["warnings"]:
        has_issues = True
        print("WARNINGS:")
        for warning in results["warnings"]:
            print(f"  [WARN]  {warning}")
        print()

    if results["info"]:
        print("INFO:")
        for info in results["info"]:
            print(f"  [INFO]  {info}")
        print()

    if not has_issues and not results["info"]:
        print("All checks passed!")

    return has_issues


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Check inventory data quality.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inventory", nargs="?", default="inventory.json", help="Path to inventory.json")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--fix-categories", action="store_true", help="Apply suggested category fixes")
    parser.add_argument("--no-tingbok", action="store_true", help="Skip tingbok vocabulary lookup")
    parser.add_argument("--tingbok-url", default=DEFAULT_TINGBOK_URL, metavar="URL", help="Tingbok base URL")
    parser.add_argument(
        "--allow-broad-categories",
        action="store_true",
        help="Don't fail on too-broad categories (vegetables, fruit, meat, …). "
        f"Per-item override: tag the item {OVERRIDE_BROAD_TAGS[0]!r}.",
    )
    ns = parser.parse_args()

    tingbok_url: str | None = None if ns.no_tingbok else ns.tingbok_url
    fix_categories = ns.fix_categories
    inventory_path = Path(ns.inventory)

    if not inventory_path.exists():
        parser.error(f"{inventory_path} not found")

    lang = load_inventory_lang(inventory_path)

    print(f"Checking: {inventory_path}")
    print(f"Language: {lang}")
    if _VOCAB_AVAILABLE:
        print(f"Vocabulary: {tingbok_url or 'local only'}")
    else:
        print("Vocabulary: unavailable (inventory_md not importable)")
    print()

    data = load_inventory(inventory_path)
    concepts = load_vocabulary(inventory_path, tingbok_url)
    results, fix_map = run_all_checks(data, concepts, lang, tingbok_url, allow_broad=ns.allow_broad_categories)
    print_results(results)

    if fix_categories:
        if fix_map:
            print(f"Applying {len(fix_map)} category fix(es)...")
            count = apply_fixes(inventory_path, fix_map)
            print(f"  Replaced {count} category string(s) in {inventory_path}")
        else:
            print("No category fixes to apply.")

    sys.exit(1 if results["errors"] else 0)


if __name__ == "__main__":
    main()
