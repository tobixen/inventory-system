"""Tests for scripts/find-space-in-series.py — free-slot detection in a numbered ID series."""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "find-space-in-series.py"

# The script's filename is hyphenated (like scripts/migrate-tags.py), so it is not
# importable by name; load it from its path instead.
_spec = importlib.util.spec_from_file_location("find_space_in_series", _SCRIPT)
fsis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fsis)


def taken(ids, prefix):
    """used_numbers() reduced to the set of numbers, for tests not about spellings."""
    return set(fsis.used_numbers(ids, prefix))


class TestContainerIds:
    def test_collects_ids(self):
        inventory = {"containers": [{"id": "C-01"}, {"id": "C-02"}]}
        assert fsis.container_ids(inventory) == ["C-01", "C-02"]

    def test_skips_containers_without_a_usable_id(self):
        # A container with no "id" key used to become a None in the set and blow
        # up the regex with a TypeError; a non-string id did the same later.
        inventory = {"containers": [{"id": "C-01"}, {"name": "no id here"}, {"id": None}, {"id": 7}, {"id": "  "}]}
        assert fsis.container_ids(inventory) == ["C-01"]

    def test_missing_containers_key(self):
        assert fsis.container_ids({}) == []

    def test_json_that_is_not_an_object(self):
        with pytest.raises(ValueError):
            fsis.container_ids([])


class TestUsedNumbers:
    @pytest.mark.parametrize("cid", ["C1", "C-1", "C 1", "C-01", "C_01", "c001", "  C-01  "])
    def test_spelling_variants_all_mean_one(self, cid):
        assert taken([cid], "C") == {1}

    def test_prefix_is_case_insensitive(self):
        assert taken(["c-07"], "C") == {7}
        assert taken(["C-07"], "c") == {7}

    def test_other_series_are_ignored(self):
        assert taken(["A1", "B-02", "Garasje", "Oversikt"], "C") == set()

    def test_longer_prefix_is_not_a_c_container(self):
        # "TC-01" is the toolbox series; a "C" search must not claim it, and a
        # "C" search must not be claimed by it either.
        assert taken(["TC-01"], "C") == set()
        assert taken(["TC-01"], "TC") == {1}

    def test_trailing_text_is_not_a_number_in_the_series(self):
        assert taken(["C-01-shelf", "C-01b"], "C") == set()

    def test_prefix_metacharacters_are_escaped(self):
        assert taken(["C.1"], "C.") == {1}
        assert taken(["CX1"], "C.") == set()

    def test_records_every_spelling_of_a_number(self):
        assert fsis.used_numbers(["A5", "A05"], "A") == {5: {"A5", "A05"}}


class TestFreeNumbers:
    def test_gaps_only(self):
        assert list(fsis.free_numbers({1, 2, 4}, 1, 5)) == [3, 5]

    def test_range_is_inclusive_at_both_ends(self):
        assert list(fsis.free_numbers(set(), 1, 3)) == [1, 2, 3]

    def test_all_taken(self):
        assert list(fsis.free_numbers({1, 2, 3}, 1, 3)) == []

    def test_is_lazy(self):
        # An absurd --max must not allocate the range; taking two values from a
        # 50-million-wide series has to be instant.
        free = fsis.free_numbers(set(), 1, 50_000_000)
        assert [next(free), next(free)] == [1, 2]


class TestFormatId:
    def test_zero_padded_and_uppercased(self):
        assert fsis.format_id("c", 7, 2) == "C-07"

    def test_number_wider_than_the_padding(self):
        assert fsis.format_id("C", 123, 2) == "C-123"


class TestMain:
    def _inventory(self, tmp_path, ids):
        path = tmp_path / "inventory.json"
        path.write_text(json.dumps({"containers": [{"id": i} for i in ids]}), encoding="utf-8")
        return path

    def test_prints_free_ids(self, tmp_path, capsys):
        path = self._inventory(tmp_path, ["C-01", "C-03"])
        assert fsis.main(["C", str(path), "--max", "4"]) == 0
        assert capsys.readouterr().out.split() == ["C-02", "C-04"]

    def test_c10_does_not_make_c01_look_taken(self, tmp_path, capsys):
        # The original script tested each candidate number with its own regex
        # ("[Cc][- ]?0*1" searched in "C-10" hits the leading "C-1"), so an
        # existing C-10 made C-01 look taken.  Extracting the number from the
        # ID instead cannot exhibit that, so no mutation of the current code
        # fails this test — it guards the design, and fires if anyone rewrites
        # it back to per-number matching.
        path = self._inventory(tmp_path, ["C-10"])
        assert fsis.main(["C", str(path), "-n", "1"]) == 0
        assert capsys.readouterr().out.split() == ["C-01"]

    def test_count_limits_the_output(self, tmp_path, capsys):
        path = self._inventory(tmp_path, ["C-01"])
        assert fsis.main(["C", str(path), "--max", "99", "-n", "2"]) == 0
        assert capsys.readouterr().out.split() == ["C-02", "C-03"]

    def test_count_larger_than_the_result_set(self, tmp_path, capsys):
        path = self._inventory(tmp_path, ["C-01"])
        assert fsis.main(["C", str(path), "--max", "3", "-n", "9"]) == 0
        assert capsys.readouterr().out.split() == ["C-02", "C-03"]

    def test_start_skips_the_low_numbers(self, tmp_path, capsys):
        path = self._inventory(tmp_path, [])
        assert fsis.main(["C", str(path), "--start", "5", "--max", "6"]) == 0
        assert capsys.readouterr().out.split() == ["C-05", "C-06"]

    def test_start_zero_offers_number_zero(self, tmp_path, capsys):
        # ~/solveig-inventory has an FM-0, so a series may number from zero.
        path = self._inventory(tmp_path, [])
        assert fsis.main(["FM", str(path), "--start", "0", "--max", "1"]) == 0
        assert capsys.readouterr().out.split() == ["FM-00", "FM-01"]

    def test_max_above_99_widens_the_padding(self, tmp_path, capsys):
        # Documented behaviour: one series' IDs stay sortable as text.
        path = self._inventory(tmp_path, [])
        assert fsis.main(["C", str(path), "--max", "100", "-n", "1"]) == 0
        assert capsys.readouterr().out.split() == ["C-001"]

    def test_collision_is_reported_on_stderr(self, tmp_path, capsys):
        # A5 and A05 are two real boxes in ~/furusetalle9-inventory; zero
        # padding is meant to be insignificant, so that needs relabelling.
        path = self._inventory(tmp_path, ["A5", "A05"])
        assert fsis.main(["A", str(path), "--max", "6", "-n", "1"]) == 0
        captured = capsys.readouterr()
        assert captured.out.split() == ["A-01"]
        assert "A5" in captured.err
        assert "A05" in captured.err

    def test_no_collision_no_warning(self, tmp_path, capsys):
        path = self._inventory(tmp_path, ["A-05"])
        assert fsis.main(["A", str(path), "--max", "6", "-n", "1"]) == 0
        assert capsys.readouterr().err == ""

    def test_no_free_slot_is_an_error(self, tmp_path, capsys):
        path = self._inventory(tmp_path, ["C-01", "C-02"])
        assert fsis.main(["C", str(path), "--max", "2"]) == 1
        assert capsys.readouterr().out == ""

    def test_missing_file_exits_two(self, tmp_path, capsys):
        assert fsis.main(["C", str(tmp_path / "nope.json")]) == 2
        assert "nope.json" in capsys.readouterr().err

    def test_malformed_json_exits_two(self, tmp_path, capsys):
        path = tmp_path / "inventory.json"
        path.write_text("{not json", encoding="utf-8")
        assert fsis.main(["C", str(path)]) == 2
        assert "could not read" in capsys.readouterr().err

    def test_json_that_is_not_an_object_exits_two(self, tmp_path, capsys):
        # Not exit 1 — that is the documented code for "the series is full".
        path = tmp_path / "inventory.json"
        path.write_text("[]", encoding="utf-8")
        assert fsis.main(["C", str(path)]) == 2
        assert "not a JSON object" in capsys.readouterr().err


class TestArgumentChecking:
    """Values that used to be accepted and silently produce wrong output."""

    @pytest.mark.parametrize("bad", [["C", "-n", "0"], ["C", "-n", "-1"], ["C", "--start", "-3"]])
    def test_rejected(self, bad):
        with pytest.raises(SystemExit) as exc:
            fsis.parse_args(bad)
        assert exc.value.code == 2

    def test_max_below_start_is_rejected(self):
        with pytest.raises(SystemExit) as exc:
            fsis.parse_args(["C", "--start", "10", "--max", "5"])
        assert exc.value.code == 2

    def test_empty_prefix_is_rejected(self):
        with pytest.raises(SystemExit) as exc:
            fsis.parse_args([" "])
        assert exc.value.code == 2
