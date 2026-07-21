"""Tests for the `inventory-md edit` write path (edititem module)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inventory_md import edititem

_MD = """# Intro

Demo

# ID:box1 First box

* category:rice ID:rice-1 EAN:7038010000000 bb:2027-01 qty:2 Rice 1kg
* category:peel-ply ID:peel-1 Peel ply
  * 83 g/m2 plain
  * 105 g/m2 twill
* category:milk ID:milk-1 bb:2026-07 Whole milk

# ID:box2 Second box

* category:hammer ID:hammer-1 A hammer
"""


# --- rewrite_item_line ------------------------------------------------------


def test_rewrite_replaces_existing_field_in_place():
    line = "* category:rice ID:rice-1 EAN:7038010000000 bb:2027-01 qty:2 Rice 1kg"
    out = edititem.rewrite_item_line(line, {"ean": "1234567890123"})
    assert out == "* category:rice ID:rice-1 EAN:1234567890123 bb:2027-01 qty:2 Rice 1kg"


def test_rewrite_inserts_missing_field_in_canonical_position():
    line = "* category:rice ID:rice-1 EAN:7038010000000 qty:2 Rice 1kg"
    out = edititem.rewrite_item_line(line, {"bb": "2027-01"})
    # bb sits between EAN and qty, and the name stays last
    assert out == "* category:rice ID:rice-1 EAN:7038010000000 bb:2027-01 qty:2 Rice 1kg"


def test_rewrite_appends_field_after_last_when_none_follow():
    line = "* category:rice ID:rice-1 Rice 1kg"
    out = edititem.rewrite_item_line(line, {"price": "EUR:1.29/pcs"})
    assert out == "* category:rice ID:rice-1 price:EUR:1.29/pcs Rice 1kg"


def test_rewrite_removes_field_with_empty_value():
    line = "* category:rice ID:rice-1 EAN:7038010000000 qty:2 Rice 1kg"
    out = edititem.rewrite_item_line(line, {"qty": None})
    assert out == "* category:rice ID:rice-1 EAN:7038010000000 Rice 1kg"


def test_rewrite_removing_absent_field_is_a_noop():
    line = "* category:rice ID:rice-1 Rice 1kg"
    assert edititem.rewrite_item_line(line, {"qty": None}) == line


def test_rewrite_preserves_indentation_and_bullet_marker():
    line = "  - category:rice ID:rice-1 Rice 1kg"
    out = edititem.rewrite_item_line(line, {"qty": "3"})
    assert out.startswith("  - category:rice ID:rice-1 qty:3 ")


def test_rewrite_name_replaces_trailing_text_only():
    line = "* category:rice ID:rice-1 qty:2 Rice 1kg"
    out = edititem.rewrite_item_line(line, {}, name="Basmati rice")
    assert out == "* category:rice ID:rice-1 qty:2 Basmati rice"


def test_rewrite_tags_replace_the_whole_set():
    line = "* category:drill ID:drill-1 tag:condition:used tag:owner:tb EAN:123 A drill"
    out = edititem.rewrite_item_line(line, {}, tags=["condition:new"])
    assert out == "* category:drill ID:drill-1 tag:condition:new EAN:123 A drill"


def test_rewrite_leaves_other_fields_byte_identical():
    line = "* category:rice ID:rice-1 EAN:7038010000000 bb:2027-01 price:EUR:1.29/pcs Rice 1kg (top shelf)"
    out = edititem.rewrite_item_line(line, {"bb": "2028-02"})
    assert out.replace("2028-02", "2027-01") == line


def test_rewrite_does_not_touch_colon_tokens_in_the_name():
    # A second ID: inside the description is free text, not a field (same rule as
    # the parser); editing must not rewrite or consume it.
    line = "* category:tracker ID:gps-1 EAN:123 GPS tracker (IMEI:490154, ID:280425160522)"
    out = edititem.rewrite_item_line(line, {"ean": "999"})
    assert "ID:280425160522" in out
    assert "ID:gps-1" in out
    assert "EAN:999" in out


# --- edit_item end to end ---------------------------------------------------


@pytest.fixture
def inventory_dir(tmp_path: Path) -> Path:
    (tmp_path / "inventory.md").write_text(_MD, encoding="utf-8")
    example_vocab = Path(__file__).parent.parent / "example" / "vocabulary.json"
    (tmp_path / "vocabulary.json").write_text(example_vocab.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


@pytest.fixture
def md_path(inventory_dir: Path) -> Path:
    return inventory_dir / "inventory.md"


def test_edit_item_updates_ean(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", ean="1234567890128")
    assert not result.errors
    assert result.written
    assert "EAN:1234567890128" in md_path.read_text(encoding="utf-8")
    assert result.before != result.after


def test_edit_item_reports_before_and_after(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", qty="5")
    assert result.before == "* category:rice ID:rice-1 EAN:7038010000000 bb:2027-01 qty:2 Rice 1kg"
    assert result.after == "* category:rice ID:rice-1 EAN:7038010000000 bb:2027-01 qty:5 Rice 1kg"
    assert result.container == "box1"


def test_edit_item_dry_run_leaves_file(md_path: Path):
    before = md_path.read_text(encoding="utf-8")
    result = edititem.edit_item(md_path, item_id="rice-1", qty="5", dry_run=True)
    assert not result.errors
    assert not result.written
    assert result.after != result.before
    assert md_path.read_text(encoding="utf-8") == before


def test_edit_item_preserves_subbullets(md_path: Path):
    result = edititem.edit_item(md_path, item_id="peel-1", mass="500g", check_bb=False)
    assert not result.errors
    text = md_path.read_text(encoding="utf-8")
    assert "  * 83 g/m2 plain" in text
    assert "  * 105 g/m2 twill" in text
    assert "mass:500g" in text


def test_edit_item_unknown_id_errors(md_path: Path):
    before = md_path.read_text(encoding="utf-8")
    result = edititem.edit_item(md_path, item_id="nope-1", qty="5")
    assert result.errors
    assert not result.written
    assert md_path.read_text(encoding="utf-8") == before


def test_edit_item_ambiguous_id_errors(tmp_path: Path):
    md = tmp_path / "inventory.md"
    md.write_text(
        "# ID:box1 Box\n\n* category:rice ID:dup Rice\n* category:pasta ID:dup Pasta\n",
        encoding="utf-8",
    )
    before = md.read_text(encoding="utf-8")
    result = edititem.edit_item(md, item_id="dup", qty="5", check_bb=False)
    assert result.errors
    assert "more than once" in result.errors[0] or "2" in result.errors[0]
    assert not result.written
    assert md.read_text(encoding="utf-8") == before


def test_edit_item_container_heading_id_is_not_an_item(md_path: Path):
    result = edititem.edit_item(md_path, item_id="box1", qty="5")
    assert result.errors
    assert not result.written


def test_edit_item_no_changes_requested_errors(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1")
    assert result.errors
    assert not result.written


def test_edit_item_bb_est_suffix(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", bb="2027-02:EST")
    assert not result.errors
    assert "bb:2027-02:EST" in md_path.read_text(encoding="utf-8")


def test_edit_item_bb_est_flag(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", bb="2027-02", bb_est=True)
    assert not result.errors
    assert "bb:2027-02:EST" in md_path.read_text(encoding="utf-8")


def test_edit_item_bb_est_conflict_errors(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", bb="2027-02:EST", bb_est=False)
    assert result.errors
    assert not result.written


def test_edit_item_est_flag_alone_marks_existing_bb(md_path: Path):
    # The repair case: a date already on the line was a guess, not a printed date.
    result = edititem.edit_item(md_path, item_id="milk-1", bb_est=True)
    assert not result.errors
    assert "bb:2026-07:EST" in md_path.read_text(encoding="utf-8")


def test_edit_item_no_est_flag_alone_clears_marker(md_path: Path):
    edititem.edit_item(md_path, item_id="milk-1", bb_est=True)
    result = edititem.edit_item(md_path, item_id="milk-1", bb_est=False)
    assert not result.errors
    text = md_path.read_text(encoding="utf-8")
    assert "bb:2026-07 " in text
    assert ":EST" not in text


def test_edit_item_est_flag_without_any_bb_errors(md_path: Path):
    result = edititem.edit_item(md_path, item_id="peel-1", bb_est=True)
    assert result.errors
    assert not result.written


def test_edit_item_invalid_bb_format_errors(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", bb="soon")
    assert result.errors
    assert not result.written


def test_edit_item_removing_bb_from_food_errors(md_path: Path):
    result = edititem.edit_item(md_path, item_id="milk-1", bb="")
    assert result.errors
    assert not result.written


def test_edit_item_removing_bb_from_food_allowed_with_flag(md_path: Path):
    result = edititem.edit_item(md_path, item_id="milk-1", bb="", check_bb=False)
    assert not result.errors
    assert "bb:" not in result.after


def test_edit_item_unknown_category_warns(md_path: Path):
    result = edititem.edit_item(md_path, item_id="peel-1", category="zzz-unknown-thing", check_bb=False)
    assert not result.errors
    assert result.warnings
    assert result.written


def test_edit_item_unknown_category_strict_errors(md_path: Path):
    result = edititem.edit_item(md_path, item_id="peel-1", category="zzz-unknown-thing", strict=True, check_bb=False)
    assert result.errors
    assert not result.written


def test_edit_item_name_change(md_path: Path):
    result = edititem.edit_item(md_path, item_id="rice-1", name="Basmati rice 1kg")
    assert not result.errors
    assert result.after.endswith("Basmati rice 1kg")
    assert "EAN:7038010000000" in result.after


def test_edit_item_tags_replace(md_path: Path):
    result = edititem.edit_item(md_path, item_id="peel-1", tags=["condition:new"], check_bb=False)
    assert not result.errors
    assert "tag:condition:new" in md_path.read_text(encoding="utf-8")


def test_edit_item_missing_file_errors(tmp_path: Path):
    result = edititem.edit_item(tmp_path / "nope.md", item_id="rice-1", qty="1")
    assert result.errors
    assert not result.written


def test_edit_item_keeps_the_rest_of_the_file_intact(md_path: Path):
    before = md_path.read_text(encoding="utf-8")
    edititem.edit_item(md_path, item_id="rice-1", qty="9")
    after = md_path.read_text(encoding="utf-8")
    assert len(after.splitlines()) == len(before.splitlines())
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert len(changed) == 1
