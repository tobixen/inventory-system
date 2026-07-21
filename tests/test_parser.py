"""Tests for parser module."""

import pytest

from inventory_md import parser


class TestParseInventoryMarkdownItPy:
    """Tests for the markdown-it-py based parser."""

    def test_parse_simple_container(self, tmp_path):
        """Test parsing a simple container with items."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:box1 Storage Box

Description of the box

* Item one
* Item two
""")
        result = parser.parse_inventory(md_file)

        assert len(result["containers"]) == 1
        container = result["containers"][0]
        assert container["id"] == "box1"
        assert container["heading"] == "Storage Box"
        assert "Description of the box" in container["description"]
        assert len(container["items"]) == 2

    def test_parse_nested_hierarchy(self, tmp_path):
        """Test parsing nested container hierarchy."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:garage Garage

## ID:shelf1 Shelf 1

* Item on shelf

### ID:box1 Box on Shelf

* Item in box
""")
        result = parser.parse_inventory(md_file)

        assert len(result["containers"]) == 3

        # Find containers by ID
        containers = {c["id"]: c for c in result["containers"]}

        assert "garage" in containers
        assert "shelf1" in containers
        assert "box1" in containers

        # Check parent relationships
        assert containers["garage"]["parent"] is None
        assert containers["shelf1"]["parent"] == "garage"
        assert containers["box1"]["parent"] == "shelf1"

    def test_parse_item_metadata(self, tmp_path):
        """Test parsing items with metadata tags."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:box1 Box

* tag:tools,hardware Screwdriver set
* ID:wrench My wrench
""")
        result = parser.parse_inventory(md_file)

        container = result["containers"][0]
        assert len(container["items"]) == 2

        # First item has tags
        assert container["items"][0]["metadata"].get("tags") == ["tools", "hardware"]
        assert container["items"][0]["name"] == "Screwdriver set"

        # Second item has ID
        assert container["items"][1]["metadata"].get("id") == "wrench"
        assert container["items"][1]["name"] == "My wrench"

    def test_parse_intro_section(self, tmp_path):
        """Test that Intro section is extracted."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# Intro

This is the introduction.

# ID:box1 Box

* item
""")
        result = parser.parse_inventory(md_file)

        assert result["intro"] == "This is the introduction."
        assert len(result["containers"]) == 1

    def test_structural_wrapper_section_not_a_container(self, tmp_path):
        """Sections without ID are structural wrappers - not containers, but their subsections are."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# Storage overview

## ID:box1 Box 1

* item1

## ID:box2 Box 2

* item2
""")
        result = parser.parse_inventory(md_file)

        container_ids = [c["id"] for c in result["containers"]]
        assert "box1" in container_ids
        assert "box2" in container_ids
        # The wrapper itself is not a container
        assert "Storage-overview" not in container_ids
        assert len(result["containers"]) == 2

    def test_structural_wrapper_items_are_found(self, tmp_path):
        """Items inside containers under a structural wrapper section are found."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# Attic storage

## ID:A1 Box A1

* category:electronics USB cable
* category:electronics USB charger

## ID:A2 Box A2

* category:tools Hammer
""")
        result = parser.parse_inventory(md_file)

        all_items = [item for c in result["containers"] for item in c["items"]]
        item_names = [i["name"] for i in all_items]
        assert "USB cable" in item_names
        assert "USB charger" in item_names
        assert "Hammer" in item_names

    def test_items_under_id_less_subheading_attach_to_container(self, tmp_path):
        """ID-less sub-headings are human-readable grouping, not sub-containers.

        Their items must attach to the enclosing container rather than being
        silently dropped.
        """
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# Inventory

### ID:C-04 Box C-04 - Children's books

Clear plastic box.

#### English children's books

* category:book ID:book-a "A"
* category:book ID:book-b "B"

#### Norwegian children's books

* category:book ID:book-c "C"
""")
        result = parser.parse_inventory(md_file)

        containers = {c["id"]: c for c in result["containers"]}
        # The ID-less sub-headings must not become containers
        assert list(containers) == ["C-04"]
        item_ids = [i["id"] for i in containers["C-04"]["items"]]
        assert item_ids == ["book-a", "book-b", "book-c"]

    def test_items_under_nested_id_less_subheadings_attach_to_nearest_container(self, tmp_path):
        """Items attach to the nearest ID-bearing ancestor, across several ID-less levels."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""## ID:C-09 Junk box

### Electronics/Networking

* category:power-connector ID:adapter-delta Delta AC adapter

#### Alarms and sensors

* category:gas-alarm ID:alarm-gas Gas detector
""")
        result = parser.parse_inventory(md_file)

        containers = {c["id"]: c for c in result["containers"]}
        assert list(containers) == ["C-09"]
        item_ids = [i["id"] for i in containers["C-09"]["items"]]
        assert item_ids == ["adapter-delta", "alarm-gas"]

    def test_configurable_intro_section_name(self, tmp_path):
        """Intro section name is configurable via config dict."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# Preface

Custom intro text.

# ID:box1 Box

* item
""")
        config = {"sections": {"intro": "Preface", "numbering_scheme": "Numbering"}}
        result = parser.parse_inventory(md_file, config=config)

        assert result["intro"] == "Custom intro text."
        assert len(result["containers"]) == 1

    def test_default_intro_section_name(self, tmp_path):
        """Default intro section name is 'Intro'."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# Intro

Default intro text.

# ID:box1 Box

* item
""")
        result = parser.parse_inventory(md_file)

        assert result["intro"] == "Default intro text."

    def test_parse_indented_items(self, tmp_path):
        """Test parsing indented (nested) items."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:box1 Box

* Main item
  * Nested item 1
  * Nested item 2
""")
        result = parser.parse_inventory(md_file)

        container = result["containers"][0]
        assert len(container["items"]) == 3
        assert container["items"][0]["indented"] is False
        assert container["items"][1]["indented"] is True
        assert container["items"][2]["indented"] is True

    def test_parse_deeply_nested_items(self, tmp_path):
        """Nesting deeper than one level must not be dropped (issue: aft-cabin overview)."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""### ID:aft-cabin Aft cabin

* ID:sb Starboard side
  * ID:sb1 Storage behind artwork
  * ID:sb2 Wardrobe storage
    * ID:sb3 Top shelf
    * ID:sb4 Upper shelf
""")
        result = parser.parse_inventory(md_file)

        container = result["containers"][0]
        item_ids = [i["id"] for i in container["items"]]
        assert item_ids == ["sb", "sb1", "sb2", "sb3", "sb4"]
        # everything below the top-level bullet is indented
        assert container["items"][0]["indented"] is False
        assert all(i["indented"] is True for i in container["items"][1:])

    def test_parse_item_categories(self, tmp_path):
        """Test parsing items with category metadata."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:box1 Box

* category:food/vegetables/potatoes Potatoes from garden
* category:tools/hand-tools Hammer
""")
        result = parser.parse_inventory(md_file)

        container = result["containers"][0]
        assert len(container["items"]) == 2

        # Categories are stored as-is (no normalization)
        assert container["items"][0]["metadata"].get("categories") == ["food/vegetables/potatoes"]
        assert container["items"][0]["name"] == "Potatoes from garden"

        assert container["items"][1]["metadata"].get("categories") == ["tools/hand-tools"]
        assert container["items"][1]["name"] == "Hammer"

    def test_parse_item_multiple_categories(self, tmp_path):
        """Test parsing items with multiple categories."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:box1 Box

* category:food/vegetables,food/staples Potatoes
""")
        result = parser.parse_inventory(md_file)

        container = result["containers"][0]
        # Categories are stored as-is (no normalization)
        assert container["items"][0]["metadata"].get("categories") == ["food/vegetables", "food/staples"]

    def test_parse_item_with_category_and_tag(self, tmp_path):
        """Test parsing items with both category and tag metadata."""
        md_file = tmp_path / "inventory.md"
        md_file.write_text("""# ID:box1 Box

* category:food/vegetables tag:condition:new,packaging:glass Organic potatoes
""")
        result = parser.parse_inventory(md_file)

        container = result["containers"][0]
        item = container["items"][0]

        # Categories are stored as-is (no normalization)
        assert item["metadata"].get("categories") == ["food/vegetables"]
        assert item["metadata"].get("tags") == ["condition:new", "packaging:glass"]
        assert item["name"] == "Organic potatoes"


class TestExtractMetadata:
    """Tests for extract_metadata function."""

    def test_extract_simple_category(self):
        """Test extracting a simple category."""
        result = parser.extract_metadata("category:food/vegetables Potatoes")
        # Categories are stored as-is (no normalization)
        assert result["metadata"].get("categories") == ["food/vegetables"]
        assert result["name"] == "Potatoes"

    def test_extract_multiple_categories(self):
        """Test extracting multiple categories."""
        result = parser.extract_metadata("category:food/vegetables,food/staples Potatoes")
        # Categories are stored as-is (no normalization)
        assert result["metadata"].get("categories") == ["food/vegetables", "food/staples"]
        assert result["name"] == "Potatoes"

    def test_extract_category_and_tag(self):
        """Test extracting both category and tag."""
        result = parser.extract_metadata("category:tools/hand-tools tag:condition:new Hammer")
        # Categories are stored as-is (no normalization)
        assert result["metadata"].get("categories") == ["tools/hand-tools"]
        assert result["metadata"].get("tags") == ["condition:new"]
        assert result["name"] == "Hammer"

    def test_extract_category_with_id(self):
        """Test extracting category with ID."""
        result = parser.extract_metadata("ID:item1 category:food/vegetables Potatoes")
        assert result["metadata"].get("id") == "item1"
        # Categories are stored as-is (no normalization)
        assert result["metadata"].get("categories") == ["food/vegetables"]
        assert result["name"] == "Potatoes"

    def test_extract_no_category(self):
        """Test extracting without category."""
        result = parser.extract_metadata("tag:tools Hammer")
        assert result["metadata"].get("categories") is None
        assert result["metadata"].get("tags") == ["tools"]
        assert result["name"] == "Hammer"

    def test_first_id_wins_when_line_has_two(self):
        """A second ID: in the free-text description must not override the item's ID.

        Real case: a GPS tracker line carrying a device id in its description
        (``ID:280425160522``) was parsed under that id instead of the leading
        ``ID:gps-tracker-fl1``, truncating the name at the second token.
        """
        result = parser.extract_metadata(
            "category:gps-tracker ID:gps-tracker-fl1 GPS tracker (black, IMEI:355228042516052, ID:280425160522)"
        )
        assert result["metadata"].get("id") == "gps-tracker-fl1"
        # the stray second ID: stays in the name rather than being consumed
        assert "ID:280425160522" in result["name"]
        assert "GPS tracker" in result["name"]

    def test_multiple_categories_across_tokens_still_accumulate(self):
        """First-wins must not apply to repeatable keys (category/tag)."""
        result = parser.extract_metadata("category:canning category:pate Fish pâté")
        assert result["metadata"].get("categories") == ["canning", "pate"]
        assert result["name"] == "Fish pâté"


class TestExtractMetadataTypedFields:
    """Tests for typed field parsing in extract_metadata."""

    def test_qty_parsed_as_float(self):
        result = parser.extract_metadata("qty:3 Spaghetti")
        assert result["metadata"]["qty"] == 3.0
        assert isinstance(result["metadata"]["qty"], float)

    def test_qty_fractional(self):
        result = parser.extract_metadata("qty:0.5 Pasta (opened)")
        assert result["metadata"]["qty"] == 0.5

    def test_mass_kg_normalized_to_grams(self):
        result = parser.extract_metadata("mass:1.5kg Pasta")
        assert result["metadata"]["mass_g"] == 1500.0
        assert "mass" not in result["metadata"]

    def test_mass_g_stored_as_float(self):
        result = parser.extract_metadata("mass:500g Pasta")
        assert result["metadata"]["mass_g"] == 500.0

    def test_volume_ml_normalized_to_liters(self):
        result = parser.extract_metadata("volume:500ml Juice")
        assert result["metadata"]["volume_l"] == pytest.approx(0.5)
        assert "volume" not in result["metadata"]

    def test_volume_l_stored_as_float(self):
        result = parser.extract_metadata("volume:1.5l Juice")
        assert result["metadata"]["volume_l"] == 1.5

    def test_volume_cl_normalized_to_liters(self):
        result = parser.extract_metadata("volume:33cl Beer")
        assert result["metadata"]["volume_l"] == pytest.approx(0.33)

    def test_bb_full_date_unchanged(self):
        result = parser.extract_metadata("bb:2026-03-15 Pasta")
        assert result["metadata"]["bb"] == "2026-03-15"

    def test_bb_year_month_extended_to_last_day(self):
        result = parser.extract_metadata("bb:2026-03 Pasta")
        assert result["metadata"]["bb"] == "2026-03-31"

    def test_bb_year_only_extended_to_dec_31(self):
        result = parser.extract_metadata("bb:2026 Pasta")
        assert result["metadata"]["bb"] == "2026-12-31"

    def test_bb_feb_last_day_non_leap(self):
        result = parser.extract_metadata("bb:2025-02 Pasta")
        assert result["metadata"]["bb"] == "2025-02-28"

    def test_bb_feb_last_day_leap_year(self):
        result = parser.extract_metadata("bb:2024-02 Pasta")
        assert result["metadata"]["bb"] == "2024-02-29"

    def test_bb_est_flag_sets_bb_inferred(self):
        result = parser.extract_metadata("bb:2026-03 EST Pasta")
        assert result["metadata"]["bb"] == "2026-03-31"
        assert result["metadata"]["bb_inferred"] is True
        assert "EST" not in result["name"]

    def test_bb_without_est_has_no_bb_inferred(self):
        result = parser.extract_metadata("bb:2026-03 Pasta")
        assert "bb_inferred" not in result["metadata"]

    def test_name_cleaned_of_typed_fields(self):
        result = parser.extract_metadata("category:pasta qty:2 mass:500g bb:2026-03 EST Spaghetti")
        assert result["name"] == "Spaghetti"
        assert "EST" not in result["name"]


class TestExtractMetadataKeyWhitelist:
    """Unknown keys must not be swallowed as metadata."""

    def test_url_not_parsed_as_key(self):
        result = parser.extract_metadata("category:clothing Some shirt https://example.com/shirt")
        assert "https" not in result["metadata"]
        assert "https://example.com/shirt" in result["name"]

    def test_time_not_parsed_as_key(self):
        result = parser.extract_metadata("category:food Pasta ready in 12:30 min")
        assert "12" not in result["metadata"]
        assert "12:30" in result["name"]

    def test_known_key_still_extracted(self):
        result = parser.extract_metadata("EAN:1234567890123 category:food Pasta")
        assert result["metadata"].get("ean") == "1234567890123"


class TestFindContainerSection:
    """find_container_section(lines, container_id) -> (start, end, level) | None"""

    LINES = [
        "# Box A ID:A1\n",
        "\n",
        "* Hammer\n",
        "## Shelf ID:S1\n",
        "* Nails\n",
        "## Shelf2 ID:S2\n",
        "* Bolts\n",
        "# Box B ID:B1\n",
        "* Wrench\n",
    ]

    def test_level1_found(self):
        result = parser.find_container_section(self.LINES, "A1")
        assert result is not None
        start, end, level = result
        assert start == 0
        assert level == "#"
        assert end == 7  # stops at "# Box B"

    def test_level2_found(self):
        result = parser.find_container_section(self.LINES, "S1")
        assert result is not None
        start, end, level = result
        assert start == 3
        assert level == "##"
        assert end == 5  # stops at next ## heading

    def test_not_found_returns_none(self):
        assert parser.find_container_section(self.LINES, "NOPE") is None

    def test_last_container_end_is_eof(self):
        result = parser.find_container_section(self.LINES, "B1")
        assert result is not None
        _, end, _ = result
        assert end == len(self.LINES)

    def test_level1_end_stops_at_level1_not_level2(self):
        result = parser.find_container_section(self.LINES, "A1")
        _, end, _ = result
        assert end == 7  # ## headings at 3 and 5 are inside A1; only # at 7 ends it

    # Nested (### and deeper) sub-containers, e.g. pantry-fridge under a ## area.
    LINES3 = [
        "# Pantry ID:P1\n",
        "## Fridge area ID:FA\n",
        "### Fridge ID:pantry-fridge\n",
        "* Milk\n",
        "### Freezer ID:freezer\n",
        "* Peas\n",
        "## Other ID:O1\n",
        "* Thing\n",
    ]

    def test_level3_found(self):
        result = parser.find_container_section(self.LINES3, "pantry-fridge")
        assert result is not None
        start, end, level = result
        assert start == 2
        assert level == "###"
        assert end == 4  # stops at the next ### heading (Freezer)

    def test_level3_end_stops_at_higher_level(self):
        result = parser.find_container_section(self.LINES3, "freezer")
        assert result is not None
        start, end, level = result
        assert start == 4
        assert level == "###"
        assert end == 6  # stops at the higher-level "## Other"


class TestAddContainerIdPrefixes:
    """add_container_id_prefixes must skip configurable section names."""

    def _write(self, tmp_path, content: str):
        f = tmp_path / "inventory.md"
        f.write_text(content)
        return f

    def test_skips_default_intro_section(self, tmp_path):
        """Headings inside the default '# Intro' section are not prefixed."""
        md = self._write(
            tmp_path,
            "# Intro\n\n## Box1\n\nSome text\n\n## ID:A1 Storage\n\nItem\n",
        )
        parser.add_container_id_prefixes(md)
        content = md.read_text()
        # Box1 is inside Intro — should not get ID: prefix
        assert "## ID:Box1" not in content
        # A1 was already prefixed — should remain unchanged
        assert "## ID:A1 Storage" in content

    def test_skips_custom_section_name(self, tmp_path):
        """skip_sections overrides the default list."""
        md = self._write(
            tmp_path,
            "# Introduction\n\n## Box2\n\nText\n\n## ID:A1 Storage\n\nItem\n",
        )
        parser.add_container_id_prefixes(md, skip_sections=["Introduction"])
        content = md.read_text()
        assert "## ID:Box2" not in content

    def test_prefixes_heading_outside_skipped_section(self, tmp_path):
        """Headings not in a skipped section do get prefixed."""
        md = self._write(
            tmp_path,
            "# Intro\n\n## Box1\n\nText\n\n# Storage\n\n## Box5\n\n",
        )
        parser.add_container_id_prefixes(md)
        content = md.read_text()
        assert "ID:Box5" in content

    def test_default_skip_includes_nummereringsregime(self, tmp_path):
        """The default skip list includes 'Nummereringsregime'."""
        md = self._write(
            tmp_path,
            "# Nummereringsregime\n\n## B1 Numbering\n\n# Storage\n\n## C1 Container\n\n",
        )
        parser.add_container_id_prefixes(md)
        content = md.read_text()
        assert "## ID:B1" not in content
        assert "## ID:C1" in content


class TestFindContainerSectionExactMatch:
    """An exact ID match must always beat a prefix/substring match.

    Regression: `location: temp` in a staging file resolved to the *earlier*
    heading `## ID:temp-boxes`, whose section spans a whole tree of tool boxes,
    so the new bullet was appended after the last bullet in that span — inside
    `#### ID:TC-01` (Einhell batteries). Groceries ended up in a tool box.
    """

    LINES = [
        "## ID:temp-boxes Temporary boxes\n",
        "* Junk\n",
        "#### ID:TC-01 Box TC-01 - Einhell Power X-Change batteries & charger\n",
        "* category:battery ID:einhell-1 Battery\n",
        "## ID:temp - newly bought, not yet sorted to a proper place\n",
        "* category:milk ID:milk-1 bb:2026-08 Milk\n",
    ]

    def test_exact_id_wins_over_earlier_prefix_match(self):
        result = parser.find_container_section(self.LINES, "temp")
        assert result is not None
        start, end, level = result
        assert start == 4  # the `## ID:temp` heading, NOT `## ID:temp-boxes`
        assert level == "##"
        assert end == len(self.LINES)

    def test_prefixed_id_still_resolves_to_itself(self):
        result = parser.find_container_section(self.LINES, "temp-boxes")
        assert result is not None
        assert result[0] == 0

    def test_exact_match_is_case_insensitive(self):
        result = parser.find_container_section(self.LINES, "tc-01")
        assert result is not None
        assert result[0] == 2

    def test_unique_prefix_match_still_works(self):
        """No exact `temp-b` container, but only one candidate — resolve it."""
        result = parser.find_container_section(self.LINES, "temp-b")
        assert result is not None
        assert result[0] == 0

    def test_ambiguous_prefix_match_raises_and_lists_candidates(self):
        lines = [
            "## ID:food1 Pantry\n",
            "* Pasta\n",
            "## ID:food2 Fridge\n",
            "* Milk\n",
        ]
        with pytest.raises(parser.AmbiguousContainerError) as exc:
            parser.find_container_section(lines, "food")
        message = str(exc.value)
        assert "food1" in message
        assert "food2" in message

    def test_no_match_still_returns_none(self):
        assert parser.find_container_section(self.LINES, "nope") is None
