"""Tests for check_quality food best-before enforcement."""

from unittest.mock import patch

import pytest

from inventory_md import check_quality
from inventory_md.check_quality import (
    DEFAULT_BROAD_CATEGORIES,
    OVERRIDE_BROAD_TAGS,
    _category_is_food,
    _is_food_concept,
    apply_fixes,
    check_broad_categories,
    check_food_without_bb,
    check_shop_specific_eans,
    load_inventory_lang,
    run_all_checks,
)
from inventory_md.check_quality import (
    main as cq_main,
)


class TestBroadCategories:
    @staticmethod
    def _inv(items):
        return {"containers": [{"id": "c1", "items": items}]}

    def test_bare_broad_flagged(self):
        data = self._inv([{"id": "veg-1", "metadata": {"categories": ["vegetables"]}}])
        assert check_broad_categories(data, DEFAULT_BROAD_CATEGORIES)

    def test_food_rooted_broad_path_flagged(self):
        data = self._inv([{"id": "veg-2", "metadata": {"categories": ["food/vegetables"]}}])
        assert check_broad_categories(data, DEFAULT_BROAD_CATEGORIES)

    def test_specific_leaf_ok(self):
        data = self._inv([{"id": "tom", "metadata": {"categories": ["tomatoes"]}}])
        assert check_broad_categories(data, DEFAULT_BROAD_CATEGORIES) == []

    def test_bread_is_specific_enough_ok(self):
        # 'bread' is a usable leaf category, not a too-broad bucket.
        data = self._inv([{"id": "bread-1", "metadata": {"categories": ["bread"]}}])
        assert check_broad_categories(data, DEFAULT_BROAD_CATEGORIES) == []

    def test_nonfood_path_leaf_collision_ok(self):
        # 'hardware/nut' must not be flagged just because 'nut' is a food bucket
        data = self._inv([{"id": "nut-1", "metadata": {"categories": ["hardware/nut"]}}])
        assert check_broad_categories(data, DEFAULT_BROAD_CATEGORIES) == []

    def test_override_tag_exempts(self):
        data = self._inv(
            [{"id": "veg-3", "metadata": {"categories": ["vegetables"], "tags": [OVERRIDE_BROAD_TAGS[0]]}}]
        )
        assert check_broad_categories(data, DEFAULT_BROAD_CATEGORIES) == []


class TestApplyFixes:
    def test_replaces_category_in_md(self, tmp_path):
        md = tmp_path / "inventory.md"
        md.write_text(
            "* category:rice ID:item1 Some rice\n"
            "* category:grain ID:item2 Grain\n"
            "* category:rice-old ID:item3 Not matched\n"  # prefix match must not fire
        )
        count = apply_fixes(tmp_path / "inventory.json", {"rice": "food/grains/rice"})
        assert count == 1
        lines = md.read_text().splitlines()
        assert "category:food/grains/rice" in lines[0]
        assert "category:grain" in lines[1]  # unrelated line unchanged
        assert "category:rice-old" in lines[2]  # prefix not clobbered

    def test_does_not_touch_json(self, tmp_path):
        md = tmp_path / "inventory.md"
        md.write_text("* category:rice ID:r1 Rice\n")
        json_path = tmp_path / "inventory.json"
        original = '{"containers":[],"sentinel":"category:rice"}'
        json_path.write_text(original)
        apply_fixes(json_path, {"rice": "food/grains/rice"})
        assert json_path.read_text() == original  # json untouched

    def test_warns_when_md_missing(self, tmp_path, capsys):
        count = apply_fixes(tmp_path / "inventory.json", {"rice": "food/grains/rice"})
        assert count == 0
        assert "inventory.md" in capsys.readouterr().err


class TestCategoryIsFood:
    @staticmethod
    def _resolve(leaf):
        return {
            "rice": {"id": "rice", "broader": ["food/grains"]},
            "nuts": {"id": "nuts", "broader": ["food/nuts"]},
        }.get(leaf)

    def test_explicit_food_path(self):
        assert _category_is_food("food/spices", self._resolve)

    def test_explicit_hardware_path_not_food(self):
        # leaf 'nuts' resolves to food, but explicit hardware/ root wins
        assert not _category_is_food("hardware/nuts", self._resolve)

    def test_bare_leaf_resolved(self):
        assert _category_is_food("rice", self._resolve)

    def test_bare_unknown_leaf_not_food(self):
        assert not _category_is_food("widget", self._resolve)


class TestIsFoodConcept:
    def test_id_under_food(self):
        assert _is_food_concept({"id": "food/processed_animal_products/cured_meat"})

    def test_broader_under_food(self):
        assert _is_food_concept({"id": "chickpeas", "broader": ["food/legumes"]})

    def test_non_food(self):
        assert not _is_food_concept({"id": "dishwasher_detergent", "broader": ["product/chemical_product/detergent"]})

    def test_no_broader(self):
        assert not _is_food_concept({"id": "epoxy", "broader": []})

    def test_none(self):
        assert not _is_food_concept(None)


# A simple classifier standing in for the tingbok-backed one.
_FOOD = {"rice", "chickpeas", "lentils", "cured-meat", "tomatoes"}


def _is_food(cat: str) -> bool:
    return cat in _FOOD


def _inv(items):
    return {"containers": [{"id": "c1", "items": items}]}


class TestCheckFoodWithoutBB:
    def test_food_without_bb_flagged(self):
        data = _inv(
            [
                {"id": "rice-x", "metadata": {"categories": ["rice"]}},  # no bb
            ]
        )
        issues = check_food_without_bb(data, _is_food)
        assert issues
        assert "1 items" in issues[0]
        assert "rice-x" in issues[0]

    def test_food_with_bb_ok(self):
        data = _inv(
            [
                {"id": "rice-x", "metadata": {"categories": ["rice"], "bb": "2027-01-05"}},
            ]
        )
        assert check_food_without_bb(data, _is_food) == []

    def test_non_food_without_bb_ignored(self):
        data = _inv(
            [
                {"id": "detergent-x", "metadata": {"categories": ["dishwasher-detergent"]}},
                {"id": "epoxy-x", "metadata": {"categories": ["epoxy"]}},
            ]
        )
        assert check_food_without_bb(data, _is_food) == []

    def test_mixed_counts_only_food(self):
        data = _inv(
            [
                {"id": "rice-x", "metadata": {"categories": ["rice"]}},  # food, no bb -> flag
                {"id": "lentils-x", "metadata": {"categories": ["lentils"]}},  # food, no bb -> flag
                {"id": "soap", "metadata": {"categories": ["dishwasher-detergent"]}},  # not food
                {"id": "milk", "metadata": {"categories": ["rice"], "bb": "2026-07"}},  # has bb
            ]
        )
        issues = check_food_without_bb(data, _is_food)
        assert "2 items" in issues[0]


class TestRunAllChecksUsesValidateInventory:
    """run_all_checks must report duplicate IDs and missing parents via parser.validate_inventory."""

    def _data(self, containers):
        return {"containers": containers}

    def test_duplicate_ids_reported_as_error(self):
        data = self._data([{"id": "A"}, {"id": "A"}])
        results, _ = run_all_checks(data, {}, "en", None)
        assert any("A" in e and ("uplicate" in e or "⚠️" in e) for e in results["errors"])

    def test_missing_parent_reported_as_error(self):
        data = self._data([{"id": "A", "parent": "NONEXISTENT"}])
        results, _ = run_all_checks(data, {}, "en", None)
        assert any("NONEXISTENT" in e or "parent" in e.lower() for e in results["errors"])

    def test_no_errors_on_valid_data(self):
        data = self._data([{"id": "A"}, {"id": "B", "parent": "A"}])
        results, _ = run_all_checks(data, {}, "en", None)
        assert results["errors"] == []


class TestLoadInventoryLangUsesConfigFilenames:
    """load_inventory_lang must use CONFIG_FILENAMES; only inventory-md.yaml/json in CWD."""

    def test_reads_lang_from_inventory_md_yaml(self, tmp_path):
        (tmp_path / "inventory-md.yaml").write_text("lang: fr\n")
        inventory = tmp_path / "inventory.json"
        assert load_inventory_lang(inventory) == "fr"

    def test_reads_lang_from_inventory_md_json(self, tmp_path):
        (tmp_path / "inventory-md.json").write_text('{"lang": "de"}')
        inventory = tmp_path / "inventory.json"
        assert load_inventory_lang(inventory) == "de"

    def test_config_yaml_in_cwd_is_ignored(self, tmp_path):
        """config.yaml in CWD must NOT be picked up (avoid collisions)."""
        (tmp_path / "config.yaml").write_text("lang: no\n")
        (tmp_path / "inventory-md.yaml").write_text("lang: en\n")
        inventory = tmp_path / "inventory.json"
        assert load_inventory_lang(inventory) == "en"

    def test_default_en_when_no_config(self, tmp_path):
        inventory = tmp_path / "inventory.json"
        assert load_inventory_lang(inventory) == "en"


class TestArgparse:
    """main() must use argparse — validates that hand-rolled IndexError is gone."""

    def _minimal_inventory(self, tmp_path):
        inv = tmp_path / "inventory.json"
        inv.write_text('{"containers":[]}')
        return inv

    def test_tingbok_url_as_last_arg_raises_systemexit_not_indexerror(self, tmp_path):
        inv = self._minimal_inventory(tmp_path)
        # Previously raised IndexError because args[idx+1] was out of range
        with patch("sys.argv", ["check_quality.py", str(inv), "--tingbok-url"]):
            with pytest.raises(SystemExit) as exc:
                cq_main()
            assert exc.value.code != 0  # argparse error, not success

    def test_no_tingbok_runs_without_network(self, tmp_path):
        inv = self._minimal_inventory(tmp_path)
        with patch("sys.argv", ["check_quality.py", "--no-tingbok", str(inv)]):
            with pytest.raises(SystemExit) as exc:
                cq_main()
            assert exc.value.code == 0  # clean run, no issues

    def test_unknown_flag_raises_systemexit(self, tmp_path):
        inv = self._minimal_inventory(tmp_path)
        with patch("sys.argv", ["check_quality.py", "--bogus-flag", str(inv)]):
            with pytest.raises(SystemExit) as exc:
                cq_main()
            assert exc.value.code != 0


class TestShopSpecificEans:
    def test_bare_instore_code_flagged(self):
        # GS1 restricted range (first digit 2): shop-local, must be prefixed.
        data = _inv([{"id": "lidl-item", "metadata": {"ean": "20241988"}}])
        issues = check_shop_specific_eans(data)
        assert issues
        assert "20241988" in issues[0]
        assert "lidl-item" in issues[0]

    def test_thirteen_digit_instore_code_flagged(self):
        # A 13-digit code in the restricted range is still shop-local.
        data = _inv([{"id": "gloves", "metadata": {"ean": "2007000369012"}}])
        assert check_shop_specific_eans(data)

    def test_biltema_article_number_flagged(self):
        # Biltema catalogue numbers don't start with 2 and aren't a GTIN length.
        data = _inv([{"id": "flag", "metadata": {"ean": "463491"}}])
        issues = check_shop_specific_eans(data)
        assert issues
        assert "463491" in issues[0]

    def test_valid_gtin8_not_starting_with_2_ok(self):
        # A genuine 8-digit GTIN-8 outside the restricted range passes.
        data = _inv([{"id": "widget", "metadata": {"ean": "40001234"}}])
        assert check_shop_specific_eans(data) == []

    def test_shop_prefixed_ok(self):
        data = _inv(
            [
                {"id": "flag", "metadata": {"ean": "biltema-463491"}},
                {"id": "cheese", "metadata": {"ean": "lidl-20241988"}},
            ]
        )
        assert check_shop_specific_eans(data) == []

    def test_normal_gtin_ok(self):
        # Ordinary global GTIN (not in the restricted range) is fine as-is.
        data = _inv([{"id": "epoxy", "metadata": {"ean": "4250153632306"}}])
        assert check_shop_specific_eans(data) == []

    def test_no_ean_ignored(self):
        data = _inv([{"id": "misc", "metadata": {"categories": ["misc"]}}])
        assert check_shop_specific_eans(data) == []


class TestDuplicateConcepts:
    """Concept IDs that differ only in separator or plural form.

    ``cling-film`` and ``clingfilm`` are one thing written two ways.  Which
    spelling is canonical — dashes or underscores, singular or plural — is an
    open question in tingbok's own TODO, so this reports and does not rewrite.
    """

    def _concepts(self, *ids, source="inventory"):
        return {cid: {"id": cid, "prefLabel": cid, "source": source} for cid in ids}

    def test_separator_variants_are_reported(self):
        issues = check_quality.check_duplicate_concepts(self._concepts("bike-clamp", "bike_clamp"))
        assert len(issues) == 1
        assert "bike-clamp" in issues[0]
        assert "bike_clamp" in issues[0]
        assert "separator" in issues[0]

    def test_a_missing_separator_counts(self):
        issues = check_quality.check_duplicate_concepts(self._concepts("cling-film", "clingfilm"))
        assert len(issues) == 1

    def test_plural_variants_are_reported_separately(self):
        issues = check_quality.check_duplicate_concepts(self._concepts("lentil", "lentils"))
        assert len(issues) == 1
        assert "plural" in issues[0]

    def test_both_rules_at_once_give_two_lines(self):
        issues = check_quality.check_duplicate_concepts(self._concepts("bike-clamp", "bike_clamp", "lentil", "lentils"))
        assert len(issues) == 2

    def test_distinct_concepts_are_not_reported(self):
        assert check_quality.check_duplicate_concepts(self._concepts("epoxy", "resin", "hardener")) == []

    def test_the_same_leaf_under_different_paths_is_not_a_duplicate(self):
        """Upstream taxonomies reach one concept by many routes; that is not a typo.

        ``book`` appears under 30 different Wikidata/DBpedia ancestor chains in a
        real vocabulary.  Normalising only the leaf would report every one of them.
        """
        concepts = self._concepts("written_work/book", "product/book", "manifestation/document/book", source="tingbok")
        assert check_quality.check_duplicate_concepts(concepts) == []

    def test_tingbok_sourced_pairs_are_reported_too(self):
        """Both spellings usually come back marked tingbok-sourced.

        ``bike_hardware`` is in tingbok's vocabulary and ``bike-hardware`` is
        not — the inventory wrote the latter, tingbok resolved it on its own, and
        the result is two concepts, both labelled tingbok.  Filtering by source
        would hide 46 of the 65 groups in a real inventory.
        """
        concepts = self._concepts("bike-hardware", "bike_hardware", source="tingbok")
        assert len(check_quality.check_duplicate_concepts(concepts)) == 1

    def test_short_words_are_not_singularised(self):
        """Stripping a trailing s from a three-letter word invents duplicates."""
        assert check_quality.check_duplicate_concepts(self._concepts("gas", "ga")) == []

    def test_a_group_of_three_is_one_group(self):
        issues = check_quality.check_duplicate_concepts(self._concepts("bike-tool", "bike_tool", "biketool"))
        assert len(issues) == 1
        assert "bike-tool + bike_tool + biketool" in issues[0]

    def test_pathed_ids_stay_readable(self):
        """Concept IDs contain "/", so joining a group with "/" is unreadable.

        ``electronics/component/electronics/components`` is two IDs with no
        visible boundary, and this report's only job is to be read.
        """
        issues = check_quality.check_duplicate_concepts(
            self._concepts("electronics/component", "electronics/components")
        )
        assert "electronics/component + electronics/components" in issues[0]

    def test_a_plural_third_spelling_is_not_dropped(self):
        """A concept in a separator pair used to be excluded from plural analysis.

        Given three spellings of one category, the report named two of them and
        never mentioned the third — so the reader "fixes" the report without
        fixing the category.
        """
        issues = check_quality.check_duplicate_concepts(self._concepts("bike-clamp", "bike_clamp", "bike-clamps"))
        joined = " ".join(issues)
        assert "bike-clamps" in joined, joined
        assert "bike-clamp" in joined
        assert "bike_clamp" in joined

    def test_a_long_run_of_groups_is_summarised(self):
        concepts = self._concepts(*[f"thing-{n}" for n in range(20)], *[f"thing_{n}" for n in range(20)])
        issues = check_quality.check_duplicate_concepts(concepts)
        assert len(issues) == 1
        assert "(20)" in issues[0]
        assert "+12 more" in issues[0]

    def test_no_concepts_is_no_issues(self):
        assert check_quality.check_duplicate_concepts({}) == []


class TestFoodClassificationViaAncestors:
    """``_is_food_concept`` only ever looked one ``broader`` level deep."""

    def test_a_direct_food_parent_still_works_without_tingbok(self):
        assert _is_food_concept({"id": "chickpeas", "broader": ["food/legumes"]})

    def test_a_grandparent_needs_the_ancestors_endpoint(self):
        """``soybeans`` → ``legumes`` → ``food/legumes``: two hops, previously missed."""
        concept = {"id": "soybeans", "broader": ["legumes"]}
        assert not _is_food_concept(concept)
        assert _is_food_concept(concept, ancestors_of=lambda cid: ["legumes", "food/legumes", "food"])

    def test_ancestors_saying_no_is_a_no(self):
        concept = {"id": "m8-bolt", "broader": ["fasteners"]}
        assert not _is_food_concept(concept, ancestors_of=lambda cid: ["fasteners", "hardware"])

    def test_an_unreachable_tingbok_leaves_the_shallow_answer(self):
        concept = {"id": "chickpeas", "broader": ["food/legumes"]}
        assert _is_food_concept(concept, ancestors_of=lambda cid: None)

    def test_no_concept_is_not_food(self):
        assert not _is_food_concept(None, ancestors_of=lambda cid: ["food"])
