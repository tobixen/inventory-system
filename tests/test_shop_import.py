"""Tests for shop_import.py — builds a human-correctable staging file from a
shopping receipt + barcode-extraction output.

The importer does only mechanical work (parse receipt, classify photos, gather
EAN candidates via an injectable searcher). Matching and best-before reading are
left to a later AI review step that edits the staging file.
"""

import sys

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0] + "/scripts")
from shop_import import (  # noqa: E402
    build_loose_photos,
    build_staging,
    classify_photo_result,
    find_date_candidates,
    parse_lidl_receipt,
    parse_price,
)

LIDL_RECEIPT = {
    "purchase_date": "2026.05.28",
    "store": "Варна – бул. Вл. Варненчик 257",
    "total_price_no_saving": "6,64",
    "items": [
        {"name": "СВЕТЛА БИРА 3,0%", "price": "1,17", "quantity": "1"},
        {"name": "ПРЯСНО МЛЯКО 3,7%", "price": "1,49", "quantity": "1"},
        {"name": "НЕКТАРИНИ НА КГ", "price": "2,79", "quantity": "0,078"},
    ],
}


class TestParsePrice:
    def test_comma_decimal(self):
        assert parse_price("1,17") == 1.17

    def test_dot_decimal(self):
        assert parse_price("1.49") == 1.49

    def test_integer(self):
        assert parse_price("2") == 2.0


class TestParseLidlReceipt:
    def test_session_date_normalized_to_iso(self):
        staging = parse_lidl_receipt(LIDL_RECEIPT)
        assert staging["session"] == "2026-05-28"

    def test_currency_defaults_to_eur(self):
        assert parse_lidl_receipt(LIDL_RECEIPT)["currency"] == "EUR"

    def test_receipt_total_parsed(self):
        assert parse_lidl_receipt(LIDL_RECEIPT)["receipt_total"] == 6.64

    def test_source_recorded(self):
        assert parse_lidl_receipt(LIDL_RECEIPT)["source"] == "lidl_receipts.json"

    def test_one_row_per_item(self):
        assert len(parse_lidl_receipt(LIDL_RECEIPT)["items"]) == 3

    def test_pcs_item_fields(self):
        beer = parse_lidl_receipt(LIDL_RECEIPT)["items"][0]
        assert beer["receipt_name"] == "СВЕТЛА БИРА 3,0%"
        assert beer["price"] == 1.17
        assert beer["qty"] == 1
        assert beer["unit"] == "pcs"
        assert beer["line_total"] == 1.17

    def test_kg_item_detected_and_line_total_is_price_times_qty(self):
        nectarines = parse_lidl_receipt(LIDL_RECEIPT)["items"][2]
        assert nectarines["unit"] == "kg"
        assert nectarines["qty"] == 0.078
        assert nectarines["line_total"] == 0.22  # 2.79 * 0.078 rounded

    def test_rows_have_review_scaffold(self):
        item = parse_lidl_receipt(LIDL_RECEIPT)["items"][0]
        for field in ("ean", "name", "category", "bb", "bb_source", "location", "inventory_id"):
            assert item[field] is None
        assert item["ean_candidates"] == []
        assert item["add_to_inventory"] is True
        assert item["to_tingbok"] is None
        assert item["photos"] == []
        assert item["needs_review"] is True


# A hand-transcribed receipt (no shop JSON API): header keys date/shop/currency/
# total, item rows carrying explicit unit, per-unit price and printed line total.
GENERIC_RECEIPT = {
    "date": "2026-07-08",
    "shop": "Бурлекс Галата",
    "currency": "EUR",
    "total": 49.25,
    "items": [
        {"name": "ДОМАТИ РОЗОВИ", "quantity": 0.506, "unit": "kg", "unit_price": 2.15, "price": 1.09},
        {"name": "ПУРИЧКИ ВАФЛЕНИ ТАГО КАКАО 150Г", "quantity": 1, "unit_price": 1.65, "price": 1.65},
    ],
}


class TestParseGenericReceipt:
    """Regression: a hand-transcribed receipt used to get the Lidl header
    (shop 'Lidl Varna', receipt_total 0.0, source 'lidl_receipts.json')."""

    def test_header_comes_from_receipt_keys(self):
        staging = parse_lidl_receipt(GENERIC_RECEIPT, shop="Lidl Varna", source="receipt-2026-07-08-burlex.json")
        assert staging["session"] == "2026-07-08"
        assert staging["shop"] == "Бурлекс Галата"  # receipt overrides the CLI default
        assert staging["receipt_total"] == 49.25
        assert staging["currency"] == "EUR"
        assert staging["source"] == "receipt-2026-07-08-burlex.json"

    def test_weighed_item_honors_explicit_unit_and_unit_price(self):
        row = parse_lidl_receipt(GENERIC_RECEIPT)["items"][0]
        assert row["unit"] == "kg"
        assert row["qty"] == 0.506
        assert row["price"] == 2.15  # per-kg price
        assert row["line_total"] == 1.09  # printed line amount stays authoritative

    def test_pcs_item_with_unit_price(self):
        row = parse_lidl_receipt(GENERIC_RECEIPT)["items"][1]
        assert row["unit"] == "pcs"
        assert row["price"] == 1.65
        assert row["line_total"] == 1.65


class TestFindDateCandidates:
    def test_iso_date(self):
        assert "2026-06-12" in find_date_candidates("Best before 2026-06-12")

    def test_dotted_full_date(self):
        assert "2026-06-12" in find_date_candidates("12.06.2026")

    def test_month_year_only(self):
        assert "2026-08" in find_date_candidates("08.2026")

    def test_no_date(self):
        assert find_date_candidates("no dates here") == []


class TestClassifyPhotoResult:
    def test_barcode_photo(self):
        result = {
            "file": "/p/IMG_1.jpg",
            "type": "EAN13",
            "data": "4056489080510",
            "product": {"name": "Pilos Fresh Milk 3% 1l"},
        }
        photo = classify_photo_result(result)
        assert photo == {
            "file": "IMG_1.jpg",
            "kind": "barcode",
            "ean": "4056489080510",
            "product": "Pilos Fresh Milk 3% 1l",
        }

    def test_expiry_photo_from_ocr_date(self):
        result = {
            "file": "/p/IMG_2.jpg",
            "type": "OCR",
            "data": "12.06.2026",
            "ocr_results": [{"text": "12.06.2026"}],
            "ocr_title": None,
        }
        photo = classify_photo_result(result)
        assert photo["kind"] == "expiry"
        assert "2026-06-12" in photo["ocr_date_candidates"]

    def test_barcode_photo_surfaces_best_before(self):
        result = {
            "file": "/p/IMG_1.jpg",
            "type": "EAN13",
            "data": "4056489693307",
            "product": {"name": "Lukanka"},
            "best_before": "2026-07-25",
        }
        photo = classify_photo_result(result)
        assert photo["kind"] == "barcode"
        assert photo["bb"] == "2026-07-25"

    def test_label_photo_without_date(self):
        result = {
            "file": "/p/IMG_3.jpg",
            "type": "OCR",
            "data": "Pilos Mlyako",
            "ocr_results": [{"text": "Pilos Mlyako"}],
            "ocr_title": "Pilos Mlyako",
        }
        photo = classify_photo_result(result)
        assert photo["kind"] == "label"
        assert photo["ocr_title"] == "Pilos Mlyako"


class TestBuildLoosePhotos:
    def test_maps_each_result(self):
        results = [
            {"file": "/p/IMG_1.jpg", "type": "EAN13", "data": "4056489080510", "product": None},
            {"file": "/p/IMG_2.jpg", "type": "OCR", "data": "12.06.2026", "ocr_results": [{"text": "12.06.2026"}]},
        ]
        loose = build_loose_photos(results)
        assert [p["kind"] for p in loose] == ["barcode", "expiry"]

    def test_following_expiry_photo_paired_to_barcode(self):
        # A barcode shot with no date, followed by a separate expiry shot:
        # the expiry date should be carried back onto the barcode photo.
        results = [
            {"file": "/p/IMG_1.jpg", "type": "EAN13", "data": "4056489080510", "product": None},
            {"file": "/p/IMG_2.jpg", "type": "OCR", "data": "12.06.2026", "ocr_results": [{"text": "12.06.2026"}]},
        ]
        loose = build_loose_photos(results)
        assert loose[0]["bb"] == "2026-06-12"
        assert loose[0]["bb_from"] == "IMG_2.jpg"

    def test_own_best_before_not_overwritten_by_following(self):
        # A barcode photo that already carries its own bb keeps it and is not
        # re-paired to a following expiry photo.
        results = [
            {
                "file": "/p/IMG_1.jpg",
                "type": "EAN13",
                "data": "4056489080510",
                "product": None,
                "best_before": "2026-07-25",
            },
            {"file": "/p/IMG_2.jpg", "type": "OCR", "data": "12.06.2026", "ocr_results": [{"text": "12.06.2026"}]},
        ]
        loose = build_loose_photos(results)
        assert loose[0]["bb"] == "2026-07-25"
        assert "bb_from" not in loose[0]

    def test_barcode_without_following_expiry_unpaired(self):
        # Two consecutive barcode photos: neither gains a bb.
        results = [
            {"file": "/p/IMG_1.jpg", "type": "EAN13", "data": "4056489080510", "product": None},
            {"file": "/p/IMG_2.jpg", "type": "EAN13", "data": "4056489693307", "product": None},
        ]
        loose = build_loose_photos(results)
        assert "bb" not in loose[0]
        assert "bb" not in loose[1]


def _stub_searcher(receipt_name, shop=None):
    """Pretend tingbok knows the milk receipt name."""
    if "МЛЯКО" in receipt_name:
        return [
            {
                "ean": "4056489080527",
                "name": "Pilos Fresh Milk 3.7% 1l",
                "score": 1.0,
                "matched_name": receipt_name,
                "shop": shop,
            }
        ]
    return []


class TestBuildStaging:
    def test_candidates_populated_from_searcher(self):
        staging = build_staging(LIDL_RECEIPT, shop="Lidl Varna", searcher=_stub_searcher, barcode_results=[])
        milk = staging["items"][1]
        assert milk["ean_candidates"]
        assert milk["ean_candidates"][0]["ean"] == "4056489080527"
        assert milk["ean_candidates"][0]["source"] == "tingbok_receipt_name"

    def test_item_without_candidate_stays_empty(self):
        staging = build_staging(LIDL_RECEIPT, shop="Lidl Varna", searcher=_stub_searcher, barcode_results=[])
        beer = staging["items"][0]
        assert beer["ean_candidates"] == []

    def test_loose_photos_included(self):
        results = [{"file": "/p/IMG_1.jpg", "type": "EAN13", "data": "4056489080510", "product": None}]
        staging = build_staging(LIDL_RECEIPT, shop="Lidl Varna", searcher=_stub_searcher, barcode_results=results)
        assert staging["loose_photos"][0]["file"] == "IMG_1.jpg"

    def test_shop_recorded(self):
        staging = build_staging(LIDL_RECEIPT, shop="Lidl Varna", searcher=_stub_searcher, barcode_results=[])
        assert staging["shop"] == "Lidl Varna"

    def test_candidates_are_not_shop_filtered(self):
        """Candidate recall must not be narrowed by shop (best matches often have no shop)."""

        def shop_strict_searcher(receipt_name, shop=None):
            if shop is not None:
                return []  # would drop everything if the importer filtered by shop
            return _stub_searcher(receipt_name)

        staging = build_staging(LIDL_RECEIPT, shop="Lidl Varna", searcher=shop_strict_searcher, barcode_results=[])
        assert staging["items"][1]["ean_candidates"]  # milk still has a candidate
