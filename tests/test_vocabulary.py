"""Tests for vocabulary module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from inventory_md import vocabulary


class TestConcept:
    """Tests for Concept dataclass."""

    def test_concept_creation(self):
        """Test creating a concept."""
        concept = vocabulary.Concept(
            id="food/vegetables",
            prefLabel="Vegetables",
            altLabels={"en": ["veggies", "greens"]},
            broader=["food"],
            narrower=["food/vegetables/potatoes"],
            source="local",
        )
        assert concept.id == "food/vegetables"
        assert concept.prefLabel == "Vegetables"
        assert concept.altLabels == {"en": ["veggies", "greens"]}

    def test_concept_to_dict(self):
        """Test converting concept to dictionary."""
        concept = vocabulary.Concept(
            id="food/vegetables",
            prefLabel="Vegetables",
            altLabels={"en": ["veggies"]},
            broader=["food"],
            narrower=[],
            source="local",
        )
        d = concept.to_dict()
        assert d["id"] == "food/vegetables"
        assert d["prefLabel"] == "Vegetables"
        assert d["altLabels"] == {"en": ["veggies"]}
        assert d["broader"] == ["food"]
        assert d["source"] == "local"

    def test_concept_from_dict(self):
        """Test creating concept from dictionary."""
        d = {
            "id": "food/vegetables",
            "prefLabel": "Vegetables",
            "altLabels": {"en": ["veggies"]},
            "broader": ["food"],
            "narrower": [],
            "source": "local",
        }
        concept = vocabulary.Concept.from_dict(d)
        assert concept.id == "food/vegetables"
        assert concept.prefLabel == "Vegetables"
        assert concept.altLabels == {"en": ["veggies"]}

    def test_concept_from_dict_backward_compat_list(self):
        """Test creating concept from dictionary with legacy list altLabels."""
        d = {
            "id": "food/vegetables",
            "prefLabel": "Vegetables",
            "altLabels": ["veggies"],
            "broader": ["food"],
        }
        concept = vocabulary.Concept.from_dict(d)
        assert concept.altLabels == {"en": ["veggies"]}

    def test_concept_defaults(self):
        """Test concept with default values."""
        concept = vocabulary.Concept(id="test", prefLabel="Test")
        assert concept.altLabels == {}
        assert concept.broader == []
        assert concept.narrower == []
        assert concept.source == "local"

    def test_get_alt_labels_all(self):
        """Test get_alt_labels returns all labels when lang is None."""
        concept = vocabulary.Concept(
            id="food",
            prefLabel="Food",
            altLabels={"en": ["groceries", "provisions"], "nb": ["mat", "matvarer"]},
        )
        all_alts = concept.get_alt_labels()
        assert all_alts == ["groceries", "provisions", "mat", "matvarer"]

    def test_get_alt_labels_by_language(self):
        """Test get_alt_labels returns only labels for a specific language."""
        concept = vocabulary.Concept(
            id="food",
            prefLabel="Food",
            altLabels={"en": ["groceries"], "nb": ["mat"]},
        )
        assert concept.get_alt_labels("en") == ["groceries"]
        assert concept.get_alt_labels("nb") == ["mat"]
        assert concept.get_alt_labels("de") == []

    def test_get_all_alt_labels_flat_deduplicates(self):
        """Test get_all_alt_labels_flat deduplicates across languages."""
        concept = vocabulary.Concept(
            id="sport",
            prefLabel="Sports",
            altLabels={"en": ["sport", "athletics"], "nb": ["sport", "idrett"]},
        )
        flat = concept.get_all_alt_labels_flat()
        assert flat == ["sport", "athletics", "idrett"]


class TestLoadLocalVocabulary:
    """Tests for load_local_vocabulary function."""

    def test_load_yaml_vocabulary(self, tmp_path):
        """Test loading vocabulary from YAML file."""
        pytest.importorskip("yaml")
        vocab_file = tmp_path / "local-vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  christmas-decorations:
    prefLabel: "Christmas decorations"
    altLabel: ["jul", "xmas"]
    broader: "seasonal"

  tools/hand-tools:
    prefLabel: "Hand tools"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)

        assert "christmas-decorations" in vocab
        assert vocab["christmas-decorations"].prefLabel == "Christmas decorations"
        assert vocab["christmas-decorations"].altLabels == {"en": ["jul", "xmas"]}
        assert vocab["christmas-decorations"].broader == ["seasonal"]

        assert "tools/hand-tools" in vocab
        assert vocab["tools/hand-tools"].prefLabel == "Hand tools"

    def test_load_json_vocabulary(self, tmp_path):
        """Test loading vocabulary from JSON file."""
        vocab_file = tmp_path / "local-vocabulary.json"
        vocab_file.write_text(
            json.dumps(
                {
                    "concepts": {
                        "boat-equipment": {
                            "prefLabel": "Boat equipment",
                            "narrower": ["boat-equipment/safety"],
                        }
                    }
                }
            )
        )
        vocab = vocabulary.load_local_vocabulary(vocab_file)

        assert "boat-equipment" in vocab
        assert vocab["boat-equipment"].prefLabel == "Boat equipment"
        assert vocab["boat-equipment"].narrower == ["boat-equipment/safety"]

    def test_altlabels_roundtrip_through_to_dict(self, tmp_path):
        """altLabels written by Concept.to_dict (key 'altLabels') must load back.

        Regression: the JSON serializer writes the plural "altLabels" while the
        loader only read the singular "altLabel", so altLabels in generated
        vocabulary.json were silently dropped — breaking synonym-based category
        resolution.  A to_dict → load round-trip must preserve them.
        """
        original = vocabulary.Concept(
            id="food/vegetables",
            prefLabel="Vegetables",
            altLabels={"en": ["vegetable", "veggies"]},
        )
        vocab_file = tmp_path / "vocabulary.json"
        vocab_file.write_text(json.dumps({"concepts": {"food/vegetables": original.to_dict()}}))

        loaded = vocabulary.load_local_vocabulary(vocab_file)
        assert loaded["food/vegetables"].altLabels == {"en": ["vegetable", "veggies"]}
        assert "vegetable" in loaded["food/vegetables"].get_all_alt_labels_flat()

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from nonexistent file returns empty dict."""
        vocab_file = tmp_path / "nonexistent.yaml"
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab == {}

    def test_load_with_string_altlabel(self, tmp_path):
        """Test loading with altLabel as single string."""
        pytest.importorskip("yaml")
        vocab_file = tmp_path / "vocab.yaml"
        vocab_file.write_text("""
concepts:
  potatoes:
    prefLabel: "Potatoes"
    altLabel: "spuds"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab["potatoes"].altLabels == {"en": ["spuds"]}

    def test_load_with_string_broader(self, tmp_path):
        """Test loading with broader as single string."""
        pytest.importorskip("yaml")
        vocab_file = tmp_path / "vocab.yaml"
        vocab_file.write_text("""
concepts:
  potatoes:
    prefLabel: "Potatoes"
    broader: "vegetables"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab["potatoes"].broader == ["vegetables"]

    def test_load_with_language_tagged_altlabels(self, tmp_path):
        """Test loading vocabulary with language-tagged dict altLabels."""
        pytest.importorskip("yaml")
        vocab_file = tmp_path / "vocab.yaml"
        vocab_file.write_text("""
concepts:
  food:
    prefLabel: "Food"
    altLabel:
      en: ["groceries", "provisions"]
      nb: ["mat", "matvarer"]
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab["food"].altLabels == {"en": ["groceries", "provisions"], "nb": ["mat", "matvarer"]}

    def test_load_backward_compat_flat_altlabels(self, tmp_path):
        """Test that flat list altLabels are wrapped as en."""
        pytest.importorskip("yaml")
        vocab_file = tmp_path / "vocab.yaml"
        vocab_file.write_text("""
concepts:
  tools:
    prefLabel: "Tools"
    altLabel: ["equipment", "implements"]
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab["tools"].altLabels == {"en": ["equipment", "implements"]}

    def test_load_dict_altlabel_string_values(self, tmp_path):
        """Test that dict altLabels with string values are wrapped in lists."""
        pytest.importorskip("yaml")
        vocab_file = tmp_path / "vocab.yaml"
        vocab_file.write_text("""
concepts:
  food:
    prefLabel: "Food"
    altLabel:
      en: "groceries"
      nb: "mat"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab["food"].altLabels == {"en": ["groceries"], "nb": ["mat"]}


class TestLookupConcept:
    """Tests for lookup_concept function."""

    def test_lookup_by_id(self):
        """Test looking up concept by ID."""
        vocab = {
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
            )
        }
        concept = vocabulary.lookup_concept("food/vegetables", vocab)
        assert concept is not None
        assert concept.id == "food/vegetables"

    def test_lookup_by_preflabel(self):
        """Test looking up concept by prefLabel."""
        vocab = {
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
            )
        }
        concept = vocabulary.lookup_concept("vegetables", vocab)
        assert concept is not None
        assert concept.id == "food/vegetables"

    def test_lookup_by_altlabel(self):
        """Test looking up concept by altLabel."""
        vocab = {
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
                altLabels={"en": ["veggies", "greens"]},
            )
        }
        concept = vocabulary.lookup_concept("veggies", vocab)
        assert concept is not None
        assert concept.id == "food/vegetables"

    def test_lookup_case_insensitive(self):
        """Test that lookup is case-insensitive."""
        vocab = {
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
            )
        }
        concept = vocabulary.lookup_concept("VEGETABLES", vocab)
        assert concept is not None
        assert concept.id == "food/vegetables"

    def test_lookup_not_found(self):
        """Test lookup returns None when not found."""
        vocab = {}
        concept = vocabulary.lookup_concept("nonexistent", vocab)
        assert concept is None


class TestBuildCategoryTree:
    """Tests for build_category_tree function."""

    def test_build_simple_tree(self):
        """Test building a simple category tree."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "food" in tree.roots
        assert "tools" in tree.roots
        assert len(tree.roots) == 2

    def test_description_and_wikipedia_preserved(self):
        """build_category_tree must preserve description and wikipediaUrl."""
        vocab = {
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
            "tools/hammer": vocabulary.Concept(
                id="tools/hammer",
                prefLabel="Hammer",
                broader=["tools"],
                source="local",
                uri="http://dbpedia.org/resource/Hammer",
                description="A tool for driving nails.",
                wikipediaUrl="https://en.wikipedia.org/wiki/Hammer",
            ),
        }
        tree = vocabulary.build_category_tree(vocab)
        hammer = tree.concepts["tools/hammer"]
        assert hammer.description == "A tool for driving nails."
        assert hammer.wikipediaUrl == "https://en.wikipedia.org/wiki/Hammer"

    def test_infer_hierarchy_from_paths(self):
        """Test inferring hierarchy from path separators."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/vegetables": vocabulary.Concept(id="food/vegetables", prefLabel="Vegetables"),
            "food/vegetables/potatoes": vocabulary.Concept(id="food/vegetables/potatoes", prefLabel="Potatoes"),
        }
        tree = vocabulary.build_category_tree(vocab, infer_hierarchy=True)

        # Only "food" should be root
        assert tree.roots == ["food"]

        # Check hierarchy is inferred
        assert tree.concepts["food/vegetables"].broader == ["food"]
        assert tree.concepts["food/vegetables/potatoes"].broader == ["food/vegetables"]

        # Check narrower is set
        assert "food/vegetables" in tree.concepts["food"].narrower
        assert "food/vegetables/potatoes" in tree.concepts["food/vegetables"].narrower

    def test_self_loop_is_removed(self):
        """A concept listing itself in broader/narrower must not survive in the tree.

        Tingbok serves some concepts (e.g. "lentil") with broader==narrower==[self],
        which made the search.html category tree recurse infinitely.
        """
        vocab = {
            "lentil": vocabulary.Concept(
                id="lentil",
                prefLabel="Lentil",
                broader=["lentil"],
                narrower=["lentil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab, infer_hierarchy=False)

        lentil = tree.concepts["lentil"]
        assert "lentil" not in lentil.narrower
        assert "lentil" not in lentil.broader

    def test_mutual_cycle_is_broken(self):
        """Two concepts referencing each other in narrower must form a DAG.

        Tingbok serves "rope" and "rope/cord" each listing the other in *both*
        broader and narrower, producing a 2-cycle that crashed the UI.
        """
        vocab = {
            "rope": vocabulary.Concept(
                id="rope",
                prefLabel="ropes",
                broader=["rope/cord"],
                narrower=["rope/cord"],
            ),
            "rope/cord": vocabulary.Concept(
                id="rope/cord",
                prefLabel="Rope",
                broader=["rope"],
                narrower=["rope"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab, infer_hierarchy=True)

        # Walking narrower from any node must terminate (no cycle).
        concepts = tree.concepts

        def reachable(start: str) -> set[str]:
            seen: set[str] = set()
            stack = [start]
            while stack:
                cur = stack.pop()
                for child in concepts[cur].narrower:
                    assert child != cur, f"self-loop at {cur}"
                    if child not in seen:
                        seen.add(child)
                        stack.append(child)
            return seen

        # Neither node may be reachable from itself via narrower.
        assert "rope" not in reachable("rope")
        assert "rope/cord" not in reachable("rope/cord")

    def test_explicit_broader_not_overridden(self):
        """Test that explicit broader relationships are not overridden."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
                broader=["other-parent"],  # Explicit broader
            ),
        }
        tree = vocabulary.build_category_tree(vocab, infer_hierarchy=True)

        # Explicit broader should be preserved
        assert tree.concepts["food/vegetables"].broader == ["other-parent"]

    def test_label_index(self):
        """Test that label index is built correctly."""
        vocab = {
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
                altLabels={"en": ["veggies"]},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.label_index.get("vegetables") == "food/vegetables"
        assert tree.label_index.get("veggies") == "food/vegetables"
        assert tree.label_index.get("food/vegetables") == "food/vegetables"

    def test_virtual_root_defines_roots(self):
        """Test that _root.narrower is a whitelist: only listed concepts are roots."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["food", "tools"]),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
            "environmental_design": vocabulary.Concept(id="environmental_design", prefLabel="Environmental design"),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Only the curated roots; external orphan not promoted
        assert tree.roots == ["food", "tools"]
        assert "environmental_design" in tree.concepts  # still in vocabulary, just not a root

    def test_virtual_root_excluded_from_tree(self):
        """Test that _root is removed from concepts after root detection."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["food"]),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "_root" not in tree.concepts
        assert "_root" not in tree.roots

    def test_virtual_root_excluded_from_label_index(self):
        """Test that _root does not appear in the label index."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["food"]),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "_root" not in tree.label_index
        assert "root" not in tree.label_index

    def test_fallback_without_virtual_root(self):
        """Test backward-compatible behavior when _root is absent."""
        vocab = {
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Should be sorted alphabetically by prefLabel
        assert tree.roots == ["food", "tools"]

    def test_virtual_root_skips_missing_children(self):
        """Test that nonexistent narrower entries are ignored."""
        vocab = {
            "_root": vocabulary.Concept(
                id="_root",
                prefLabel="Root",
                narrower=["food", "nonexistent", "tools"],
            ),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.roots == ["food", "tools"]

    def test_virtual_root_excludes_orphans(self):
        """_root whitelist: orphaned concepts must NOT be added to roots."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["food"]),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "verktøy": vocabulary.Concept(id="verktøy", prefLabel="Verktøy"),
            "leker": vocabulary.Concept(id="leker", prefLabel="Leker"),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Only the curated root appears; orphaned external concepts are excluded
        assert tree.roots == ["food"]
        # Concepts are still in the vocabulary (accessible by search), just not roots
        assert "verktøy" in tree.concepts
        assert "leker" in tree.concepts

    def test_virtual_root_whitelist_exact(self):
        """_root.narrower is an exact whitelist — non-listed orphans are excluded."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["tools", "food"]),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
            "zebra": vocabulary.Concept(id="zebra", prefLabel="Zebra"),
            "alpha": vocabulary.Concept(id="alpha", prefLabel="Alpha"),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Only curated roots in their declared order; no orphan promotion
        assert tree.roots == ["tools", "food"]

    def test_reachable_children_not_promoted_to_roots(self):
        """Test that concepts reachable via narrower chains are not orphan roots."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["food"]),
            "food": vocabulary.Concept(id="food", prefLabel="Food", narrower=["fruit"]),
            "fruit": vocabulary.Concept(id="fruit", prefLabel="Fruit", broader=["food"]),
            "orphan": vocabulary.Concept(id="orphan", prefLabel="Orphan"),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Only the curated root; neither reachable children nor orphans are promoted
        assert tree.roots == ["food"]
        assert "fruit" in tree.concepts

    def test_virtual_root_preserves_narrower_order(self):
        """Test that roots appear in _root.narrower order, not alphabetical."""
        vocab = {
            "_root": vocabulary.Concept(
                id="_root",
                prefLabel="Root",
                narrower=["tools", "food", "electronics"],
            ),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
            "electronics": vocabulary.Concept(id="electronics", prefLabel="Electronics"),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Order matches _root.narrower, NOT alphabetical
        assert tree.roots == ["tools", "food", "electronics"]

    def test_source_uris_preserved(self):
        """build_category_tree must preserve source_uris on concepts."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/potatoes": vocabulary.Concept(
                id="food/potatoes",
                prefLabel="Potatoes",
                broader=["food"],
                source="dbpedia",
                uri="http://dbpedia.org/resource/Potato",
                source_uris={
                    "off": "off:en:potatoes",
                    "dbpedia": "http://dbpedia.org/resource/Potato",
                    "wikidata": "http://www.wikidata.org/entity/Q16587531",
                },
            ),
        }
        tree = vocabulary.build_category_tree(vocab)
        potatoes = tree.concepts["food/potatoes"]
        assert potatoes.source_uris == {
            "off": "off:en:potatoes",
            "dbpedia": "http://dbpedia.org/resource/Potato",
            "wikidata": "http://www.wikidata.org/entity/Q16587531",
        }

    def test_source_uris_in_json_output(self, tmp_path):
        """source_uris must appear in vocabulary.json via save_vocabulary_json."""
        vocab = {
            "tools": vocabulary.Concept(id="tools", prefLabel="Tools"),
            "tools/hammer": vocabulary.Concept(
                id="tools/hammer",
                prefLabel="Hammer",
                broader=["tools"],
                source="dbpedia",
                source_uris={
                    "dbpedia": "http://dbpedia.org/resource/Hammer",
                    "wikidata": "http://www.wikidata.org/entity/Q169470",
                },
            ),
        }
        output_path = tmp_path / "vocabulary.json"
        vocabulary.save_vocabulary_json(vocab, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        hammer = data["concepts"]["tools/hammer"]
        assert hammer["source_uris"] == {
            "dbpedia": "http://dbpedia.org/resource/Hammer",
            "wikidata": "http://www.wikidata.org/entity/Q169470",
        }


class TestCategoryBySource:
    """Tests for the dynamic category_by_source virtual node generation."""

    def test_category_by_source_nodes_added(self):
        """build_category_tree must generate category_by_source virtual nodes."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/potatoes": vocabulary.Concept(
                id="food/potatoes",
                prefLabel="Potatoes",
                broader=["food"],
                source_uris={"off": "off:en:potatoes", "wikidata": "http://www.wikidata.org/entity/Q16587531"},
            ),
            "food/cumin": vocabulary.Concept(
                id="food/cumin",
                prefLabel="Cumin",
                broader=["food"],
                source_uris={"agrovoc": "http://aims.fao.org/aos/agrovoc/c_2046"},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "category_by_source" in tree.concepts
        assert "category_by_source/off" in tree.concepts
        assert "category_by_source/wikidata" in tree.concepts
        assert "category_by_source/agrovoc" in tree.concepts

    def test_category_by_source_children(self):
        """Source nodes must list the concepts that have that source."""
        vocab = {
            "food/potatoes": vocabulary.Concept(
                id="food/potatoes",
                prefLabel="Potatoes",
                source_uris={"off": "off:en:potatoes", "wikidata": "http://www.wikidata.org/entity/Q16587531"},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        off_node = tree.concepts["category_by_source/off"]
        assert "food/potatoes" in off_node.narrower
        wikidata_node = tree.concepts["category_by_source/wikidata"]
        assert "food/potatoes" in wikidata_node.narrower

    def test_category_by_source_root_excluded_from_trees_roots(self):
        """category_by_source must not appear as a regular root when _root is used."""
        vocab = {
            "_root": vocabulary.Concept(id="_root", prefLabel="Root", narrower=["food"]),
            "food": vocabulary.Concept(
                id="food",
                prefLabel="Food",
                source_uris={"off": "off:en:food"},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "category_by_source" not in tree.roots
        assert "category_by_source" in tree.concepts

    def test_category_by_source_fallback_roots(self):
        """Without _root, category_by_source appears in roots."""
        vocab = {
            "food": vocabulary.Concept(
                id="food",
                prefLabel="Food",
                source_uris={"off": "off:en:food"},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "category_by_source" in tree.roots

    def test_category_by_source_preflabels(self):
        """Known sources must have human-friendly prefLabels."""
        vocab = {
            "food": vocabulary.Concept(
                id="food",
                prefLabel="Food",
                source_uris={
                    "off": "off:en:food",
                    "agrovoc": "http://aims.fao.org/aos/agrovoc/c_2",
                    "dbpedia": "http://dbpedia.org/resource/Food",
                    "wikidata": "http://www.wikidata.org/entity/Q2",
                    "gpt": "gpt:1234",
                },
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.concepts["category_by_source/off"].prefLabel == "OpenFoodFacts"
        assert tree.concepts["category_by_source/agrovoc"].prefLabel == "AGROVOC"
        assert tree.concepts["category_by_source/dbpedia"].prefLabel == "DBpedia"
        assert tree.concepts["category_by_source/wikidata"].prefLabel == "Wikidata"
        assert tree.concepts["category_by_source/gpt"].prefLabel == "Google Product Taxonomy"

    def test_no_category_by_source_when_no_source_uris(self):
        """No category_by_source nodes when no concept has source_uris."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "category_by_source" not in tree.concepts

    def test_source_paths_creates_intermediate_nodes(self):
        """A concept with source_paths gets proper intermediate nodes in category_by_source."""
        vocab = {
            "food/fruit/bananas": vocabulary.Concept(
                id="food/fruit/bananas",
                prefLabel="Bananas",
                source_uris={"gpt": "gpt:1234"},
                source_paths={"gpt": "food/food_items/fruit/bananas"},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        # Intermediate nodes must exist
        assert "category_by_source/gpt/food" in tree.concepts
        assert "category_by_source/gpt/food/food_items" in tree.concepts
        assert "category_by_source/gpt/food/food_items/fruit" in tree.concepts

        # Bananas should be a child of the deepest intermediate node
        leaf_parent = tree.concepts["category_by_source/gpt/food/food_items/fruit"]
        assert "food/fruit/bananas" in leaf_parent.narrower

        # Bananas must NOT appear directly under category_by_source/gpt
        gpt_node = tree.concepts["category_by_source/gpt"]
        assert "food/fruit/bananas" not in gpt_node.narrower

    def test_source_paths_intermediate_nodes_chained_correctly(self):
        """Each intermediate node has the right parent in the chain."""
        vocab = {
            "food/fruit/bananas": vocabulary.Concept(
                id="food/fruit/bananas",
                prefLabel="Bananas",
                source_uris={"gpt": "gpt:1234"},
                source_paths={"gpt": "food/food_items/fruit/bananas"},
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        food_node = tree.concepts["category_by_source/gpt/food"]
        assert food_node.broader == ["category_by_source/gpt"]

        food_items_node = tree.concepts["category_by_source/gpt/food/food_items"]
        assert food_items_node.broader == ["category_by_source/gpt/food"]

        fruit_node = tree.concepts["category_by_source/gpt/food/food_items/fruit"]
        assert fruit_node.broader == ["category_by_source/gpt/food/food_items"]

    def test_source_without_path_falls_back_to_flat(self):
        """Source without source_paths entry adds concept directly under source node."""
        vocab = {
            "food/potatoes": vocabulary.Concept(
                id="food/potatoes",
                prefLabel="Potatoes",
                source_uris={"off": "off:en:potatoes"},
                source_paths={},  # no path for off
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        off_node = tree.concepts["category_by_source/off"]
        assert "food/potatoes" in off_node.narrower


class TestPathAliases:
    """Tests for language-specific category path aliases."""

    def test_path_alias_redirects_to_canonical(self):
        """An aliased category path is redirected to the canonical concept."""
        vocab = {
            "clothing/thermal": vocabulary.Concept(
                id="clothing/thermal",
                prefLabel="Thermal clothing",
                path_aliases={"nb": ["klær/vinter", "klær/vinterklær"]},
            ),
        }
        inventory = {"containers": [{"items": [{"metadata": {"categories": ["klær/vinter"]}}]}]}
        result = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=vocab, lang="nb")

        # Canonical path must exist (either from vocab or created)
        assert "clothing/thermal" in result
        # Alias path must NOT be added as a separate inventory concept
        assert "klær/vinter" not in result
        assert "klær" not in result

    def test_path_alias_wrong_lang_not_applied(self):
        """Path aliases for nb are not applied when lang=en."""
        vocab = {
            "clothing/thermal": vocabulary.Concept(
                id="clothing/thermal",
                prefLabel="Thermal clothing",
                path_aliases={"nb": ["klær/vinter"]},
            ),
        }
        inventory = {"containers": [{"items": [{"metadata": {"categories": ["klær/vinter"]}}]}]}
        result = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=vocab, lang="en")

        # Without alias matching, the inventory concept is created verbatim
        assert "klær/vinter" in result
        assert result["klær/vinter"].source == "inventory"

    def test_path_alias_no_lang_treats_as_nb(self):
        """lang='no' is treated the same as 'nb' for alias matching."""
        vocab = {
            "clothing/thermal": vocabulary.Concept(
                id="clothing/thermal",
                prefLabel="Thermal clothing",
                path_aliases={"nb": ["klær/vinter"]},
            ),
        }
        inventory = {"containers": [{"items": [{"metadata": {"categories": ["klær/vinter"]}}]}]}
        result = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=vocab, lang="no")
        assert "klær/vinter" not in result

    def test_path_alias_build_alias_map(self):
        """_build_path_alias_map returns correct reverse mapping."""
        vocab = {
            "clothing/thermal": vocabulary.Concept(
                id="clothing/thermal",
                prefLabel="Thermal clothing",
                path_aliases={"nb": ["klær/vinter", "klær/vinterklær"]},
            ),
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
        }
        alias_map = vocabulary._build_path_alias_map(vocab, "nb")
        assert alias_map["klær/vinter"] == "clothing/thermal"
        assert alias_map["klær/vinterklær"] == "clothing/thermal"
        assert "food" not in alias_map

    def test_altlabel_root_resolution_subpath(self):
        """When the root component is an nb altLabel of a canonical concept,
        a sub-path is created with the Norwegian ID but wired under the canonical parent.

        ``klær`` is an nb altLabel of ``clothing``.  ``klær/jakke`` in the
        inventory should produce a concept ``klær/jakke`` with broader pointing
        to ``clothing`` — not a spurious local ``klær`` root node.
        """
        vocab = {
            "clothing": vocabulary.Concept(
                id="clothing",
                prefLabel="Clothing",
                altLabels={"nb": ["klær"]},
            ),
        }
        inventory = {"containers": [{"items": [{"metadata": {"categories": ["klær/jakke"]}}]}]}
        result = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=vocab, lang="nb")

        assert "klær/jakke" in result
        assert result["klær/jakke"].broader == ["clothing"]
        assert "klær" not in result
        assert "clothing/jakke" not in result

    def test_altlabel_root_resolution_single_segment(self):
        """A single-segment category that is an nb altLabel maps to the canonical concept.

        ``klær`` alone should resolve to existing ``clothing`` — no new node.
        """
        vocab = {
            "clothing": vocabulary.Concept(
                id="clothing",
                prefLabel="Clothing",
                altLabels={"nb": ["klær"]},
            ),
        }
        inventory = {"containers": [{"items": [{"metadata": {"categories": ["klær"]}}]}]}
        result = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=vocab, lang="nb")

        assert "clothing" in result
        assert "klær" not in result

    def test_path_alias_beats_altlabel_root_resolution(self):
        """An explicit full-path alias takes priority over altLabel root resolution.

        ``klær/vinter`` has an explicit path_alias to ``clothing/thermal``, so
        it should NOT be created as ``klær/vinter`` under ``clothing``.
        """
        vocab = {
            "clothing": vocabulary.Concept(
                id="clothing",
                prefLabel="Clothing",
                altLabels={"nb": ["klær"]},
            ),
            "clothing/thermal": vocabulary.Concept(
                id="clothing/thermal",
                prefLabel="Thermal clothing",
                path_aliases={"nb": ["klær/vinter"]},
            ),
        }
        inventory = {"containers": [{"items": [{"metadata": {"categories": ["klær/vinter"]}}]}]}
        result = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=vocab, lang="nb")

        assert "clothing/thermal" in result
        assert "klær/vinter" not in result
        assert "klær" not in result


class TestBuildVocabularyFromInventory:
    """Tests for build_vocabulary_from_inventory function."""

    def test_extract_categories_from_inventory(self):
        """Test extracting categories from inventory data."""
        inventory = {
            "containers": [
                {
                    "id": "box1",
                    "items": [
                        {"name": "Potatoes", "metadata": {"categories": ["food/vegetables/potatoes"]}},
                        {"name": "Hammer", "metadata": {"categories": ["tools/hand-tools"]}},
                    ],
                }
            ]
        }
        vocab = vocabulary.build_vocabulary_from_inventory(inventory)

        # Should create concepts for all paths
        assert "food" in vocab
        assert "food/vegetables" in vocab
        assert "food/vegetables/potatoes" in vocab
        assert "tools" in vocab
        assert "tools/hand-tools" in vocab

    def test_merge_with_local_vocab(self):
        """Test merging with local vocabulary."""
        local = {
            "food": vocabulary.Concept(
                id="food",
                prefLabel="Food & Groceries",  # Custom label
                altLabels={"nb": ["mat"]},
            ),
        }
        inventory = {
            "containers": [
                {
                    "id": "box1",
                    "items": [
                        {"name": "Potatoes", "metadata": {"categories": ["food/vegetables"]}},
                    ],
                }
            ]
        }
        vocab = vocabulary.build_vocabulary_from_inventory(inventory, local_vocab=local)

        # Local vocab should take precedence
        assert vocab["food"].prefLabel == "Food & Groceries"
        assert vocab["food"].altLabels == {"nb": ["mat"]}
        # But inventory categories should also be there
        assert "food/vegetables" in vocab

    def test_empty_inventory(self):
        """Test with empty inventory."""
        inventory = {"containers": []}
        vocab = vocabulary.build_vocabulary_from_inventory(inventory)
        assert vocab == {}

    def test_items_without_categories(self):
        """Test items without categories are ignored."""
        inventory = {
            "containers": [
                {
                    "id": "box1",
                    "items": [
                        {"name": "Item1", "metadata": {"tags": ["foo"]}},
                        {"name": "Item2", "metadata": {}},
                    ],
                }
            ]
        }
        vocab = vocabulary.build_vocabulary_from_inventory(inventory)
        assert vocab == {}


class TestCountItemsPerCategory:
    """Tests for count_items_per_category function."""

    def test_count_simple(self):
        """Test counting items in categories."""
        inventory = {
            "containers": [
                {
                    "id": "box1",
                    "items": [
                        {"name": "Item1", "metadata": {"categories": ["food/vegetables"]}},
                        {"name": "Item2", "metadata": {"categories": ["food/vegetables"]}},
                        {"name": "Item3", "metadata": {"categories": ["tools"]}},
                    ],
                }
            ]
        }
        counts = vocabulary.count_items_per_category(inventory)

        assert counts["food/vegetables"] == 2
        assert counts["tools"] == 1
        # Parent categories should include children
        assert counts["food"] == 2

    def test_count_hierarchical(self):
        """Test counting includes parent categories."""
        inventory = {
            "containers": [
                {
                    "id": "box1",
                    "items": [
                        {"name": "Potatoes", "metadata": {"categories": ["food/vegetables/potatoes"]}},
                    ],
                }
            ]
        }
        counts = vocabulary.count_items_per_category(inventory)

        assert counts["food/vegetables/potatoes"] == 1
        assert counts["food/vegetables"] == 1
        assert counts["food"] == 1


class TestSaveVocabularyJson:
    """Tests for save_vocabulary_json function."""

    def test_save_and_load(self, tmp_path):
        """Test saving vocabulary as JSON."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
                altLabels={"en": ["veggies"]},
            ),
        }
        output_path = tmp_path / "vocabulary.json"
        vocabulary.save_vocabulary_json(vocab, output_path)

        # Load and verify
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "concepts" in data
        assert "roots" in data
        assert "labelIndex" in data
        assert "food" in data["concepts"]
        assert data["concepts"]["food/vegetables"]["altLabels"] == {"en": ["veggies"]}

    def test_save_with_category_mappings(self, tmp_path):
        """Test saving vocabulary with category mappings for hierarchy mode."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/vegetables": vocabulary.Concept(id="food/vegetables", prefLabel="Vegetables"),
            "food/vegetables/potato": vocabulary.Concept(id="food/vegetables/potato", prefLabel="Potato"),
        }
        mappings = {
            "potato": ["food/vegetables/potato", "food/root_vegetables/potato"],
            "carrot": ["food/vegetables/carrot"],
        }
        output_path = tmp_path / "vocabulary.json"
        vocabulary.save_vocabulary_json(vocab, output_path, category_mappings=mappings)

        # Load and verify
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "categoryMappings" in data
        assert data["categoryMappings"]["potato"] == ["food/vegetables/potato", "food/root_vegetables/potato"]
        assert data["categoryMappings"]["carrot"] == ["food/vegetables/carrot"]

    def test_save_without_category_mappings(self, tmp_path):
        """Test that categoryMappings is not present when not provided."""
        vocab = {"food": vocabulary.Concept(id="food", prefLabel="Food")}
        output_path = tmp_path / "vocabulary.json"
        vocabulary.save_vocabulary_json(vocab, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "categoryMappings" not in data


class TestLocalVocabularySourcePreservation:
    """Tests for preserving local vocabulary source even with external URIs.

    Bug fix: Local vocabulary entries with DBpedia/AGROVOC URIs were getting
    their source changed from "local" to "dbpedia"/"agrovoc", which caused
    issues with hierarchy preservation.
    """

    def test_local_vocab_with_dbpedia_uri_keeps_local_source(self, tmp_path):
        """Local vocab entries with DBpedia URI should keep source=local."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  tools:
    prefLabel: "Tools"
    uri: "http://dbpedia.org/resource/Tool"
  hammer:
    prefLabel: "Hammer"
    broader: tools
    uri: "http://dbpedia.org/resource/Hammer"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)

        # Both should have source=local, not dbpedia
        assert vocab["tools"].source == "local"
        assert vocab["hammer"].source == "local"
        # But URIs should be preserved
        assert vocab["tools"].uri == "http://dbpedia.org/resource/Tool"
        assert vocab["hammer"].uri == "http://dbpedia.org/resource/Hammer"

    def test_local_vocab_with_agrovoc_uri_keeps_local_source(self, tmp_path):
        """Local vocab entries with AGROVOC URI should keep source=local."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  potatoes:
    prefLabel: "Potatoes"
    broader: food/vegetables
    uri: "http://aims.fao.org/aos/agrovoc/c_6139"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)

        assert vocab["potatoes"].source == "local"
        assert vocab["potatoes"].uri == "http://aims.fao.org/aos/agrovoc/c_6139"

    def test_local_vocab_root_categories_stay_roots(self, tmp_path):
        """Root categories in local vocab should not get broader from external sources."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  tools:
    prefLabel: "Tools"
    altLabel:
      en: ["equipment"]
  food:
    prefLabel: "Food"
    narrower:
      - food/vegetables
  food/vegetables:
    prefLabel: "Vegetables"
    broader: food
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)

        # tools and food should be roots (no broader)
        assert vocab["tools"].broader == []
        assert vocab["food"].broader == []
        # food/vegetables should have food as broader
        assert vocab["food/vegetables"].broader == ["food"]


class TestPackageSourceAttribution:
    """Tests for distinguishing package vocabulary from user-local vocabulary."""

    def test_load_local_vocabulary_defaults_to_source_local(self, tmp_path):
        """load_local_vocabulary() without default_source uses 'local'."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  clothing:
    prefLabel: "Clothing"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file)
        assert vocab["clothing"].source == "local"

    def test_load_local_vocabulary_with_package_source(self, tmp_path):
        """load_local_vocabulary(default_source='package') sets source='package'."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  clothing:
    prefLabel: "Clothing"
  food:
    prefLabel: "Food"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file, default_source="package")
        assert vocab["clothing"].source == "package"
        assert vocab["food"].source == "package"

    def test_explicit_source_overrides_default(self, tmp_path):
        """Explicit source in YAML overrides default_source param."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("""
concepts:
  tools:
    prefLabel: "Tools"
    source: "custom"
""")
        vocab = vocabulary.load_local_vocabulary(vocab_file, default_source="package")
        assert vocab["tools"].source == "custom"

    def test_local_files_use_local_source(self, tmp_path):
        """load_global_vocabulary() uses source='local' for all non-tingbok vocab files."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        user_vocab = user_dir / "vocabulary.yaml"
        user_vocab.write_text("""
concepts:
  my_thing:
    prefLabel: "My Thing"
""")

        with patch.object(vocabulary, "find_vocabulary_files", return_value=[user_vocab]):
            merged = vocabulary.load_global_vocabulary()

        assert merged["my_thing"].source == "local"

    def test_package_source_round_trip(self):
        """Concept with source='package' survives to_dict/from_dict round-trip."""
        concept = vocabulary.Concept(
            id="clothing",
            prefLabel="Clothing",
            source="package",
        )
        data = concept.to_dict()
        assert data["source"] == "package"

        restored = vocabulary.Concept.from_dict(data)
        assert restored.source == "package"


class TestConceptSourceUris:
    """Tests for source_uris field on Concept."""

    def test_source_uris_defaults_to_empty_dict(self):
        """source_uris defaults to empty dict."""
        concept = vocabulary.Concept(id="test", prefLabel="Test")
        assert concept.source_uris == {}

    def test_to_dict_includes_source_uris_when_nonempty(self):
        """to_dict() includes source_uris when non-empty."""
        concept = vocabulary.Concept(
            id="food/potatoes",
            prefLabel="Potatoes",
            source_uris={"off": "off:en:potatoes", "dbpedia": "http://dbpedia.org/resource/Potato"},
        )
        d = concept.to_dict()
        assert "source_uris" in d
        assert d["source_uris"]["off"] == "off:en:potatoes"
        assert d["source_uris"]["dbpedia"] == "http://dbpedia.org/resource/Potato"

    def test_to_dict_omits_source_uris_when_empty(self):
        """to_dict() omits source_uris when empty."""
        concept = vocabulary.Concept(id="test", prefLabel="Test")
        d = concept.to_dict()
        assert "source_uris" not in d

    def test_from_dict_round_trip(self):
        """from_dict() round-trip preserves source_uris."""
        original = vocabulary.Concept(
            id="food/potatoes",
            prefLabel="Potatoes",
            source_uris={
                "off": "off:en:potatoes",
                "agrovoc": "http://aims.fao.org/aos/agrovoc/c_6139",
                "dbpedia": "http://dbpedia.org/resource/Potato",
            },
        )
        d = original.to_dict()
        restored = vocabulary.Concept.from_dict(d)
        assert restored.source_uris == original.source_uris

    def test_from_dict_missing_source_uris(self):
        """from_dict() handles missing source_uris (backward compat)."""
        d = {"id": "test", "prefLabel": "Test"}
        concept = vocabulary.Concept.from_dict(d)
        assert concept.source_uris == {}


class TestUriToSource:
    """Tests for _uri_to_source() helper."""

    def test_off_uri(self):
        assert vocabulary._uri_to_source("off:en:potatoes") == "off"

    def test_agrovoc_uri(self):
        assert vocabulary._uri_to_source("http://aims.fao.org/aos/agrovoc/c_6139") == "agrovoc"

    def test_dbpedia_uri(self):
        assert vocabulary._uri_to_source("http://dbpedia.org/resource/Potato") == "dbpedia"

    def test_wikidata_uri(self):
        assert vocabulary._uri_to_source("http://www.wikidata.org/entity/Q10998") == "wikidata"

    def test_unknown_uri(self):
        assert vocabulary._uri_to_source("https://example.com/foo") is None

    def test_tingbok_uri(self):
        assert vocabulary._uri_to_source("https://tingbok.plann.no/api/vocabulary/food") == "tingbok"

    def test_tingbok_uri_base(self):
        assert vocabulary._uri_to_source("https://tingbok.plann.no/") == "tingbok"

    def test_dbpedia_https_uri(self):
        assert vocabulary._uri_to_source("https://dbpedia.org/resource/Potato") == "dbpedia"

    def test_wikidata_https_uri(self):
        assert vocabulary._uri_to_source("https://www.wikidata.org/entity/Q10998") == "wikidata"


class TestFetchVocabularyFromTingbok:
    """Tests for fetch_vocabulary_from_tingbok()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    VOCAB_RESPONSE = {
        "food": {
            "id": "food",
            "prefLabel": "Food",
            "altLabel": {"en": ["groceries"], "nb": ["mat"]},
            "broader": [],
            "narrower": ["food/vegetables"],
            "uri": "http://dbpedia.org/resource/Food",
            "labels": {"en": "Food", "nb": "Mat"},
            "description": None,
            "wikipediaUrl": None,
        },
        "food/vegetables": {
            "id": "food/vegetables",
            "prefLabel": "Vegetables",
            "altLabel": {},
            "broader": ["food"],
            "narrower": [],
            "uri": None,
            "labels": {},
            "description": None,
            "wikipediaUrl": None,
        },
    }

    def test_returns_concepts_on_success(self):
        """Successful fetch converts JSON to Concept objects with source='package'."""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self.VOCAB_RESPONSE

        with patch("niquests.get", return_value=mock_response):
            result = vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

        assert "food" in result
        assert "food/vegetables" in result
        assert result["food"].prefLabel == "Food"
        assert result["food"].source == "tingbok"
        assert result["food"].altLabels == {"en": ["groceries"], "nb": ["mat"]}
        assert result["food"].labels == {"en": "Food", "nb": "Mat"}
        assert result["food"].uri == "http://dbpedia.org/resource/Food"
        assert result["food/vegetables"].broader == ["food"]

    def test_strips_trailing_slash_from_url(self):
        """URL with trailing slash is handled correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self.VOCAB_RESPONSE

        with patch("niquests.get", return_value=mock_response) as mock_get:
            vocabulary.fetch_vocabulary_from_tingbok("https://tingbok.plann.no/")

        called_url = mock_get.call_args[0][0]
        assert called_url == "https://tingbok.plann.no/api/vocabulary"

    def test_raises_on_http_error(self):
        """Non-200 response raises TingbokUnavailableError."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = Exception("Service Unavailable")

        with patch("niquests.get", return_value=mock_response):
            with pytest.raises(vocabulary.TingbokUnavailableError):
                vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

    def test_raises_on_connection_error(self):
        """Network error raises TingbokUnavailableError."""
        import niquests

        with patch("niquests.get", side_effect=niquests.ConnectionError("refused")):
            with pytest.raises(vocabulary.TingbokUnavailableError):
                vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

    def test_raises_on_timeout(self):
        """Timeout raises TingbokUnavailableError."""
        import niquests

        with patch("niquests.get", side_effect=niquests.Timeout("timed out")):
            with pytest.raises(vocabulary.TingbokUnavailableError):
                vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

    def test_error_message_contains_url(self):
        """TingbokUnavailableError message includes the endpoint URL."""
        import niquests

        with patch("niquests.get", side_effect=niquests.ConnectionError("refused")):
            with pytest.raises(vocabulary.TingbokUnavailableError, match=self.TINGBOK_URL):
                vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

    def test_source_uris_list_converted_to_dict(self):
        """source_uris list from tingbok JSON is converted to source->URI dict."""
        response_data = {
            "food": {
                "id": "food",
                "prefLabel": "Food",
                "altLabel": {},
                "broader": [],
                "narrower": [],
                "uri": "http://dbpedia.org/resource/Food",
                "labels": {},
                "description": None,
                "wikipediaUrl": None,
                "source_uris": [
                    "https://tingbok.plann.no/api/vocabulary/food",
                    "http://dbpedia.org/resource/Food",
                    "http://aims.fao.org/aos/agrovoc/c_3490",
                ],
                "excluded_sources": [],
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("niquests.get", return_value=mock_response):
            result = vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

        food = result["food"]
        assert isinstance(food.source_uris, dict)
        assert food.source_uris.get("tingbok") == "https://tingbok.plann.no/api/vocabulary/food"
        assert food.source_uris.get("dbpedia") == "http://dbpedia.org/resource/Food"
        assert food.source_uris.get("agrovoc") == "http://aims.fao.org/aos/agrovoc/c_3490"

    def test_excluded_sources_passed_through(self):
        """excluded_sources from tingbok JSON is stored on Concept."""
        response_data = {
            "household/bedding": {
                "id": "household/bedding",
                "prefLabel": "Bedding",
                "altLabel": {},
                "broader": ["household"],
                "narrower": [],
                "uri": "http://dbpedia.org/resource/Bedding",
                "labels": {},
                "description": None,
                "wikipediaUrl": None,
                "source_uris": [
                    "https://tingbok.plann.no/api/vocabulary/household/bedding",
                    "http://dbpedia.org/resource/Bedding",
                ],
                "excluded_sources": ["agrovoc"],
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("niquests.get", return_value=mock_response):
            result = vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL)

        bedding = result["household/bedding"]
        assert bedding.excluded_sources == ["agrovoc"]


class TestLoadGlobalVocabularyTingbok:
    """Tests for load_global_vocabulary() with tingbok_url and skip_cwd."""

    VOCAB_RESPONSE = {
        "food": {
            "id": "food",
            "prefLabel": "Food",
            "altLabel": {},
            "broader": [],
            "narrower": [],
            "uri": None,
            "labels": {},
            "description": None,
            "wikipediaUrl": None,
        }
    }

    def test_uses_tingbok_when_url_configured(self):
        """load_global_vocabulary(tingbok_url=...) fetches from tingbok."""
        with (
            patch.object(
                vocabulary,
                "fetch_vocabulary_from_tingbok",
                return_value={
                    "food": vocabulary.Concept(id="food", prefLabel="Food", source="tingbok"),
                },
            ) as mock_fetch,
            patch.object(vocabulary, "find_vocabulary_files", return_value=[]),
        ):
            result = vocabulary.load_global_vocabulary(tingbok_url="https://tingbok.plann.no")

        mock_fetch.assert_called_once_with("https://tingbok.plann.no", session=None)
        assert "food" in result
        assert result["food"].source == "tingbok"

    def test_raises_when_tingbok_fails(self):
        """TingbokUnavailableError from fetch propagates out of load_global_vocabulary."""
        with (
            patch.object(
                vocabulary,
                "fetch_vocabulary_from_tingbok",
                side_effect=vocabulary.TingbokUnavailableError("tingbok down"),
            ),
            patch.object(vocabulary, "find_vocabulary_files", return_value=[]),
        ):
            with pytest.raises(vocabulary.TingbokUnavailableError):
                vocabulary.load_global_vocabulary(tingbok_url="https://tingbok.plann.no")

    def test_skip_cwd_excludes_cwd_files(self, tmp_path, monkeypatch):
        """skip_cwd=True does not load vocabulary files found in cwd."""
        monkeypatch.chdir(tmp_path)
        cwd_vocab = tmp_path / "vocabulary.yaml"
        cwd_vocab.write_text("concepts:\n  local_thing:\n    prefLabel: 'Local'\n")

        with (
            patch.object(vocabulary, "fetch_vocabulary_from_tingbok", return_value={}),
            patch.object(vocabulary, "find_vocabulary_files", return_value=[cwd_vocab]),
        ):
            result = vocabulary.load_global_vocabulary(skip_cwd=True)

        assert "local_thing" not in result

    def test_without_tingbok_url_loads_from_local_files(self, tmp_path):
        """Without tingbok_url, loads from local files only."""
        vocab_file = tmp_path / "vocabulary.yaml"
        vocab_file.write_text("concepts:\n  food:\n    prefLabel: 'Food'\n")

        with patch.object(vocabulary, "find_vocabulary_files", return_value=[vocab_file]):
            result = vocabulary.load_global_vocabulary()

        assert "food" in result


class TestResolveCategoriesViaTingbok:
    """Tests for resolve_categories_via_tingbok()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def _mock_response(self, data: dict, status_code: int = 200) -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = data
        r.raise_for_status = MagicMock()
        if status_code >= 400:
            import niquests

            r.raise_for_status.side_effect = niquests.HTTPError()
        return r

    def test_found_concept_creates_hierarchy_concepts(self):
        """A resolved concept should add all path segments to new_concepts."""
        hierarchy_response = {
            "label": "cumin",
            "found": True,
            "paths": ["food/spices/cumin"],
            "source": "agrovoc",
            "uri_map": {"food/spices/cumin": "http://aims.fao.org/aos/agrovoc/c_1"},
        }
        with patch("niquests.get", return_value=self._mock_response(hierarchy_response)):
            new_concepts, mappings = vocabulary.resolve_categories_via_tingbok(["cumin"], self.TINGBOK_URL)

        assert "food" in new_concepts
        assert "food/spices" in new_concepts
        assert "food/spices/cumin" in new_concepts
        assert mappings["cumin"] == ["food/spices/cumin"]

    def test_not_found_returns_empty(self):
        """When the hierarchy endpoint returns found=False, nothing is added."""
        hierarchy_response = {
            "label": "xyzzy",
            "found": False,
            "paths": [],
            "source": "agrovoc",
            "uri_map": {},
        }
        with patch("niquests.get", return_value=self._mock_response(hierarchy_response)):
            new_concepts, mappings = vocabulary.resolve_categories_via_tingbok(["xyzzy"], self.TINGBOK_URL)

        assert new_concepts == {}
        assert mappings == {}

    def test_network_error_is_ignored(self):
        """Network errors are caught and the label is skipped silently."""
        import niquests

        with patch("niquests.get", side_effect=niquests.ConnectionError("refused")):
            new_concepts, mappings = vocabulary.resolve_categories_via_tingbok(["cumin"], self.TINGBOK_URL)

        assert new_concepts == {}
        assert mappings == {}

    def test_empty_labels_returns_empty(self):
        """Passing an empty label list returns empty results."""
        new_concepts, mappings = vocabulary.resolve_categories_via_tingbok([], self.TINGBOK_URL)
        assert new_concepts == {}
        assert mappings == {}

    def test_stops_after_first_source_finds_concept(self):
        """Once a concept is found in one source, other sources are not queried."""
        found_response = {
            "label": "cumin",
            "found": True,
            "paths": ["food/spices/cumin"],
            "source": "agrovoc",
            "uri_map": {},
        }
        call_count = 0

        def fake_get(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return self._mock_response(found_response)

        with patch("niquests.get", side_effect=fake_get):
            vocabulary.resolve_categories_via_tingbok(
                ["cumin"], self.TINGBOK_URL, sources=["agrovoc", "dbpedia", "wikidata"]
            )

        assert call_count == 1, "Should stop after first source finds the concept"


class TestFindVocabularyFiles:
    """Tests for find_vocabulary_files — file discovery and exclusion rules."""

    def test_generated_vocabulary_json_not_picked_up_from_cwd(self, tmp_path) -> None:
        """vocabulary.json in CWD (generated parse output) must not be used as input."""
        import os
        from pathlib import Path

        # Create a vocabulary.json that looks like generated output
        generated = tmp_path / "vocabulary.json"
        generated.write_text(
            '{"concepts": {}, "roots": [], "labelIndex": {}, "categoryMappings": {}}',
            encoding="utf-8",
        )

        orig_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            files = vocabulary.find_vocabulary_files()
        finally:
            os.chdir(orig_cwd)

        local_files = [f for f in files if f.parent == tmp_path]
        assert local_files == [], (
            f"find_vocabulary_files() must not return generated vocabulary.json from CWD; got: {local_files}"
        )

    def test_local_vocabulary_json_is_accepted(self, tmp_path) -> None:
        """local-vocabulary.json in CWD should still be accepted as input."""
        import os
        from pathlib import Path

        local_vocab = tmp_path / "local-vocabulary.json"
        local_vocab.write_text('{"concepts": {}}', encoding="utf-8")

        orig_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            files = vocabulary.find_vocabulary_files()
        finally:
            os.chdir(orig_cwd)

        local_files = [f for f in files if f.parent == tmp_path]
        assert local_vocab in local_files

    def test_vocabulary_yaml_in_cwd_is_accepted(self, tmp_path) -> None:
        """vocabulary.yaml in CWD should still be accepted (hand-crafted local vocab)."""
        import os
        from pathlib import Path

        vocab_yaml = tmp_path / "vocabulary.yaml"
        vocab_yaml.write_text("concepts: {}", encoding="utf-8")

        orig_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            files = vocabulary.find_vocabulary_files()
        finally:
            os.chdir(orig_cwd)

        local_files = [f for f in files if f.parent == tmp_path]
        assert vocab_yaml in local_files


class TestLookupEanViaTingbok:
    """Tests for lookup_ean_via_tingbok()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def test_found_product_returns_dict(self) -> None:
        from unittest.mock import MagicMock, patch

        product_data = {
            "ean": "7310865004703",
            "name": "Kalles Kaviar",
            "brand": "Abba",
            "quantity": "300g",
            "categories": ["spreads", "caviar spreads"],
            "image_url": None,
            "source": "openfoodfacts",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = product_data

        with patch("niquests.get", return_value=mock_response):
            result = vocabulary.lookup_ean_via_tingbok("7310865004703", self.TINGBOK_URL)

        assert result is not None
        assert result["ean"] == "7310865004703"
        assert result["name"] == "Kalles Kaviar"
        assert "caviar spreads" in result["categories"]

    def test_not_found_returns_none(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("niquests.get", return_value=mock_response):
            result = vocabulary.lookup_ean_via_tingbok("0000000000000", self.TINGBOK_URL)

        assert result is None

    def test_network_error_returns_none(self) -> None:
        from unittest.mock import patch

        with patch("niquests.get", side_effect=Exception("connection refused")):
            result = vocabulary.lookup_ean_via_tingbok("7310865004703", self.TINGBOK_URL)

        assert result is None

    def test_url_constructed_correctly(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("niquests.get", return_value=mock_response) as mock_get:
            vocabulary.lookup_ean_via_tingbok("7310865004703", "https://tingbok.plann.no/")

        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        assert url == "https://tingbok.plann.no/api/ean/7310865004703"

    def test_uses_session_get_when_provided(self) -> None:
        """When a session is passed, session.get() is used instead of niquests.get()."""
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        result = vocabulary.lookup_ean_via_tingbok("0000000000000", self.TINGBOK_URL, session=mock_session)

        mock_session.get.assert_called_once()
        assert result is None


class TestFetchVocabularySession:
    """Tests that session parameter is forwarded in fetch_vocabulary_from_tingbok()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def test_uses_session_get_when_provided(self) -> None:
        """When a session is passed, session.get() is used instead of niquests.get()."""
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        vocabulary.fetch_vocabulary_from_tingbok(self.TINGBOK_URL, session=mock_session)

        mock_session.get.assert_called_once()
        url = mock_session.get.call_args[0][0]
        assert url == f"{self.TINGBOK_URL}/api/vocabulary"


class TestResolveCategoriesSession:
    """Tests that session parameter is forwarded in resolve_categories_via_tingbok()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def test_uses_session_get_when_provided(self) -> None:
        """When a session is passed, session.get() is used instead of niquests.get()."""
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"found": False, "paths": []}
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        vocabulary.resolve_categories_via_tingbok(["cumin"], self.TINGBOK_URL, session=mock_session)

        mock_session.get.assert_called()


class TestLoadGlobalVocabularySession:
    """Tests that session is passed through load_global_vocabulary()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def test_passes_session_to_fetch(self) -> None:
        """Session passed to load_global_vocabulary() is forwarded to fetch_vocabulary_from_tingbok()."""
        from unittest.mock import MagicMock, patch

        mock_session = MagicMock()

        with patch.object(vocabulary, "fetch_vocabulary_from_tingbok", return_value={}) as mock_fetch:
            vocabulary.load_global_vocabulary(tingbok_url=self.TINGBOK_URL, session=mock_session)

        mock_fetch.assert_called_once_with(self.TINGBOK_URL, session=mock_session)


class TestEnrichCategoriesViaLookup:
    """Tests for enrich_categories_via_lookup()."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def _make_response(self, data: dict, status_code: int = 200):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = data
        return r

    def _vocab_concept(self, concept_id: str, pref_label: str = "", labels: dict | None = None) -> dict:
        return {
            "id": concept_id,
            "prefLabel": pref_label or concept_id.split("/")[-1].title(),
            "altLabel": {"en": ["alt"]},
            "labels": labels or {"en": pref_label or concept_id.split("/")[-1].title(), "nb": "Norsk"},
            "description": "A description",
            "source_uris": ["http://aims.fao.org/aos/agrovoc/c_12851"],
            "broader": [],
            "narrower": [],
        }

    def test_bare_label_resolves_to_path(self) -> None:
        """Bare label 'cumin' resolved to 'food/spices/cumin' recorded in category_mappings."""
        from unittest.mock import patch

        with patch("niquests.get", return_value=self._make_response(self._vocab_concept("food/spices/cumin", "Cumin"))):
            new_concepts, mappings = vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL)

        assert "food/spices/cumin" in new_concepts
        assert mappings.get("cumin") == ["food/spices/cumin"]

    def test_path_label_gets_enriched(self) -> None:
        """Full path 'food/spices/cumin' → enriched concept, no mapping entry."""
        from unittest.mock import patch

        with patch("niquests.get", return_value=self._make_response(self._vocab_concept("food/spices/cumin", "Cumin"))):
            new_concepts, mappings = vocabulary.enrich_categories_via_lookup(["food/spices/cumin"], self.TINGBOK_URL)

        c = new_concepts["food/spices/cumin"]
        assert c.prefLabel == "Cumin"
        assert c.labels.get("nb") == "Norsk"
        assert c.source == "tingbok"
        assert "cumin" not in mappings  # no mapping — input already was the path

    def test_parent_paths_added(self) -> None:
        """All path segments of resolved concept are present in new_concepts."""
        from unittest.mock import patch

        with patch("niquests.get", return_value=self._make_response(self._vocab_concept("food/spices/cumin", "Cumin"))):
            new_concepts, _ = vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL)

        assert "food" in new_concepts
        assert "food/spices" in new_concepts
        assert "food/spices/cumin" in new_concepts

    def test_404_skips_label(self) -> None:
        """404 response → label absent from new_concepts."""
        from unittest.mock import patch

        with patch("niquests.get", return_value=self._make_response({}, status_code=404)):
            new_concepts, mappings = vocabulary.enrich_categories_via_lookup(["xyzzy"], self.TINGBOK_URL)

        assert new_concepts == {}
        assert mappings == {}

    def test_network_error_skips_label(self) -> None:
        """Network exception → graceful skip."""
        from unittest.mock import patch

        with patch("niquests.get", side_effect=Exception("connection refused")):
            new_concepts, mappings = vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL)

        assert new_concepts == {}
        assert mappings == {}

    def test_parent_stub_has_inventory_source(self) -> None:
        """Intermediate path segments added by enrichment have source='inventory'.

        This documents the known behaviour: callers must restore any global-vocab
        concepts that were overwritten by these stubs (as parse_command does after
        calling enrich_categories_via_lookup).
        """
        from unittest.mock import patch

        with patch(
            "niquests.get",
            return_value=self._make_response(self._vocab_concept("clothing/outdoor_clothing", "Outdoor Clothing")),
        ):
            new_concepts, _ = vocabulary.enrich_categories_via_lookup(["outdoor-clothing"], self.TINGBOK_URL)

        # The leaf is enriched
        assert new_concepts["clothing/outdoor_clothing"].source == "tingbok"
        # The parent stub is inventory-sourced — callers must guard against this
        # overwriting a previously loaded tingbok "clothing" concept.
        assert new_concepts["clothing"].source == "inventory"

    def test_uses_session_get_when_provided(self) -> None:
        """session.get() is used instead of niquests.get() when session is passed."""
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        mock_session.get.return_value = self._make_response(self._vocab_concept("food/spices/cumin", "Cumin"))

        vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL, session=mock_session)

        mock_session.get.assert_called_once()
        url = mock_session.get.call_args[0][0]
        assert url.endswith("/api/lookup/cumin")

    def test_altlabels_converted(self) -> None:
        """altLabel from VocabularyConcept (SKOS key) is stored in Concept.altLabels."""
        from unittest.mock import patch

        data = self._vocab_concept("food/spices/cumin", "Cumin")
        data["altLabel"] = {"en": ["cummin", "jeera"]}
        with patch("niquests.get", return_value=self._make_response(data)):
            new_concepts, _ = vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL)

        assert new_concepts["food/spices/cumin"].altLabels == {"en": ["cummin", "jeera"]}


class TestEanCache:
    """Tests for client-side EAN caching in lookup_ean_via_tingbok and report_ean_to_tingbok."""

    TINGBOK_URL = "https://tingbok.plann.no"
    EAN = "7310865004703"

    def _product(self) -> dict:
        return {
            "ean": self.EAN,
            "name": "Kalles Kaviar",
            "brand": "Abba",
            "quantity": "300g",
            "categories": ["spreads"],
            "source": "openfoodfacts",
        }

    def test_cache_miss_calls_network_and_saves(self, tmp_path) -> None:
        """On cache miss, network is called and result is saved to cache."""
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._product()

        with patch("niquests.get", return_value=mock_response) as mock_get:
            result = vocabulary.lookup_ean_via_tingbok(self.EAN, self.TINGBOK_URL, cache_dir=tmp_path)

        mock_get.assert_called_once()
        assert result is not None
        assert result["name"] == "Kalles Kaviar"
        # Cache file should exist after the call
        cache_files = list(tmp_path.glob("*.json"))
        assert cache_files, "Cache file should be written after a network call"

    def test_cache_hit_skips_network(self, tmp_path) -> None:
        """On cache hit (within TTL), network is not called."""
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._product()

        # First call populates cache
        with patch("niquests.get", return_value=mock_response):
            vocabulary.lookup_ean_via_tingbok(self.EAN, self.TINGBOK_URL, cache_dir=tmp_path)

        # Second call should use cache
        with patch("niquests.get") as mock_get2:
            result = vocabulary.lookup_ean_via_tingbok(self.EAN, self.TINGBOK_URL, cache_dir=tmp_path)

        mock_get2.assert_not_called()
        assert result is not None
        assert result["name"] == "Kalles Kaviar"

    def test_no_cache_dir_always_calls_network(self, tmp_path) -> None:
        """When cache_dir is None, network is always called (backwards-compatible)."""
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._product()

        with patch("niquests.get", return_value=mock_response) as mock_get:
            vocabulary.lookup_ean_via_tingbok(self.EAN, self.TINGBOK_URL, cache_dir=None)
            vocabulary.lookup_ean_via_tingbok(self.EAN, self.TINGBOK_URL, cache_dir=None)

        assert mock_get.call_count == 2

    def test_put_invalidates_get_cache(self, tmp_path) -> None:
        """A successful PUT removes the GET cache so next lookup fetches fresh data."""
        from unittest.mock import MagicMock, patch

        get_response = MagicMock()
        get_response.status_code = 200
        get_response.json.return_value = self._product()

        put_response = MagicMock()
        put_response.status_code = 200
        put_response.json.return_value = self._product()

        # Populate GET cache
        with patch("niquests.get", return_value=get_response):
            vocabulary.lookup_ean_via_tingbok(self.EAN, self.TINGBOK_URL, cache_dir=tmp_path)
        assert (tmp_path / f"{self.EAN}.json").exists()

        # PUT should delete the cache file
        with patch("niquests.put", return_value=put_response):
            vocabulary.report_ean_to_tingbok(self.EAN, ["food"], "Kaviar", self.TINGBOK_URL, cache_dir=tmp_path)

        assert not (tmp_path / f"{self.EAN}.json").exists(), "Cache should be invalidated after PUT"

    def test_report_without_cache_dir_always_sends(self) -> None:
        """Without cache_dir, PUT is always sent (backwards-compatible)."""
        from unittest.mock import MagicMock, patch

        put_response = MagicMock()
        put_response.status_code = 200
        put_response.json.return_value = self._product()

        with patch("niquests.put", return_value=put_response) as mock_put:
            vocabulary.report_ean_to_tingbok(self.EAN, ["food"], "Kaviar", self.TINGBOK_URL, cache_dir=None)
            vocabulary.report_ean_to_tingbok(self.EAN, ["food"], "Kaviar", self.TINGBOK_URL, cache_dir=None)

        assert mock_put.call_count == 2


class TestEanObservationNeeded:
    """Tests for ean_observation_needed() comparison helper."""

    def _product(self, categories=("spreads",), prices=()) -> dict:
        return {
            "ean": "1234",
            "name": "Kaviar",
            "quantity": "300g",
            "categories": list(categories),
            "prices": list(prices),
            "source": "openfoodfacts",
        }

    def test_nothing_to_push_returns_false(self) -> None:
        assert not vocabulary.ean_observation_needed(self._product(), [], None, None, None)

    def test_category_already_present_returns_false(self) -> None:
        assert not vocabulary.ean_observation_needed(self._product(categories=["food"]), ["food"], None, None, None)

    def test_category_missing_returns_true(self) -> None:
        assert vocabulary.ean_observation_needed(self._product(categories=[]), ["food"], None, None, None)

    def test_quantity_already_matches_returns_false(self) -> None:
        assert not vocabulary.ean_observation_needed(self._product(), [], None, "300g", None)

    def test_quantity_differs_returns_true(self) -> None:
        assert vocabulary.ean_observation_needed(self._product(), [], None, "250g", None)

    def test_price_already_present_returns_false(self) -> None:
        price = {"date": "2026-03-08", "currency": "NOK", "price": 9.9, "unit": "pcs"}
        product = self._product(prices=[price])
        assert not vocabulary.ean_observation_needed(product, [], None, None, [price])

    def test_price_missing_returns_true(self) -> None:
        price = {"date": "2026-03-08", "currency": "NOK", "price": 9.9, "unit": "pcs"}
        assert vocabulary.ean_observation_needed(self._product(prices=[]), [], None, None, [price])

    def test_none_product_with_data_returns_true(self) -> None:
        assert vocabulary.ean_observation_needed(None, ["food"], None, None, None)

    def test_none_product_no_data_returns_false(self) -> None:
        assert not vocabulary.ean_observation_needed(None, [], None, None, None)

    def test_price_same_currency_price_unit_different_date_returns_false(self) -> None:
        """Inventory rows are not new observations — same price must not re-trigger a push just because dates differ."""
        server_price = {"date": "2025-12-01", "currency": "NOK", "price": 9.9, "unit": "pcs"}
        client_price = {"date": "2026-03-08", "currency": "NOK", "price": 9.9, "unit": "pcs"}
        product = self._product(prices=[server_price])
        assert not vocabulary.ean_observation_needed(product, [], None, None, [client_price])

    def test_price_with_no_date_matches_server_price_with_date(self) -> None:
        """Client prices from inventory may lack a date; server prices from a previous push may have one."""
        server_price = {"date": "2025-12-01", "currency": "NOK", "price": 9.9, "unit": "pcs"}
        client_price = {"currency": "NOK", "price": 9.9, "unit": "pcs"}
        product = self._product(prices=[server_price])
        assert not vocabulary.ean_observation_needed(product, [], None, None, [client_price])


class TestLookupCache:
    """Tests for client-side caching in enrich_categories_via_lookup."""

    TINGBOK_URL = "https://tingbok.plann.no"

    def _make_response(self, data: dict, status_code: int = 200):
        from unittest.mock import MagicMock

        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = data
        return r

    def _vocab_concept(self, concept_id: str) -> dict:
        return {
            "id": concept_id,
            "prefLabel": concept_id.split("/")[-1].title(),
            "altLabel": {},
            "labels": {"en": concept_id.split("/")[-1].title()},
            "description": None,
            "source_uris": [],
            "broader": [],
            "narrower": [],
        }

    def test_cache_miss_calls_network_and_saves(self, tmp_path) -> None:
        """On cache miss, network is called and result is cached."""
        from unittest.mock import patch

        with patch(
            "niquests.get", return_value=self._make_response(self._vocab_concept("food/spices/cumin"))
        ) as mock_get:
            vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL, cache_dir=tmp_path)

        mock_get.assert_called_once()
        cache_files = list(tmp_path.glob("*.json"))
        assert cache_files, "Cache file should be written after a network call"

    def test_cache_hit_skips_network(self, tmp_path) -> None:
        """On cache hit, network is not called."""
        from unittest.mock import patch

        response = self._make_response(self._vocab_concept("food/spices/cumin"))
        with patch("niquests.get", return_value=response):
            vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL, cache_dir=tmp_path)

        with patch("niquests.get") as mock_get2:
            new_concepts, _ = vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL, cache_dir=tmp_path)

        mock_get2.assert_not_called()
        assert "food/spices/cumin" in new_concepts

    def test_no_cache_dir_always_calls_network(self) -> None:
        """Without cache_dir, network is always called."""
        from unittest.mock import patch

        response = self._make_response(self._vocab_concept("food/spices/cumin"))
        with patch("niquests.get", return_value=response) as mock_get:
            vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL, cache_dir=None)
            vocabulary.enrich_categories_via_lookup(["cumin"], self.TINGBOK_URL, cache_dir=None)

        assert mock_get.call_count == 2


class TestBroaderStubs:
    """Tests for stub concept creation for dangling broader references."""

    def test_stub_created_for_missing_broader(self):
        """build_category_tree creates a stub for a broader ID that doesn't exist."""
        vocab = {
            "olive_oil": vocabulary.Concept(
                id="olive_oil",
                prefLabel="Olive Oil",
                broader=["primary_commodity/raw_material/oil/cooking_oil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert "primary_commodity/raw_material/oil/cooking_oil" in tree.concepts
        assert "primary_commodity/raw_material/oil" in tree.concepts
        assert "primary_commodity/raw_material" in tree.concepts
        assert "primary_commodity" in tree.concepts

    def test_stub_has_sensible_preflabel(self):
        """Stubs derive prefLabel from path component (underscores → spaces, title case)."""
        vocab = {
            "olive_oil": vocabulary.Concept(
                id="olive_oil",
                prefLabel="Olive Oil",
                broader=["primary_commodity/raw_material/oil/cooking_oil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.concepts["primary_commodity/raw_material/oil/cooking_oil"].prefLabel == "Cooking Oil"
        assert tree.concepts["primary_commodity"].prefLabel == "Primary Commodity"

    def test_stub_included_in_label_index(self):
        """Stubs appear in the label index so they can be searched by name."""
        vocab = {
            "olive_oil": vocabulary.Concept(
                id="olive_oil",
                prefLabel="Olive Oil",
                broader=["primary_commodity/raw_material/oil/cooking_oil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.label_index.get("cooking oil") == "primary_commodity/raw_material/oil/cooking_oil"
        assert tree.label_index.get("primary commodity") == "primary_commodity"

    def test_stub_narrower_links_original_concept(self):
        """The stub's narrower list includes the concept that referenced it."""
        vocab = {
            "olive_oil": vocabulary.Concept(
                id="olive_oil",
                prefLabel="Olive Oil",
                broader=["primary_commodity/raw_material/oil/cooking_oil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        stub = tree.concepts["primary_commodity/raw_material/oil/cooking_oil"]
        assert "olive_oil" in stub.narrower

    def test_stub_hierarchy_linked_correctly(self):
        """Ancestor stubs are linked: primary_commodity/raw_material is a child of primary_commodity."""
        vocab = {
            "olive_oil": vocabulary.Concept(
                id="olive_oil",
                prefLabel="Olive Oil",
                broader=["primary_commodity/raw_material/oil/cooking_oil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.concepts["primary_commodity/raw_material"].broader == ["primary_commodity"]
        assert "primary_commodity/raw_material" in tree.concepts["primary_commodity"].narrower

    def test_resolve_category_finds_leaf_via_stub(self):
        """resolve_category('cooking_oil') matches the stub via leaf-name lookup."""
        vocab = {
            "olive_oil": vocabulary.Concept(
                id="olive_oil",
                prefLabel="Olive Oil",
                broader=["primary_commodity/raw_material/oil/cooking_oil"],
            ),
        }
        tree = vocabulary.build_category_tree(vocab)

        result = vocabulary.resolve_category("cooking_oil", tree.concepts)
        assert result == "primary_commodity/raw_material/oil/cooking_oil"

    def test_no_stub_when_broader_already_exists(self):
        """No spurious stub is created when the broader concept already exists."""
        vocab = {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/oil": vocabulary.Concept(id="food/oil", prefLabel="Oil", broader=["food"]),
        }
        tree = vocabulary.build_category_tree(vocab)

        assert tree.concepts["food"].source != "inferred"


class TestResolveCategoryViaAltLabel:
    """resolve_category falls back to the altLabel index for raw category strings.

    Tingbok folds synonym/number variants of a category into the canonical
    concept's altLabels (e.g. ``food/vegetables`` carries ``vegetable`` and
    ``veggies``).  resolve_category must consult those — reusing the same label
    index ``lookup_concept`` uses — so an inventory category written as a synonym
    or singular resolves to the canonical concept ID rather than falling through.
    """

    def _veg_vocab(self):
        return {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "food/vegetables": vocabulary.Concept(
                id="food/vegetables",
                prefLabel="Vegetables",
                broader=["food"],
                altLabels={"en": ["vegetable", "veggies", "greens"]},
            ),
            "corn": vocabulary.Concept(id="corn", prefLabel="Corn", broader=["food/vegetables"]),
        }

    def test_plural_leaf_resolves_to_canonical(self):
        # "vegetables" is the leaf of food/vegetables → resolved by the existing step.
        assert vocabulary.resolve_category("vegetables", self._veg_vocab()) == "food/vegetables"

    def test_singular_altlabel_resolves_to_canonical(self):
        # "vegetable" is only an altLabel, not the leaf → needs the new index fallback.
        assert vocabulary.resolve_category("vegetable", self._veg_vocab()) == "food/vegetables"

    def test_other_altlabel_resolves_to_canonical(self):
        assert vocabulary.resolve_category("veggies", self._veg_vocab()) == "food/vegetables"

    def test_case_insensitive(self):
        assert vocabulary.resolve_category("Vegetable", self._veg_vocab()) == "food/vegetables"

    def test_singular_and_plural_match_same_items(self):
        # End-to-end: both spellings resolve to the same canonical, so descendant
        # checks against either one behave identically.
        vocab = self._veg_vocab()
        sing = vocabulary.resolve_category("vegetable", vocab)
        plur = vocabulary.resolve_category("vegetables", vocab)
        assert sing == plur == "food/vegetables"
        assert vocabulary.is_descendant_of("corn", sing, vocab)
        assert vocabulary.is_descendant_of("corn", plur, vocab)

    def test_unknown_label_still_returns_none(self):
        assert vocabulary.resolve_category("definitely-not-a-category", self._veg_vocab()) is None


class TestBuildLabelIndexCache:
    """build_label_index returns cached object on repeated calls with same dict."""

    def setup_method(self):
        vocabulary._label_index_cache.clear()

    def _make_concepts(self) -> dict[str, vocabulary.Concept]:
        return {
            "food": vocabulary.Concept(id="food", prefLabel="Food"),
            "drink": vocabulary.Concept(id="drink", prefLabel="Drink", altLabels={"en": ["beverage"]}),
        }

    def test_returns_same_object_on_second_call(self):
        concepts = self._make_concepts()
        first = vocabulary.build_label_index(concepts)
        second = vocabulary.build_label_index(concepts)
        assert first is second

    def test_different_dict_returns_different_object(self):
        a = self._make_concepts()
        b = self._make_concepts()
        assert a is not b
        assert vocabulary.build_label_index(a) is not vocabulary.build_label_index(b)

    def test_cache_is_populated(self):
        concepts = self._make_concepts()
        vocabulary.build_label_index(concepts)
        assert id(concepts) in vocabulary._label_index_cache

    def test_index_contains_expected_keys(self):
        concepts = self._make_concepts()
        idx = vocabulary.build_label_index(concepts)
        assert idx["food"] == "food"
        assert idx["drink"] == "drink"
        assert idx["beverage"] == "drink"


class TestBuildPathAliasMapCache:
    """_build_path_alias_map returns cached object on repeated calls."""

    def setup_method(self):
        vocabulary._alias_map_cache.clear()

    def _make_vocab(self) -> dict[str, vocabulary.Concept]:
        c = vocabulary.Concept(id="food", prefLabel="Food")
        c.path_aliases = {"en": ["food", "foods"]}
        return {"food": c}

    def test_returns_same_object_on_second_call(self):
        vocab = self._make_vocab()
        first = vocabulary._build_path_alias_map(vocab, "en")
        second = vocabulary._build_path_alias_map(vocab, "en")
        assert first is second

    def test_different_lang_returns_different_object(self):
        vocab = self._make_vocab()
        en = vocabulary._build_path_alias_map(vocab, "en")
        no = vocabulary._build_path_alias_map(vocab, "no")
        assert en is not no

    def test_cache_is_populated(self):
        vocab = self._make_vocab()
        vocabulary._build_path_alias_map(vocab, "en")
        assert (id(vocab), "en") in vocabulary._alias_map_cache

    def test_map_contains_expected_keys(self):
        vocab = self._make_vocab()
        m = vocabulary._build_path_alias_map(vocab, "en")
        assert m["food"] == "food"
        assert m["foods"] == "food"
