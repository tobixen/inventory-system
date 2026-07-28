"""Tests for inventory_md.barcodes — the shared barcode-number arithmetic.

These cover the defects found in the pre-v0.15.0 review: a Unicode-digit crash
in the checksum, and shop-local article numbers from *different* shops matching
each other because the bare number was treated as a key on both sides.
"""

from inventory_md import barcodes


class TestValidateEanChecksum:
    def test_valid_codes(self):
        assert barcodes.validate_ean_checksum("5941132002140") is True
        assert barcodes.validate_ean_checksum("012345678905") is True  # UPC-A
        assert barcodes.validate_ean_checksum("96385074") is True  # EAN-8

    def test_invalid_check_digit(self):
        assert barcodes.validate_ean_checksum("5941132002141") is False

    def test_wrong_length(self):
        assert barcodes.validate_ean_checksum("594113200214") is False
        assert barcodes.validate_ean_checksum("") is False

    def test_non_digits(self):
        assert barcodes.validate_ean_checksum("lidl-40853712") is False

    def test_unicode_digits_do_not_crash(self):
        """str.isdigit() accepts superscripts; int() does not.

        `inventory-md ean ²²²²²²²²` used to raise ValueError out of the CLI.
        """
        assert barcodes.validate_ean_checksum("²" * 8) is False
        assert barcodes.validate_ean_checksum("¹²³45678") is False

    def test_other_unicode_numerics_do_not_crash(self):
        # Devanagari digits are isdigit() *and* int()-able, so they must simply
        # fail the check rather than being treated as a valid GTIN.
        assert barcodes.validate_ean_checksum("०" * 8) is False


class TestEanMatches:
    """`ean_matches(stored, query)` — direction matters.

    The shop-name prefix on a shop-local article number exists precisely so two
    chains reusing the same number stay distinguishable, so stripping the prefix
    off *both* sides defeats it.
    """

    def test_exact(self):
        assert barcodes.ean_matches("5941132002140", "5941132002140") is True

    def test_separators_ignored(self):
        assert barcodes.ean_matches("5941132002140", "5941-1320 02140") is True
        assert barcodes.ean_matches("978-0-13-468599-1", "9780134685991") is True

    def test_case_insensitive(self):
        assert barcodes.ean_matches("LIDL-40853712", "lidl-40853712") is True

    def test_bare_query_finds_shop_prefixed_item(self):
        assert barcodes.ean_matches("lidl-40853712", "40853712") is True

    def test_prefixed_query_finds_bare_item(self):
        assert barcodes.ean_matches("40853712", "lidl-40853712") is True

    def test_different_shops_do_not_match(self):
        """The regression: the prefix has to keep disambiguating."""
        assert barcodes.ean_matches("lidl-40853712", "billa-40853712") is False
        assert barcodes.ean_matches("billa-40853712", "lidl-40853712") is False

    def test_unrelated_codes(self):
        assert barcodes.ean_matches("5941132002140", "8680041405983") is False

    def test_empty_never_matches(self):
        assert barcodes.ean_matches("", "5941132002140") is False
        assert barcodes.ean_matches("5941132002140", "") is False
        assert barcodes.ean_matches("", "") is False

    def test_bare_number_does_not_match_a_longer_code_ending_in_it(self):
        assert barcodes.ean_matches("5941132002140", "2002140") is False


class TestUpceExpansion:
    """UPC-E's check digit is computed over the expanded UPC-A, not over itself.

    Validating the 8 raw characters with EAN-8 arithmetic rejected genuine reads.
    """

    def test_known_upce_codes_expand(self):
        # 04252614 -> 042100005264 is the textbook example.
        assert barcodes.expand_upce("04252614") == "042100005264"

    @staticmethod
    def _valid_upce(system: str, body: str) -> str:
        """Build a UPC-E whose check digit is the one its expansion implies."""
        provisional = barcodes.expand_upce(f"{system}{body}0")
        assert provisional is not None
        digits = [int(d) for d in provisional[:-1]]
        total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits))
        return f"{system}{body}{(10 - total % 10) % 10}"

    def test_expansion_covers_every_last_digit_rule(self):
        # One body per branch of the expansion: last digit 0/1/2, 3, 4, and 5-9.
        for body in ("425261", "123453", "123454", "123456", "425260", "425262"):
            upce = self._valid_upce("0", body)
            expanded = barcodes.expand_upce(upce)
            assert expanded is not None, upce
            assert len(expanded) == 12
            assert barcodes.validate_ean_checksum(expanded), f"{upce} -> {expanded}"
            assert barcodes.validate_upce_checksum(upce), upce

    def test_rejects_wrong_shape(self):
        assert barcodes.expand_upce("1234567") is None
        assert barcodes.expand_upce("123456789") is None
        assert barcodes.expand_upce("abcdefgh") is None
        assert barcodes.expand_upce("2" + "1234567") is None  # number system must be 0 or 1

    def test_validate_upce_accepts_a_genuine_code(self):
        assert barcodes.validate_upce_checksum("04252614") is True

    def test_validate_upce_rejects_a_corrupted_code(self):
        assert barcodes.validate_upce_checksum("04252615") is False
