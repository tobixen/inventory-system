"""Tests for the `inventory-md move` write path (moveitem module)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inventory_md import moveitem

_MD = """# Intro

Demo

# ID:box1 First box

Some text.

* category:rice ID:rice-1 Rice 1kg
* category:pasta ID:pasta-1 Pasta
* category:peel-ply ID:peel-1 Peel ply
  * 83 g/m2 plain
  * 105 g/m2 twill

# ID:box2 Second box

* category:milk ID:milk-1 Milk
"""


# --- find_item_block --------------------------------------------------------


def test_find_item_block_single_bullet():
    lines = _MD.splitlines()
    block = moveitem.find_item_block(lines, "pasta-1")
    assert block is not None
    start, end = block
    assert lines[start] == "* category:pasta ID:pasta-1 Pasta"
    assert end - start == 1  # single line, no children


def test_find_item_block_includes_subbullets():
    lines = _MD.splitlines()
    block = moveitem.find_item_block(lines, "peel-1")
    assert block is not None
    start, end = block
    moved = lines[start:end]
    assert moved[0] == "* category:peel-ply ID:peel-1 Peel ply"
    assert "  * 83 g/m2 plain" in moved
    assert "  * 105 g/m2 twill" in moved
    assert end - start == 3


def test_find_item_block_missing_returns_none():
    lines = _MD.splitlines()
    assert moveitem.find_item_block(lines, "does-not-exist") is None


def test_find_item_block_ignores_container_heading():
    # box1 is a heading ID, not an item bullet — must not be matched as an item.
    lines = _MD.splitlines()
    assert moveitem.find_item_block(lines, "box1") is None


def test_find_item_block_exact_id_no_prefix_match():
    # "rice-1" must not be matched when searching for "rice".
    lines = _MD.splitlines()
    assert moveitem.find_item_block(lines, "rice") is None


# --- move_item end to end ---------------------------------------------------


@pytest.fixture
def md_path(tmp_path: Path) -> Path:
    p = tmp_path / "inventory.md"
    p.write_text(_MD, encoding="utf-8")
    return p


def test_move_item_relocates_line(md_path: Path):
    result = moveitem.move_item(md_path, item_id="pasta-1", container_id="box2")
    assert not result.errors
    assert result.written
    text = md_path.read_text(encoding="utf-8")
    box1_block, box2_block = text.split("# ID:box2")
    # removed from box1
    assert "pasta-1" not in box1_block
    # present in box2
    assert "pasta-1" in box2_block
    # the exact original line content is preserved
    assert "* category:pasta ID:pasta-1 Pasta" in box2_block


def test_move_item_moves_subbullets_together(md_path: Path):
    result = moveitem.move_item(md_path, item_id="peel-1", container_id="box2")
    assert not result.errors
    text = md_path.read_text(encoding="utf-8")
    box1_block, box2_block = text.split("# ID:box2")
    assert "peel-1" not in box1_block
    assert "83 g/m2 plain" not in box1_block
    assert "83 g/m2 plain" in box2_block
    assert "105 g/m2 twill" in box2_block


def test_move_item_unknown_item_errors_file_unchanged(md_path: Path):
    result = moveitem.move_item(md_path, item_id="nope-1", container_id="box2")
    assert result.errors
    assert not result.written
    assert md_path.read_text(encoding="utf-8") == _MD


def test_move_item_unknown_container_errors_file_unchanged(md_path: Path):
    result = moveitem.move_item(md_path, item_id="pasta-1", container_id="nowhere")
    assert result.errors
    assert not result.written
    assert md_path.read_text(encoding="utf-8") == _MD


def test_move_item_dry_run_leaves_file(md_path: Path):
    result = moveitem.move_item(md_path, item_id="pasta-1", container_id="box2", dry_run=True)
    assert not result.errors
    assert not result.written
    assert result.item_line == "* category:pasta ID:pasta-1 Pasta"
    assert md_path.read_text(encoding="utf-8") == _MD


def test_move_item_reports_source_container(md_path: Path):
    result = moveitem.move_item(md_path, item_id="pasta-1", container_id="box2")
    assert result.from_container == "box1"
