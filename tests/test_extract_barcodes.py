"""Tests for barcode extraction and ISBN/EAN lookup functionality."""

# Import the module under test
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip all tests in this module if pyzbar is not available
pytest.importorskip("pyzbar", reason="pyzbar not installed")

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0] + "/scripts")
from extract_barcodes import (
    format_for_inventory,
    is_ean,
    is_isbn,
    is_lookupable,
    isbn10_to_isbn13,
    lookup_code,
    lookup_isbn,
    lookup_nb_no,
    normalize_isbn,
    validate_ean_checksum,
    validate_isbn10_checksum,
    validate_isbn13_checksum,
)


class TestNormalizeIsbn:
    """Tests for ISBN normalization."""

    def test_removes_hyphens(self):
        assert normalize_isbn("978-0-13-468599-1") == "9780134685991"

    def test_removes_spaces(self):
        assert normalize_isbn("978 0 13 468599 1") == "9780134685991"

    def test_removes_mixed_separators(self):
        assert normalize_isbn("978-0 13-468599 1") == "9780134685991"

    def test_preserves_digits(self):
        assert normalize_isbn("9780134685991") == "9780134685991"

    def test_preserves_x_checksum(self):
        assert normalize_isbn("0-306-40615-X") == "030640615X"


class TestValidateIsbn10Checksum:
    """Tests for ISBN-10 checksum validation."""

    def test_valid_isbn10(self):
        assert validate_isbn10_checksum("0306406152") is True

    def test_valid_isbn10_with_x(self):
        # 155860832X is a valid ISBN-10 (The C Programming Language)
        assert validate_isbn10_checksum("155860832X") is True

    def test_valid_isbn10_lowercase_x(self):
        # X can be lowercase
        assert validate_isbn10_checksum("155860832x") is True

    def test_invalid_isbn10_wrong_checksum(self):
        assert validate_isbn10_checksum("0306406151") is False

    def test_invalid_isbn10_wrong_length(self):
        assert validate_isbn10_checksum("03064061") is False
        assert validate_isbn10_checksum("03064061521") is False

    def test_invalid_isbn10_non_digits(self):
        assert validate_isbn10_checksum("030640615A") is False


class TestValidateIsbn13Checksum:
    """Tests for ISBN-13 checksum validation."""

    def test_valid_isbn13_978(self):
        assert validate_isbn13_checksum("9780134685991") is True

    def test_valid_isbn13_979(self):
        # 979 prefix ISBNs exist (French publishers, etc.)
        assert validate_isbn13_checksum("9791032305690") is True

    def test_invalid_isbn13_wrong_checksum(self):
        assert validate_isbn13_checksum("9780134685992") is False

    def test_invalid_isbn13_not_978_979(self):
        # Valid EAN-13 but not an ISBN (doesn't start with 978/979)
        assert validate_isbn13_checksum("5901234123457") is False

    def test_invalid_isbn13_wrong_length(self):
        assert validate_isbn13_checksum("978013468599") is False
        assert validate_isbn13_checksum("97801346859912") is False


class TestValidateEanChecksum:
    """Tests for EAN/UPC checksum validation."""

    def test_valid_ean13(self):
        assert validate_ean_checksum("5901234123457") is True

    def test_valid_ean8(self):
        assert validate_ean_checksum("96385074") is True

    def test_valid_upc_a(self):
        assert validate_ean_checksum("012345678905") is True

    def test_invalid_ean13(self):
        assert validate_ean_checksum("5901234123458") is False

    def test_invalid_length(self):
        assert validate_ean_checksum("12345") is False
        assert validate_ean_checksum("12345678901234") is False

    def test_non_digits(self):
        assert validate_ean_checksum("590123412345X") is False


class TestIsIsbn:
    """Tests for ISBN detection."""

    def test_isbn13_with_978(self):
        assert is_isbn("9780134685991") is True

    def test_isbn13_with_979(self):
        assert is_isbn("9791032305690") is True

    def test_isbn13_with_hyphens(self):
        assert is_isbn("978-0-13-468599-1") is True

    def test_isbn10(self):
        assert is_isbn("0306406152") is True

    def test_isbn10_with_x(self):
        assert is_isbn("155860832X") is True

    def test_isbn10_with_hyphens(self):
        assert is_isbn("0-306-40615-2") is True

    def test_regular_ean_not_isbn(self):
        # Valid EAN-13 but not an ISBN
        assert is_isbn("5901234123457") is False

    def test_invalid_checksum_not_isbn(self):
        assert is_isbn("9780134685992") is False

    def test_short_number_not_isbn(self):
        assert is_isbn("12345") is False


class TestIsbn10ToIsbn13:
    """Tests for ISBN-10 to ISBN-13 conversion."""

    def test_converts_correctly(self):
        # 0306406152 should become 9780306406157
        result = isbn10_to_isbn13("0306406152")
        assert result == "9780306406157"
        assert validate_isbn13_checksum(result) is True

    def test_handles_hyphens(self):
        result = isbn10_to_isbn13("0-306-40615-2")
        assert result == "9780306406157"

    def test_returns_input_if_wrong_length(self):
        assert isbn10_to_isbn13("12345") == "12345"


class TestIsLookupable:
    """Tests for barcode lookupability detection."""

    def test_isbn13_detected(self):
        can_lookup, code_type = is_lookupable("EAN13", "9780134685991")
        assert can_lookup is True
        assert code_type == "isbn"

    def test_isbn10_detected(self):
        can_lookup, code_type = is_lookupable("CODE128", "0306406152")
        assert can_lookup is True
        assert code_type == "isbn"

    def test_ean13_detected(self):
        can_lookup, code_type = is_lookupable("EAN13", "5901234123457")
        assert can_lookup is True
        assert code_type == "ean"

    def test_ean8_detected(self):
        can_lookup, code_type = is_lookupable("EAN8", "96385074")
        assert can_lookup is True
        assert code_type == "ean"

    def test_upca_detected(self):
        can_lookup, code_type = is_lookupable("UPCA", "012345678905")
        assert can_lookup is True
        assert code_type == "ean"

    def test_qrcode_not_lookupable(self):
        can_lookup, code_type = is_lookupable("QRCODE", "https://example.com")
        assert can_lookup is False
        assert code_type == ""


class TestIsEan:
    """Tests for is_ean (legacy function)."""

    def test_returns_true_for_isbn(self):
        # is_ean returns True for ISBNs too (they can be looked up)
        assert is_ean("EAN13", "9780134685991") is True

    def test_returns_true_for_ean(self):
        assert is_ean("EAN13", "5901234123457") is True

    def test_returns_false_for_qrcode(self):
        assert is_ean("QRCODE", "https://example.com") is False


class TestLookupCode:
    """Tests for code lookup routing."""

    def test_isbn_routes_to_lookup_isbn(self):
        """Test that ISBNs are routed to lookup_isbn, not tingbok."""
        with (
            patch("extract_barcodes.lookup_isbn") as mock_isbn,
            patch("extract_barcodes.lookup_tingbok") as mock_ean,
        ):
            mock_isbn.return_value = {"name": "Test Book", "type": "book"}

            product, cached = lookup_code("9780134685991", {}, use_cache=False)

            mock_isbn.assert_called_once_with("9780134685991")
            mock_ean.assert_not_called()
            assert product["type"] == "book"

    def test_ean_routes_to_tingbok(self):
        """Test that EANs are routed to tingbok."""
        with (
            patch("extract_barcodes.lookup_isbn") as mock_isbn,
            patch("extract_barcodes.lookup_tingbok") as mock_ean,
        ):
            mock_ean.return_value = {"name": "Test Product", "source": "tingbok"}

            product, cached = lookup_code("5901234123457", {}, use_cache=False)

            mock_ean.assert_called_once_with("5901234123457")
            mock_isbn.assert_not_called()

    def test_cache_hit_returns_cached(self):
        """Test that cache hits return cached data without API call."""
        cache = {"9780134685991": {"name": "Cached Book", "type": "book"}}

        with patch("extract_barcodes.lookup_isbn") as mock_isbn:
            product, cached = lookup_code("9780134685991", cache, use_cache=True)

            mock_isbn.assert_not_called()
            assert cached is True
            assert product["name"] == "Cached Book"

    def test_ean_always_queries_tingbok(self):
        """Test that EANs always query tingbok (no local cache for EANs)."""
        cache = {"5901234123457": None}

        with patch("extract_barcodes.lookup_tingbok") as mock_ean:
            mock_ean.return_value = None
            product, cached = lookup_code("5901234123457", cache, use_cache=True)

            mock_ean.assert_called_once_with("5901234123457")
            assert cached is False
            assert product is None


class TestFormatForInventory:
    """Tests for inventory format output."""

    def test_book_format(self):
        barcode = {"type": "EAN13", "data": "9780134685991"}
        product = {
            "type": "book",
            "isbn": "9780134685991",
            "name": "Test Book",
            "author": "John Doe",
            "publisher": "Publisher Inc",
            "publish_date": "2020",
        }

        result = format_for_inventory(barcode, product)

        assert result.startswith("* tag:book ISBN:9780134685991")
        assert '"Test Book" by John Doe' in result
        assert "(Publisher Inc, 2020)" in result

    def test_book_format_no_author(self):
        barcode = {"type": "EAN13", "data": "9780134685991"}
        product = {
            "type": "book",
            "isbn": "9780134685991",
            "name": "Test Book",
            "author": None,
            "publisher": "Publisher Inc",
        }

        result = format_for_inventory(barcode, product)

        assert '"Test Book"' in result
        assert "by" not in result

    def test_product_format(self):
        barcode = {"type": "EAN13", "data": "5901234123457"}
        product = {
            "name": "Test Product",
            "brand": "Brand X",
            "quantity": "500g",
        }

        result = format_for_inventory(barcode, product)

        assert result == "* EAN:5901234123457 Brand X Test Product (500g)"

    def test_unknown_isbn_format(self):
        barcode = {"type": "EAN13", "data": "9780134685991"}
        product = None

        result = format_for_inventory(barcode, product)

        assert result == "* tag:book ISBN:9780134685991 (unknown book)"

    def test_unknown_ean_format(self):
        barcode = {"type": "EAN13", "data": "5901234123457"}
        product = None

        result = format_for_inventory(barcode, product)

        assert "* EAN:5901234123457 (unknown product" in result


class TestRealWorldIsbns:
    """Tests with real-world ISBN examples."""

    @pytest.mark.parametrize(
        "isbn,expected",
        [
            ("9781846461828", True),  # Ladybird book
            ("9785222394137", True),  # Russian book
            ("978-1-78243-517-4", True),  # With hyphens
            ("0451526538", True),  # ISBN-10: 1984 by Orwell
            ("0-545-01022-5", True),  # ISBN-10 with hyphens: Harry Potter
        ],
    )
    def test_real_isbns_detected(self, isbn, expected):
        assert is_isbn(isbn) is expected

    @pytest.mark.parametrize(
        "ean",
        [
            "7622210678546",  # Freia chocolate
            "5902062007025",  # Welding electrodes
            "4008153752353",  # UNITEC product
        ],
    )
    def test_real_eans_not_isbns(self, ean):
        assert is_isbn(ean) is False
        assert validate_ean_checksum(ean) is True


class TestLookupIsbn:
    """Tests for ISBN lookup with fallback."""

    def test_openlibrary_success_no_fallback(self):
        """When Open Library succeeds, NB.no is not called."""
        with patch("extract_barcodes.lookup_openlibrary") as mock_ol, patch("extract_barcodes.lookup_nb_no") as mock_nb:
            mock_ol.return_value = {"name": "Test Book", "type": "book"}

            result = lookup_isbn("9780134685991")

            mock_ol.assert_called_once()
            mock_nb.assert_not_called()
            assert result["name"] == "Test Book"

    def test_norwegian_isbn_fallback_to_nb(self):
        """Norwegian ISBNs fall back to NB.no when Open Library fails."""
        with patch("extract_barcodes.lookup_openlibrary") as mock_ol, patch("extract_barcodes.lookup_nb_no") as mock_nb:
            mock_ol.return_value = None  # Not found
            mock_nb.return_value = {"name": "Norwegian Book", "type": "book", "source": "nb.no"}

            result = lookup_isbn("9788248936688")  # Norwegian ISBN (978-82-*)

            mock_ol.assert_called_once()
            mock_nb.assert_called_once_with("9788248936688")
            assert result["source"] == "nb.no"

    def test_non_norwegian_isbn_no_nb_fallback(self):
        """Non-Norwegian ISBNs don't fall back to NB.no."""
        with patch("extract_barcodes.lookup_openlibrary") as mock_ol, patch("extract_barcodes.lookup_nb_no") as mock_nb:
            mock_ol.return_value = None  # Not found

            result = lookup_isbn("9780134685991")  # US ISBN

            mock_ol.assert_called_once()
            mock_nb.assert_not_called()
            assert result is None

    def test_norwegian_isbn_prefix_detection(self):
        """Test that 978-82-* prefix correctly triggers NB.no fallback."""
        with patch("extract_barcodes.lookup_openlibrary") as mock_ol, patch("extract_barcodes.lookup_nb_no") as mock_nb:
            mock_ol.return_value = None

            # These should trigger NB.no fallback
            lookup_isbn("9788248936688")
            lookup_isbn("9788205389724")

            assert mock_nb.call_count == 2


class TestLookupNbNo:
    """Tests for Norwegian National Library API lookup."""

    def test_returns_book_type(self):
        """NB.no results should have type='book'."""
        with patch("extract_barcodes.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "_embedded": {
                    "items": [
                        {
                            "metadata": {
                                "title": "Test Book",
                                "creators": ["Author Name"],
                                "originInfo": {"publisher": "Publisher", "issued": "2020"},
                            }
                        }
                    ]
                }
            }

            result = lookup_nb_no("9788248936688")

            assert result["type"] == "book"
            assert result["source"] == "nb.no"
            assert result["name"] == "Test Book"
            assert result["author"] == "Author Name"

    def test_returns_none_for_empty_results(self):
        """NB.no returns None when no items found."""
        with patch("extract_barcodes.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"_embedded": {"items": []}}

            result = lookup_nb_no("9789999999999")

            assert result is None

    def test_handles_multiple_authors(self):
        """NB.no correctly joins multiple authors."""
        with patch("extract_barcodes.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "_embedded": {
                    "items": [
                        {
                            "metadata": {
                                "title": "Collaborative Book",
                                "creators": ["Author One", "Author Two", "Author Three"],
                                "originInfo": {},
                            }
                        }
                    ]
                }
            }

            result = lookup_nb_no("9788248936688")

            assert result["author"] == "Author One, Author Two, Author Three"
            assert len(result["authors"]) == 3


class TestOutOption:
    """--out writes results to a file instead of stdout (so the pipeline needs no
    shell `>` redirect, which breaks Bash-allowlist prefix matching)."""

    def test_out_writes_to_file_not_stdout(self, tmp_path, capsys):
        from extract_barcodes import main

        out_file = tmp_path / "barcodes.json"
        missing = tmp_path / "does-not-exist.jpg"  # no barcode work needed to test plumbing
        argv = ["extract_barcodes.py", "--no-lookup", "--json", "--out", str(out_file), str(missing)]
        with patch.object(sys, "argv", argv):
            main()

        assert out_file.read_text().strip() == "[]"  # JSON payload landed in the file
        assert capsys.readouterr().out == ""  # ... and nothing leaked to stdout


class TestTextQuality:
    """_text_quality scores an OCR pass so extract_text_ocr_oriented can pick the
    orientation. Sideways photos OCR into 1-2 char fragments (score ~0); an
    upright label/receipt scores several points."""

    def test_garbage_fragments_score_zero(self):
        from extract_barcodes import _text_quality

        # The real sideways-OCR signature seen on rotated phone photos.
        garbage = [
            {"text": "1", "confidence": 0.9},
            {"text": "0", "confidence": 0.8},
            {"text": "Il", "confidence": 0.7},
            {"text": "$", "confidence": 0.6},
        ]
        assert _text_quality(garbage) == 0.0

    def test_real_words_accumulate_confidence(self):
        from extract_barcodes import _text_quality

        good = [
            {"text": "Най-добър до", "confidence": 0.9},
            {"text": "2026-12-15", "confidence": 0.8},
            {"text": "x", "confidence": 0.95},  # short token ignored
        ]
        assert _text_quality(good) == pytest.approx(1.7)


class TestExtractTextOcrOriented:
    """extract_text_ocr_oriented retries rotations only when 0° reads as garbage,
    and returns the best-scoring orientation."""

    def test_upright_photo_skips_rotation(self):
        import extract_barcodes

        # A real upright label reads as several confident tokens, clearing accept_score.
        good = [
            {"text": "Дюрум", "confidence": 0.92},
            {"text": "Голям", "confidence": 0.9},
            {"text": "350гр", "confidence": 0.88},
            {"text": "Най-добър до", "confidence": 0.85},
        ]
        calls = []

        def fake(image_path, languages=None, min_confidence=0.3, angles=None):
            calls.append(angles)
            return good  # every orientation "reads" fine

        with patch.object(extract_barcodes, "extract_text_ocr", fake):
            out = extract_barcodes.extract_text_ocr_oriented(Path("x.jpg"))

        assert out == good
        assert calls == [[0]]  # cleared accept_score on first pass; no retries

    def test_rotated_photo_picks_best_orientation(self):
        import extract_barcodes

        by_angle = {
            0: [{"text": "1", "confidence": 0.9}, {"text": "$", "confidence": 0.8}],  # garbage
            90: [{"text": "og", "confidence": 0.5}],  # still poor
            270: [
                {"text": "Най-добър до", "confidence": 0.9},
                {"text": "2026-12-15", "confidence": 0.85},
            ],  # correct orientation
            180: [{"text": "xx", "confidence": 0.9}],
        }
        calls = []

        def fake(image_path, languages=None, min_confidence=0.3, angles=None):
            calls.append(angles[0])
            return by_angle[angles[0]]

        with patch.object(extract_barcodes, "extract_text_ocr", fake):
            out = extract_barcodes.extract_text_ocr_oriented(Path("x.jpg"))

        assert out == by_angle[270]
        assert calls[0] == 0  # tried 0° first
        assert 270 in calls  # ... then rotations


# ---------------------------------------------------------------------------
# Phantom (parity-misdecoded) EAN handling
#
# Regression specimen: one photo of a Dr. Oetker vanilla sugar sachet decoded
# as both 5941132002140 (real) and 2931532002140 (phantom).  The right halves
# are byte-identical and only the left half differs — the signature of an
# EAN-13 parity misdecode, whose checksum is recomputed over the corrupted
# digits and therefore passes.  A valid checksum is not evidence of a correct
# read, so the extractor must corroborate and, failing that, flag.
# ---------------------------------------------------------------------------

import extract_barcodes as eb  # noqa: E402

REAL_EAN = "5941132002140"
PHANTOM_EAN = "2931532002140"

# Second specimen pair, from IMG_20260715_123606.jpg.  Both prefixes are
# plausible (320 France, 380 Bulgaria), and here the *phantom* out-corroborated
# the real code 3-to-2 — which is why corroboration is the last resort and not
# the first.
REAL_SAUSAGE = "3800214928780"
PHANTOM_SAUSAGE = "3200274928780"


class _FakeBarcode:
    """Stand-in for a pyzbar Decoded tuple."""

    def __init__(self, type_: str, data: str):
        self.type = type_
        self.data = data.encode()
        self.polygon = None


class TestIsParityConfusable:
    def test_specimen_pair_is_confusable(self):
        assert eb.is_parity_confusable(REAL_EAN, PHANTOM_EAN) is True

    def test_symmetric(self):
        assert eb.is_parity_confusable(PHANTOM_EAN, REAL_EAN) is True

    def test_identical_codes_are_not_a_conflict(self):
        assert eb.is_parity_confusable(REAL_EAN, REAL_EAN) is False

    def test_unrelated_eans_are_not_confusable(self):
        assert eb.is_parity_confusable(REAL_EAN, "8680041405983") is False

    def test_differing_right_half_is_not_confusable(self):
        # Same left half, different right half — not the parity signature.
        assert eb.is_parity_confusable("5941132002140", "5941132118266") is False

    def test_different_lengths_are_not_confusable(self):
        assert eb.is_parity_confusable(REAL_EAN, "59411320") is False

    def test_ean8_uses_its_own_half(self):
        # EAN-8: last four digits are the right half.
        assert eb.is_parity_confusable("96385074", "12345074") is True
        assert eb.is_parity_confusable("96385074", "96385011") is False


class TestIsRestrictedGs1Prefix:
    """A retail pack never carries a restricted-distribution / coupon prefix.

    Which makes it a free, offline discriminator inside a conflict group, where
    one of the candidates is a misdecode by definition.
    """

    def test_in_store_range_is_restricted(self):
        assert eb.is_restricted_gs1_prefix(PHANTOM_EAN) is True  # 293
        assert eb.is_restricted_gs1_prefix("0294061821517") is True  # 029
        assert eb.is_restricted_gs1_prefix("2000000000009") is True  # 200
        assert eb.is_restricted_gs1_prefix("2999999999995") is True  # 299

    def test_coupon_and_refund_ranges_are_restricted(self):
        assert eb.is_restricted_gs1_prefix("0500000000007") is True  # 050 coupons
        assert eb.is_restricted_gs1_prefix("9800000000002") is True  # 980 refunds
        assert eb.is_restricted_gs1_prefix("0400000000009") is True  # 040

    def test_real_country_prefixes_are_not_restricted(self):
        assert eb.is_restricted_gs1_prefix(REAL_EAN) is False  # 594 Romania
        assert eb.is_restricted_gs1_prefix(REAL_SAUSAGE) is False  # 380 Bulgaria
        assert eb.is_restricted_gs1_prefix(PHANTOM_SAUSAGE) is False  # 320 France
        assert eb.is_restricted_gs1_prefix("7038010000000") is False  # 703 Norway
        assert eb.is_restricted_gs1_prefix("0123456789012") is False  # 012 US/UPC-A

    def test_isbn_and_issn_prefixes_are_not_restricted(self):
        assert eb.is_restricted_gs1_prefix("9780134685991") is False
        assert eb.is_restricted_gs1_prefix("9771234567003") is False

    def test_only_applies_to_ean13(self):
        # Nothing to say about shorter codes; the caller must not use this as a
        # reason to reject them.
        assert eb.is_restricted_gs1_prefix("96385074") is False
        assert eb.is_restricted_gs1_prefix("not-a-number") is False


def _cand(data: str, corroboration: int = 1, type_: str = "EAN13", bbox: tuple | None = None) -> dict:
    return {
        "type": type_,
        "data": data,
        "polygon": None,
        "bbox": bbox,
        "corroboration": corroboration,
        "variants": 3,
    }


class TestBboxOverlapFraction:
    def test_identical_boxes_fully_overlap(self):
        assert eb.bbox_overlap_fraction((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0

    def test_contained_box_fully_overlaps(self):
        # The vanilla-sugar phantom's box sat entirely inside the real read's.
        assert eb.bbox_overlap_fraction((1416, 2820, 2353, 3208), (1875, 2928, 2345, 3184)) == 1.0

    def test_disjoint_boxes_do_not_overlap(self):
        assert eb.bbox_overlap_fraction((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0

    def test_touching_edges_do_not_overlap(self):
        assert eb.bbox_overlap_fraction((0, 0, 10, 10), (10, 0, 20, 10)) == 0.0

    def test_partial_overlap_is_a_fraction(self):
        assert eb.bbox_overlap_fraction((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(0.5)

    def test_missing_box_is_no_evidence(self):
        assert eb.bbox_overlap_fraction(None, (0, 0, 10, 10)) == 0.0

    def test_degenerate_box_is_no_evidence(self):
        assert eb.bbox_overlap_fraction((5, 5, 5, 5), (0, 0, 10, 10)) == 0.0


class TestSpatialGrouping:
    """Reads of the *same physical symbol* land in the same place in the photo.

    That is stronger evidence than any digit-similarity heuristic: on
    IMG_20260715_123606.jpg a third misdecode (3800874988780) shared no right
    half with the real code, so the parity signature missed it — but all three
    boxes covered the same barcode.
    """

    SYMBOL_A = (1660, 468, 2174, 2860)
    SYMBOL_B = (100, 100, 400, 900)

    def test_overlapping_reads_conflict_even_without_the_parity_signature(self):
        out = eb.resolve_candidates(
            [
                _cand(REAL_SAUSAGE, 1, bbox=(1720, 468, 2167, 2845)),
                _cand("3800874988780", 1, bbox=(1668, 480, 1977, 2857)),
            ],
            resolver=lambda e: {"name": "луканка"} if e == REAL_SAUSAGE else None,
        )
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_SAUSAGE]["status"] == "ok"
        assert by_data["3800874988780"]["status"] == "rejected"

    def test_three_reads_of_one_symbol_form_one_group(self):
        out = eb.resolve_candidates(
            [
                _cand(REAL_SAUSAGE, 1, bbox=(1720, 468, 2167, 2845)),
                _cand(PHANTOM_SAUSAGE, 1, bbox=(1697, 470, 2174, 2838)),
                _cand("3800874988780", 1, bbox=(1668, 480, 1977, 2857)),
            ],
            resolver=lambda e: {"name": "луканка"} if e == REAL_SAUSAGE else None,
        )
        by_data = {c["data"]: c["status"] for c in out}
        assert by_data[REAL_SAUSAGE] == "ok"
        assert by_data[PHANTOM_SAUSAGE] == "rejected"
        assert by_data["3800874988780"] == "rejected"

    def test_barcodes_in_different_places_are_not_a_conflict(self):
        """Two flavours of the same brand on one shelf photo differ in a couple
        of digits, but they are two symbols in two places — not a misdecode."""
        out = eb.resolve_candidates(
            [
                _cand("3800214928780", 1, bbox=self.SYMBOL_A),
                _cand("3800214928797", 1, bbox=self.SYMBOL_B),
            ],
            resolver=lambda e: None,
        )
        assert [c["status"] for c in out] == ["ok", "ok"]

    def test_parity_signature_still_groups_when_boxes_are_unknown(self):
        """A code that only decoded in a rescaled variant may have no box."""
        out = eb.resolve_candidates([_cand(REAL_EAN, 1, bbox=None), _cand(PHANTOM_EAN, 1, bbox=None)])
        by_data = {c["data"]: c["status"] for c in out}
        assert by_data[REAL_EAN] == "ok"
        assert by_data[PHANTOM_EAN] == "rejected"


class TestResolveCandidates:
    def test_single_candidate_is_ok(self):
        out = eb.resolve_candidates([_cand(REAL_EAN)])
        assert [c["status"] for c in out] == ["ok"]

    def test_lone_candidate_never_consults_the_resolver(self):
        """Tingbok coverage must not gate a barcode that nothing conflicts with.

        A genuinely new product is absent from tingbok; rejecting it there
        would be worse than the bug being fixed.
        """
        calls = []
        out = eb.resolve_candidates([_cand("8680041405983")], resolver=lambda e: calls.append(e))
        assert calls == []
        assert out[0]["status"] == "ok"

    def test_lone_restricted_prefix_code_is_kept(self):
        """A shop's own in-store code is a legitimate lone read."""
        out = eb.resolve_candidates([_cand("2000123456789")])
        assert out[0]["status"] == "ok"

    def test_restricted_prefix_loses_the_conflict(self):
        out = eb.resolve_candidates([_cand(REAL_EAN, 1), _cand(PHANTOM_EAN, 1)])
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_EAN]["status"] == "ok"
        assert by_data[PHANTOM_EAN]["status"] == "rejected"
        assert PHANTOM_EAN in by_data[REAL_EAN]["discarded"]

    def test_prefix_beats_corroboration(self):
        """Regression: a phantom can out-corroborate the real read."""
        out = eb.resolve_candidates([_cand(REAL_EAN, 1), _cand(PHANTOM_EAN, 3)])
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_EAN]["status"] == "ok"
        assert by_data[PHANTOM_EAN]["status"] == "rejected"

    def test_prefix_decision_needs_no_network(self):
        calls = []
        eb.resolve_candidates([_cand(REAL_EAN, 1), _cand(PHANTOM_EAN, 3)], resolver=lambda e: calls.append(e))
        assert calls == []

    def test_resolver_beats_corroboration(self):
        """Regression, IMG_20260715_123606.jpg: the phantom won 3-to-2.

        Both prefixes are plausible, so only the product database can tell them
        apart — and corroboration must not get to overrule it.
        """
        out = eb.resolve_candidates(
            [_cand(REAL_SAUSAGE, 2), _cand(PHANTOM_SAUSAGE, 3)],
            resolver=lambda e: {"name": "луканка червена ЕКО МЕС"} if e == REAL_SAUSAGE else None,
        )
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_SAUSAGE]["status"] == "ok"
        assert by_data[PHANTOM_SAUSAGE]["status"] == "rejected"

    def test_corroboration_decides_when_nothing_else_can(self):
        out = eb.resolve_candidates(
            [_cand(REAL_SAUSAGE, 3), _cand(PHANTOM_SAUSAGE, 1)],
            resolver=lambda e: None,
        )
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_SAUSAGE]["status"] == "ok"
        assert by_data[PHANTOM_SAUSAGE]["status"] == "rejected"

    def test_a_thin_corroboration_margin_is_not_enough(self):
        """3-to-2 is the margin that got it wrong on real data — don't trust it."""
        out = eb.resolve_candidates(
            [_cand(REAL_SAUSAGE, 2), _cand(PHANTOM_SAUSAGE, 3)],
            resolver=lambda e: None,
        )
        assert sorted(c["status"] for c in out) == ["needs_review", "rejected"]

    def test_unresolvable_tie_is_needs_review(self):
        out = eb.resolve_candidates([_cand(REAL_SAUSAGE, 1), _cand(PHANTOM_SAUSAGE, 1)], resolver=lambda e: None)
        statuses = sorted(c["status"] for c in out)
        # Exactly one representative carries the review flag; the other is
        # reported underneath it rather than as a peer result.
        assert statuses == ["needs_review", "rejected"]
        rep = next(c for c in out if c["status"] == "needs_review")
        assert set(rep["alternatives"]) == {REAL_SAUSAGE, PHANTOM_SAUSAGE}

    def test_both_resolving_is_still_needs_review(self):
        out = eb.resolve_candidates(
            [_cand(REAL_SAUSAGE, 1), _cand(PHANTOM_SAUSAGE, 1)], resolver=lambda e: {"name": "x"}
        )
        assert sorted(c["status"] for c in out) == ["needs_review", "rejected"]

    def test_two_unrelated_barcodes_are_both_ok(self):
        """A shelf photo with two real products must not be flagged."""
        out = eb.resolve_candidates([_cand(REAL_EAN, 3), _cand("8680041405983", 1)], resolver=lambda e: None)
        assert [c["status"] for c in out] == ["ok", "ok"]

    def test_non_ean_barcodes_pass_through(self):
        out = eb.resolve_candidates([_cand("https://example.com", 1, type_="QRCODE"), _cand(REAL_EAN, 1)])
        assert all(c["status"] == "ok" for c in out)

    def test_duplicate_reads_of_one_code_collapse(self):
        out = eb.resolve_candidates([_cand(REAL_EAN, 2), _cand(REAL_EAN, 2)])
        assert all(c["status"] == "ok" for c in out)

    def test_resolution_is_deterministic(self):
        pair = [_cand(REAL_SAUSAGE, 1), _cand(PHANTOM_SAUSAGE, 1)]
        a = eb.resolve_candidates(pair, resolver=lambda e: None)
        b = eb.resolve_candidates(list(reversed(pair)), resolver=lambda e: None)
        rep_a = next(c["data"] for c in a if c["status"] == "needs_review")
        rep_b = next(c["data"] for c in b if c["status"] == "needs_review")
        assert rep_a == rep_b


class TestExtractBarcodesCorroboration:
    @staticmethod
    def _blank(tmp_path: Path) -> Path:
        from PIL import Image as PILImage

        path = tmp_path / "photo.jpg"
        PILImage.new("RGB", (900, 600), "white").save(path)
        return path

    def test_counts_how_many_variants_agree(self, tmp_path):
        path = self._blank(tmp_path)
        seen = []

        def fake_decode(image):
            seen.append(image.size)
            if len(seen) == 1:
                return [_FakeBarcode("EAN13", REAL_EAN), _FakeBarcode("EAN13", PHANTOM_EAN)]
            return [_FakeBarcode("EAN13", REAL_EAN)]

        with patch.object(eb, "decode", fake_decode):
            results = eb.extract_barcodes(path)

        by_data = {r["data"]: r for r in results}
        assert by_data[REAL_EAN]["corroboration"] == len(eb.DECODE_VARIANTS)
        assert by_data[PHANTOM_EAN]["corroboration"] == 1
        assert by_data[REAL_EAN]["variants"] == len(eb.DECODE_VARIANTS)
        assert len(seen) == len(eb.DECODE_VARIANTS)

    def test_variants_are_actually_different_images(self, tmp_path):
        path = self._blank(tmp_path)
        seen = []

        with patch.object(eb, "decode", lambda image: seen.append(image.size) or []):
            eb.extract_barcodes(path)

        assert len(set(seen)) > 1, "rescaling is what makes a second read independent"

    def test_corroborate_false_decodes_once(self, tmp_path):
        path = self._blank(tmp_path)
        seen = []

        def fake_decode(image):
            seen.append(image.size)
            return [_FakeBarcode("EAN13", REAL_EAN)]

        with patch.object(eb, "decode", fake_decode):
            results = eb.extract_barcodes(path, corroborate=False)

        assert len(seen) == 1
        assert results[0]["corroboration"] == 1
        assert results[0]["variants"] == 1

    def test_unreadable_file_returns_empty(self, tmp_path):
        path = tmp_path / "not-an-image.jpg"
        path.write_text("nope", encoding="utf-8")
        assert eb.extract_barcodes(path) == []


class TestUndecodedBarcodeDetection:
    """Second specimen: a torn diving-mask label whose quiet zone is gone.

    zbar returns nothing at all even though the bars are plainly legible.
    We cannot diagnose *which* defect it is, but silence is the worst answer —
    detecting that a barcode-like pattern is present lets the run flag the
    photo instead of dropping it.
    """

    @staticmethod
    def _stripes(path: Path) -> Path:
        from PIL import Image as PILImage
        from PIL import ImageDraw

        img = PILImage.new("L", (400, 300), "white")
        draw = ImageDraw.Draw(img)
        x = 20
        widths = [3, 1, 2, 1, 4, 1, 1, 3, 2, 1, 5, 2, 1, 1, 3, 1, 2, 4, 1, 2] * 4
        for i, w in enumerate(widths):
            if i % 2 == 0:
                draw.rectangle([x, 60, x + w, 240], fill="black")
            x += w + 1
            if x > 380:
                break
        img.save(path)
        return path

    @staticmethod
    def _texty(path: Path) -> Path:
        from PIL import Image as PILImage
        from PIL import ImageDraw

        img = PILImage.new("L", (400, 300), "white")
        draw = ImageDraw.Draw(img)
        # Rows of small blobs: locally busy, but the pattern changes every few
        # rows, unlike the vertically coherent bars of a barcode.
        for row in range(0, 300, 14):
            for col in range(0, 400, 9):
                if (row // 14 + col // 9) % 3:
                    draw.rectangle([col, row, col + 5, row + 8], fill="black")
        img.save(path)
        return path

    def test_detects_a_barcode_like_pattern(self, tmp_path):
        assert eb.looks_like_undecoded_barcode(self._stripes(tmp_path / "bars.png")) is True

    def test_blank_image_is_not_flagged(self, tmp_path):
        from PIL import Image as PILImage

        path = tmp_path / "blank.png"
        PILImage.new("L", (400, 300), "white").save(path)
        assert eb.looks_like_undecoded_barcode(path) is False

    def test_dense_text_is_not_flagged(self, tmp_path):
        assert eb.looks_like_undecoded_barcode(self._texty(tmp_path / "text.png")) is False

    def test_unreadable_file_is_not_flagged(self, tmp_path):
        path = tmp_path / "broken.png"
        path.write_text("nope", encoding="utf-8")
        assert eb.looks_like_undecoded_barcode(path) is False


class TestFormatFlagged:
    def test_needs_review_emits_one_block_not_two_peers(self):
        rep = {
            "type": "EAN13",
            "data": PHANTOM_EAN,
            "status": "needs_review",
            "alternatives": [PHANTOM_EAN, REAL_EAN],
        }
        text = eb.format_flagged(rep)
        assert text.count("\n* ") == 0
        assert text.startswith("* tag:TODO")
        assert PHANTOM_EAN in text
        assert REAL_EAN in text

    def test_undecoded_barcode_block(self):
        text = eb.format_flagged({"type": "NO_DECODE", "data": "", "status": "needs_review"})
        assert text.startswith("* tag:TODO")
        assert "barcode" in text.lower()

    def test_winner_notes_the_discarded_phantom(self):
        barcode = {"type": "EAN13", "data": REAL_EAN, "discarded": [PHANTOM_EAN]}
        text = format_for_inventory(barcode, {"name": "Zahar vanilinat"})
        assert REAL_EAN in text
        assert PHANTOM_EAN in text
        assert "discarded" in text.lower()


class TestReviewFixes:
    """Defects found reviewing v0.15.0 before release."""

    def test_two_real_products_with_overlapping_boxes_are_not_silently_dropped(self):
        """The serious one: grouping by geometry alone deletes a real product.

        A small sticker inside a larger label, or one package lying over
        another, puts two *different* barcodes in overlapping boxes. Treating
        that as one symbol demoted a real second product to a comment.
        Neither code explains the other as a misdecode, so the honest answer is
        a review flag, not a silent pick.
        """
        out = eb.resolve_candidates(
            [
                _cand("5941132002140", 3, bbox=(0, 0, 100, 50)),
                _cand("4006040000006", 1, bbox=(10, 10, 60, 40)),
            ],
            resolver=lambda e: {"name": "a real product"},
        )
        statuses = {c["data"]: c["status"] for c in out}
        assert "ok" not in statuses.values(), statuses
        review = next(c for c in out if c["status"] == "needs_review")
        # Both codes reach the reviewer; neither is picked as the answer.
        assert set(review["alternatives"]) == {"5941132002140", "4006040000006"}

    def test_an_explained_misdecode_is_still_discarded_silently(self):
        """The parity signature explains the loser, so no review flag is needed."""
        out = eb.resolve_candidates(
            [
                _cand(REAL_EAN, 3, bbox=(0, 0, 100, 50)),
                _cand(PHANTOM_EAN, 1, bbox=(10, 10, 60, 40)),
            ]
        )
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_EAN]["status"] == "ok"
        assert by_data[PHANTOM_EAN]["status"] == "rejected"

    def test_unresolvable_loser_on_a_resolved_winner_is_still_discarded(self):
        """The real sausage-label case: a third read sharing no right half.

        It is explained by resolving to nothing while the winner resolves, so
        it stays a discarded read rather than becoming a review flag.
        """
        out = eb.resolve_candidates(
            [
                _cand(REAL_SAUSAGE, 2, bbox=(1720, 468, 2167, 2845)),
                _cand("3800874988780", 3, bbox=(1668, 480, 1977, 2857)),
            ],
            resolver=lambda e: {"name": "луканка"} if e == REAL_SAUSAGE else None,
        )
        by_data = {c["data"]: c for c in out}
        assert by_data[REAL_SAUSAGE]["status"] == "ok"
        assert by_data["3800874988780"]["status"] == "rejected"

    def test_grouping_is_order_independent(self):
        """Single-linkage that only joins the first matching group is order-dependent."""
        wide = _cand("5941132002140", 1, bbox=(0, 0, 100, 10))
        left = _cand("4006040000006", 1, bbox=(0, 0, 40, 10))
        right = _cand("8712100000004", 1, bbox=(60, 0, 100, 10))

        def group_sets(cands):
            groups = eb._confusable_groups(cands)
            return sorted(tuple(sorted(c["data"] for c in g)) for g in groups)

        assert group_sets([wide, left, right]) == group_sets([left, right, wide])
        assert group_sets([wide, left, right]) == group_sets([right, wide, left])

    def test_a_raising_resolver_does_not_abort_the_scan(self):
        """A network blip on photo 40 of 50 used to discard the 39 before it."""

        def boom(_code):
            raise RuntimeError("network down")

        out = eb.resolve_candidates(
            [_cand(REAL_SAUSAGE, 1), _cand(PHANTOM_SAUSAGE, 1)],
            resolver=boom,
        )
        # Unresolvable either way, so it must fall through to a review flag.
        assert sorted(c["status"] for c in out) == ["needs_review", "rejected"]

    def test_corroboration_counts_variants_not_occurrences(self, tmp_path):
        """Two copies of one product in a frame gave '6 of 3 decode passes'."""
        from PIL import Image as PILImage

        path = tmp_path / "two-of-the-same.jpg"
        PILImage.new("RGB", (900, 600), "white").save(path)

        def fake_decode(image):
            # The same code read twice per variant — two packs on the table.
            return [_FakeBarcode("EAN13", REAL_EAN), _FakeBarcode("EAN13", REAL_EAN)]

        with patch.object(eb, "decode", fake_decode):
            results = eb.extract_barcodes(path)

        assert len(results) == 1
        assert results[0]["corroboration"] == len(eb.DECODE_VARIANTS)
        assert results[0]["corroboration"] <= results[0]["variants"]


class TestUpceLookupable:
    def test_genuine_upce_is_accepted(self):
        """UPC-E's check digit covers the expanded UPC-A, not the 8 raw digits."""
        assert eb.is_lookupable("UPCE", "04252614") == (True, "ean")

    def test_corrupted_upce_is_rejected(self):
        assert eb.is_lookupable("UPCE", "04252615")[0] is False
