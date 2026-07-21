"""Tests for shopping_context (read-only situational-awareness helper)."""

import sys
from pathlib import Path

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0] + "/scripts")
from shopping_context import (  # noqa: E402
    find_staging_files,
    grep_diary_lines,
    match_shop_osm,
    read_diary_text,
    recent_ledger_rows,
    shop_of,
    shop_osm_candidates,
)


class TestMatchShopOsm:
    CACHE = {
        "Billa Varna": {"osm_type": "WAY", "osm_id": 1016681733},
        "Lidl Varna": {"osm_type": "WAY", "osm_id": 235500005},
    }

    def test_exact(self):
        assert match_shop_osm(self.CACHE, "Lidl Varna")["osm_id"] == 235500005

    def test_case_insensitive_substring(self):
        # One Lidl cached → a bare "lidl" still resolves unambiguously.
        assert match_shop_osm(self.CACHE, "lidl")["osm_id"] == 235500005

    def test_no_match(self):
        assert match_shop_osm(self.CACHE, "Praktiker Varna") is None

    def test_ambiguous_substring_refuses_to_guess(self):
        # Two branches of the same chain: a bare "lidl" must NOT silently pick one.
        cache = {
            "Lidl Varna Вл. Варненчик": {"osm_type": "WAY", "osm_id": 235500005},
            "Lidl Varna Цар Освободител": {"osm_type": "WAY", "osm_id": 999999999},
        }
        assert match_shop_osm(cache, "lidl") is None
        assert match_shop_osm(cache, "lidl varna") is None
        # …but the exact branch name still resolves.
        assert match_shop_osm(cache, "Lidl Varna Цар Освободител")["osm_id"] == 999999999

    def test_candidates_lists_all_matches(self):
        cache = {
            "Lidl Varna Вл. Варненчик": {"osm_type": "WAY", "osm_id": 235500005},
            "Lidl Varna Цар Освободител": {"osm_type": "WAY", "osm_id": 999999999},
            "Billa Varna": {"osm_type": "WAY", "osm_id": 1016681733},
        }
        assert sorted(shop_osm_candidates(cache, "lidl")) == [
            "Lidl Varna Вл. Варненчик",
            "Lidl Varna Цар Освободител",
        ]


class TestStagingFiles:
    def _make(self, tmp_path: Path):
        d = tmp_path / "staging"
        d.mkdir()
        (d / "shopping-2026-06-13-praktiker.yaml").write_text("shop: Praktiker Varna\n")
        (d / "shopping-2026-06-16.yaml").write_text("shop: Lidl Varna\n")
        (d / "shopping-2026-06-18-praktiker.yaml").write_text("shop: Praktiker Varna\n")
        (d / "off-products-2026-06-16.yaml").write_text("products: []\n")
        return d

    def test_shop_of_reads_field(self, tmp_path):
        d = self._make(tmp_path)
        assert shop_of(d / "shopping-2026-06-16.yaml") == "Lidl Varna"

    def test_filters_by_shop_newest_first(self, tmp_path):
        d = self._make(tmp_path)
        files = find_staging_files(d, "praktiker", limit=5)
        names = [f.name for f in files]
        assert names == [
            "shopping-2026-06-18-praktiker.yaml",
            "shopping-2026-06-13-praktiker.yaml",
        ]

    def test_limit_respected(self, tmp_path):
        d = self._make(tmp_path)
        assert len(find_staging_files(d, "praktiker", limit=1)) == 1

    def test_no_shop_returns_all_shopping(self, tmp_path):
        d = self._make(tmp_path)
        files = find_staging_files(d, None, limit=10)
        # off-products-* is not a shopping file
        assert all(f.name.startswith("shopping-") for f in files)
        assert len(files) == 3


class TestGrepDiary:
    DIARY = """\
* EUR 19.75 - maintenance - Praktiker Varna (paint brushes)
* EUR 28.32 - food - Lidl Varna (groceries)
* EUR 25.50 - maintenance - Praktiker Varna (thinner, scissors)
"""

    def test_matches_shop_lines(self):
        lines = grep_diary_lines(self.DIARY, "Praktiker")
        assert len(lines) == 2
        assert all("Praktiker" in line for line in lines)

    def test_case_insensitive(self):
        assert len(grep_diary_lines(self.DIARY, "lidl")) == 1

    def test_empty_when_no_match(self):
        assert grep_diary_lines(self.DIARY, "Decathlon") == []


class TestRecentLedgerRows:
    LEDGER = "\n".join(
        [
            '{"date": "2026-06-13", "shop": "Praktiker Varna", "receipt_name": "THINNER", "total": 4.99, "currency": "EUR", "ean": "3800045022060"}',
            '{"date": "2026-06-18", "shop": "Lidl Varna", "receipt_name": "MLYAKO", "total": 1.43, "currency": "EUR", "ean": "4056489108160"}',
            "",  # blank lines are skipped
            '{"date": "2026-06-19", "shop": "Praktiker Varna", "receipt_name": "SOUDAL", "total": 9.99, "currency": "EUR", "ean": null}',
            "not json — tolerated and skipped",
        ]
    )

    def test_filters_by_shop_and_keeps_newest(self):
        rows = recent_ledger_rows(self.LEDGER, "praktiker", limit=10)
        assert [r["receipt_name"] for r in rows] == ["THINNER", "SOUDAL"]

    def test_limit_keeps_the_last_n(self):
        rows = recent_ledger_rows(self.LEDGER, "praktiker", limit=1)
        assert [r["receipt_name"] for r in rows] == ["SOUDAL"]

    def test_no_match_is_empty(self):
        assert recent_ledger_rows(self.LEDGER, "Decathlon", limit=10) == []


class TestReadDiaryText:
    """--diary may be a file or a directory (diary-md keeps diary-YYYY.md files)."""

    def test_plain_file(self, tmp_path):
        f = tmp_path / "diary-2026.md"
        f.write_text("* EUR 1.00 - groceries - Lidl Varna\n", encoding="utf-8")
        assert "Lidl Varna" in read_diary_text(f)

    def test_directory_discovers_diary_file(self, tmp_path):
        (tmp_path / "diary-2026.md").write_text("* EUR 2.00 - groceries - Lidl Varna\n", encoding="utf-8")
        assert "Lidl Varna" in read_diary_text(tmp_path)

    def test_directory_prefers_newest_year(self, tmp_path):
        (tmp_path / "diary-2025.md").write_text("old\n", encoding="utf-8")
        (tmp_path / "diary-2026.md").write_text("new\n", encoding="utf-8")
        assert "new" in read_diary_text(tmp_path)

    def test_directory_without_diary_files_raises(self, tmp_path):
        import pytest

        with pytest.raises(OSError):
            read_diary_text(tmp_path)
