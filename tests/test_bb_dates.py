"""Tests for bb_dates — best-before date extraction from OCR text."""

from inventory_md.bb_dates import extract_best_before, find_dates


class TestFindDates:
    def test_iso(self):
        assert find_dates("Best before 2026-06-12") == ["2026-06-12"]

    def test_dotted_full_european(self):
        # day.month.year — European order
        assert find_dates("05.01.2027") == ["2027-01-05"]

    def test_dashed_full(self):
        assert find_dates("E1 7B0003 28-08-2026") == ["2026-08-28"]

    def test_spaced_full(self):
        assert find_dates("10 02 2028 L D60183 BULGARIA") == ["2028-02-10"]

    def test_two_digit_year(self):
        # 25.07.26 -> 2026-07-25
        assert find_dates("НАЙ-ДОБЪР ДО: 25.07.26") == ["2026-07-25"]

    def test_month_year_only(self):
        assert find_dates("08.2026") == ["2026-08"]

    def test_day_gt_12_resolves_order(self):
        assert find_dates("25.07.2026") == ["2026-07-25"]

    def test_invalid_dropped(self):
        assert find_dates("99.99.9999") == []
        assert find_dates("lot 4056489 batch 220") == []

    def test_multiple_dates_in_order_deduped(self):
        got = find_dates("prod 01.01.2026 best before 12.06.2026 12.06.2026")
        assert got == ["2026-01-01", "2026-06-12"]


class TestExtractBestBefore:
    def test_keyword_adjacent_wins(self):
        # production date earlier, bb date after the keyword
        text = "Произведено 01.06.2026 НАЙ-ДОБЪР ДО 25.07.2026"
        res = extract_best_before(text)
        assert res["best"] == "2026-07-25"
        assert any(c["near_keyword"] and c["date"] == "2026-07-25" for c in res["candidates"])

    def test_english_best_before(self):
        assert extract_best_before("BEST BEFORE: 2026-12-31")["best"] == "2026-12-31"

    def test_no_keyword_falls_back_to_latest(self):
        res = extract_best_before("01.01.2026 and 12.06.2027")
        assert res["best"] == "2027-06-12"
        assert all(not c["near_keyword"] for c in res["candidates"])

    def test_no_date(self):
        res = extract_best_before("no dates here at all")
        assert res["best"] is None
        assert res["candidates"] == []

    def test_accepts_ocr_blocks(self):
        blocks = [{"text": "НАЙ-ДОБЪР ДО"}, {"text": "25.07.26"}]
        assert extract_best_before(blocks)["best"] == "2026-07-25"
