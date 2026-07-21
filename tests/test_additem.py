"""Tests for the `inventory-md add` write path (additem module)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from inventory_md import additem

# --- format_item_line -------------------------------------------------------


def test_format_item_line_minimal():
    line = additem.format_item_line("milk", "milk-2026-06-14")
    assert line == "* category:milk ID:milk-2026-06-14"


def test_format_item_line_full_field_order():
    line = additem.format_item_line(
        "milk",
        "milk-1",
        ean="7038010000000",
        bb="2026-07",
        bb_est=False,
        qty=2,
        mass="1000g",
        volume="1l",
        price="EUR:1.29/pcs",
        tags=["condition:new"],
        name="Whole milk 1l",
    )
    # category, ID, tag, EAN, bb, qty, mass, volume, price, then name last
    assert line == (
        "* category:milk ID:milk-1 tag:condition:new EAN:7038010000000 "
        "bb:2026-07 qty:2 mass:1000g volume:1l price:EUR:1.29/pcs Whole milk 1l"
    )


def test_format_item_line_bb_est_appends_flag():
    line = additem.format_item_line("potatoes", "potatoes-1", bb="2026-09", bb_est=True, name="Potatoes")
    assert "bb:2026-09:EST" in line
    assert line.endswith("Potatoes")


def test_format_item_line_lowercases_category():
    line = additem.format_item_line("Food/Vegetables/Potatoes", "p1")
    assert "category:food/vegetables/potatoes" in line


def test_format_item_line_multiple_categories_preserved():
    line = additem.format_item_line("oatmeal,breakfast", "oats-1")
    assert "category:oatmeal,breakfast" in line


# --- resolve_bb_est ---------------------------------------------------------


def test_resolve_bb_est_suffix_only():
    assert additem.resolve_bb_est("2026-09:EST") == ("2026-09", True)


def test_resolve_bb_est_plain_date_is_asserted():
    assert additem.resolve_bb_est("2026-09") == ("2026-09", False)


def test_resolve_bb_est_explicit_true_without_suffix():
    assert additem.resolve_bb_est("2026-09", True) == ("2026-09", True)


def test_resolve_bb_est_explicit_true_with_suffix_agrees():
    assert additem.resolve_bb_est("2026-09:EST", True) == ("2026-09", True)


def test_resolve_bb_est_explicit_false_conflicts_with_suffix():
    with pytest.raises(ValueError, match="EST"):
        additem.resolve_bb_est("2026-09:EST", False)


def test_resolve_bb_est_explicit_false_without_suffix():
    assert additem.resolve_bb_est("2026-09", False) == ("2026-09", False)


def test_resolve_bb_est_coerces_yaml_date():
    assert additem.resolve_bb_est(date(2026, 9, 1), True) == ("2026-09-01", True)


def test_resolve_bb_est_none_bb():
    assert additem.resolve_bb_est(None) == (None, False)


def test_resolve_bb_est_rejects_non_boolean_flag():
    with pytest.raises(ValueError, match="bb_est"):
        additem.resolve_bb_est("2026-09", "yes")


# --- validate_bb_format -----------------------------------------------------


@pytest.mark.parametrize("bb", ["2026", "2026-07", "2026-07-15", "2026-07-15T08:30"])
def test_validate_bb_format_accepts(bb):
    assert additem.validate_bb_format(bb) is True


@pytest.mark.parametrize("bb", ["july", "2026/07", "26-07", "2026-13-40x"])
def test_validate_bb_format_rejects(bb):
    assert additem.validate_bb_format(bb) is False


# --- collect_existing_ids ---------------------------------------------------


def test_collect_existing_ids_includes_containers_and_items():
    data = {
        "containers": [
            {"id": "food1", "items": [{"id": "milk-1"}, {"id": None}, {"id": "eggs-1"}]},
            {"id": "food2", "items": []},
        ]
    }
    assert additem.collect_existing_ids(data) == {"food1", "food2", "milk-1", "eggs-1"}


# --- generate_item_id -------------------------------------------------------


def test_generate_item_id_food_appends_date():
    item_id = additem.generate_item_id("milk", "Whole milk 1l", set(), is_food=True, today=date(2026, 6, 14))
    assert item_id == "milk-2026-06-14"


def test_generate_item_id_nonfood_no_date():
    item_id = additem.generate_item_id("hammer", "Bosch hammer", set(), is_food=False)
    assert item_id == "hammer"


def test_generate_item_id_avoids_collision():
    existing = {"milk-2026-06-14"}
    item_id = additem.generate_item_id("milk", "milk", existing, is_food=True, today=date(2026, 6, 14))
    assert item_id == "milk-2026-06-14-2"


# --- insert_item_line -------------------------------------------------------

_MD = """# Intro

Demo

# ID:food1 Pantry

Some text.

* category:rice ID:rice-1 bb:2027-01 Rice 1kg
* category:pasta ID:pasta-1 bb:2027-03 Pasta

# ID:food2 Fridge

* category:milk ID:milk-old bb:2026-06 Milk
"""


def test_insert_item_line_after_last_bullet():
    lines = _MD.splitlines()
    new = additem.insert_item_line(lines, "food1", "* category:beans ID:beans-1 bb:2028-01 Beans")
    text = "\n".join(new)
    # inserted into food1, right after pasta line, before the food2 heading
    food1_block = text.split("# ID:food2")[0]
    assert "* category:beans ID:beans-1 bb:2028-01 Beans" in food1_block
    # order preserved: beans comes after pasta
    assert food1_block.index("pasta-1") < food1_block.index("beans-1")


def test_insert_item_line_unknown_container_raises():
    lines = _MD.splitlines()
    with pytest.raises(ValueError, match="nope"):
        additem.insert_item_line(lines, "nope", "* category:x ID:x")


def test_insert_item_line_empty_container():
    md = "# ID:empty Empty container\n\nNo items yet.\n"
    lines = md.splitlines()
    new = additem.insert_item_line(lines, "empty", "* category:milk ID:m1")
    assert "* category:milk ID:m1" in new


# --- end-to-end command -----------------------------------------------------


@pytest.fixture
def inventory_dir(tmp_path: Path) -> Path:
    """A minimal inventory.md + vocabulary.json copied from the example."""
    (tmp_path / "inventory.md").write_text(_MD, encoding="utf-8")
    example_vocab = Path(__file__).parent.parent / "example" / "vocabulary.json"
    (tmp_path / "vocabulary.json").write_text(example_vocab.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_add_item_writes_line(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="milk-new",
        bb="2026-07",
        name="Fresh milk",
    )
    assert not result.errors
    text = md_path.read_text(encoding="utf-8")
    assert "ID:milk-new" in text
    assert result.item_line in text


def test_add_item_rejects_duplicate_id(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="rice-1",  # already present
        bb="2026-07",
    )
    assert any("rice-1" in e for e in result.errors)
    # file unchanged
    assert md_path.read_text(encoding="utf-8") == _MD


def test_add_item_food_without_bb_is_error(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="milk-x",
    )
    assert any("bb" in e.lower() for e in result.errors)
    assert "milk-x" not in md_path.read_text(encoding="utf-8")


def test_add_item_food_without_bb_allowed_with_flag(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="milk-x",
        check_bb=False,
    )
    assert not result.errors
    assert "milk-x" in md_path.read_text(encoding="utf-8")


def test_add_item_nonfood_without_bb_ok(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="hammer",
        item_id="hammer-1",
        name="A hammer in the pantry, weird but valid",
    )
    assert not result.errors
    assert "hammer-1" in md_path.read_text(encoding="utf-8")


def test_add_item_unknown_category_warns(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="zzznotacategory",
        item_id="weird-1",
        name="Mystery",
    )
    assert not result.errors  # warning, not error
    assert any("zzznotacategory" in w for w in result.warnings)
    assert "weird-1" in md_path.read_text(encoding="utf-8")


def test_add_item_unknown_category_strict_errors(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="zzznotacategory",
        item_id="weird-1",
        name="Mystery",
        strict=True,
    )
    assert any("zzznotacategory" in e for e in result.errors)
    assert "weird-1" not in md_path.read_text(encoding="utf-8")


def test_add_item_autogenerates_id_for_food(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        bb="2026-07",
        name="Some milk",
        today=date(2026, 6, 14),
    )
    assert not result.errors
    assert result.item_id == "milk-2026-06-14"
    assert "ID:milk-2026-06-14" in md_path.read_text(encoding="utf-8")


def test_add_item_unknown_container_errors(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="does-not-exist",
        category="milk",
        item_id="m1",
        bb="2026-07",
    )
    assert any("does-not-exist" in e for e in result.errors)


# --- bb as datetime.date (YAML loads unquoted dates as date objects) ---------


def test_add_item_accepts_date_object_bb(inventory_dir: Path):
    """Staging YAML gives ``bb: 2027-02-12`` as datetime.date — must not crash."""
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="milk-dated",
        bb=date(2027, 2, 12),
        name="Milk with date-typed bb",
    )
    assert not result.errors
    assert "bb:2027-02-12" in md_path.read_text(encoding="utf-8")


def test_add_item_accepts_est_suffix_in_bb(inventory_dir: Path):
    """``bb="2026-07:EST"`` is a valid spelling of an estimate, as on a staging row."""
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="milk-est-suffix",
        bb="2026-07:EST",
        name="Milk",
    )
    assert not result.errors
    assert "bb:2026-07:EST" in md_path.read_text(encoding="utf-8")


def test_add_item_est_suffix_conflicting_with_bb_est_false_errors(inventory_dir: Path):
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="milk",
        item_id="milk-conflict",
        bb="2026-07:EST",
        bb_est=False,
        name="Milk",
    )
    assert result.errors
    assert not result.written
    assert "EST" in result.errors[0]


# --- tingbok fallback for categories new to this inventory -------------------


def _fake_resolver(concepts: dict):
    def fake_resolve(labels, url, lang="en", session=None):
        return concepts

    return fake_resolve


def test_add_item_category_resolving_in_tingbok_no_warning(inventory_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """A category unknown locally but valid in tingbok must not warn."""
    from inventory_md import vocabulary

    monkeypatch.setattr(
        additem._vocabulary,
        "resolve_vocabulary_from_tingbok",
        _fake_resolver({"zzz-novel": vocabulary.Concept(id="zzz-novel", prefLabel="Novel", source="tingbok")}),
    )
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="zzz-novel",
        item_id="novel-1",
        name="Novel thing",
        tingbok_url="https://tingbok.test",
    )
    assert not result.errors
    assert not any("does not resolve" in w for w in result.warnings)


def test_add_item_category_unknown_everywhere_still_warns(inventory_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Tingbok returns only an inventory-sourced stub → the warning stays."""
    from inventory_md import vocabulary

    monkeypatch.setattr(
        additem._vocabulary,
        "resolve_vocabulary_from_tingbok",
        _fake_resolver({"zzz-novel": vocabulary.Concept(id="zzz-novel", prefLabel="zzz-novel", source="inventory")}),
    )
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="zzz-novel",
        item_id="novel-2",
        name="Novel thing",
        tingbok_url="https://tingbok.test",
    )
    assert any("does not resolve" in w for w in result.warnings)


def test_add_item_category_warning_kept_when_tingbok_offline(inventory_dir: Path, monkeypatch: pytest.MonkeyPatch):
    from inventory_md import vocabulary

    def fake_resolve(labels, url, lang="en", session=None):
        raise vocabulary.TingbokUnavailableError("offline")

    monkeypatch.setattr(additem._vocabulary, "resolve_vocabulary_from_tingbok", fake_resolve)
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="zzz-novel",
        item_id="novel-3",
        name="Novel thing",
        tingbok_url="https://tingbok.test",
    )
    assert any("does not resolve" in w for w in result.warnings)


def test_add_item_no_tingbok_url_stays_offline(inventory_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Without tingbok_url the fallback must not be attempted at all."""

    def boom(labels, url, lang="en", session=None):
        raise AssertionError("tingbok must not be queried when tingbok_url is None")

    monkeypatch.setattr(additem._vocabulary, "resolve_vocabulary_from_tingbok", boom)
    md_path = inventory_dir / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="food1",
        category="zzz-novel",
        item_id="novel-4",
        name="Novel thing",
    )
    assert any("does not resolve" in w for w in result.warnings)


# --- container resolution (regression: groceries written into a tool box) ----

_MD_TEMP = """# Intro

Demo

# Storage

## ID:temp-boxes Temporary boxes

* Assorted junk

#### ID:TC-01 Box TC-01 - Einhell Power X-Change batteries & charger

* category:battery ID:einhell-1 Einhell 4Ah battery

## ID:temp - newly bought, not yet sorted to a proper place

* category:milk ID:milk-1 bb:2026-08 Milk
"""


@pytest.fixture
def temp_inventory(tmp_path: Path) -> Path:
    (tmp_path / "inventory.md").write_text(_MD_TEMP, encoding="utf-8")
    example_vocab = Path(__file__).parent.parent / "example" / "vocabulary.json"
    (tmp_path / "vocabulary.json").write_text(example_vocab.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_add_item_exact_container_beats_prefix_sibling(temp_inventory: Path):
    """`location: temp` must land in ID:temp, not in ID:temp-boxes' last bullet.

    Regression: the substring match hit `## ID:temp-boxes` first; its section
    spans the nested `#### ID:TC-01`, so the bullet was appended inside the
    Einhell tool box. Cornflakes in a battery box.
    """
    md_path = temp_inventory / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="temp",
        category="cereal",
        item_id="cornflakes-1",
        bb="2027-01",
        name="Cornflakes 500g",
        check_bb=False,
    )
    assert not result.errors
    text = md_path.read_text(encoding="utf-8")
    temp_block = text.split("## ID:temp - newly bought")[1]
    assert "ID:cornflakes-1" in temp_block
    # and emphatically NOT in the tool box
    tc01_block = text.split("#### ID:TC-01")[1].split("## ID:temp - newly bought")[0]
    assert "cornflakes" not in tc01_block


def test_add_item_container_match_is_case_insensitive(temp_inventory: Path):
    md_path = temp_inventory / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="tc-01",
        category="battery",
        item_id="einhell-2",
        name="Einhell 2Ah battery",
        check_bb=False,
    )
    assert not result.errors
    text = md_path.read_text(encoding="utf-8")
    tc01_block = text.split("#### ID:TC-01")[1].split("## ID:temp - newly bought")[0]
    assert "ID:einhell-2" in tc01_block


def test_add_item_unknown_container_still_errors(temp_inventory: Path):
    md_path = temp_inventory / "inventory.md"
    result = additem.add_item(
        md_path,
        container_id="no-such-box",
        category="milk",
        item_id="milk-9",
        bb="2026-08",
        name="Milk",
    )
    assert any("not found" in e for e in result.errors)
