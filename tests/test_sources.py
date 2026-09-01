"""Tests for the category-source registry.

tingbok is the authority on which sources exist; this module holds a bundled
copy so an offline inventory still gets sensible labels, and fetches the live
list when tingbok is reachable.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from inventory_md import sources


@pytest.fixture(autouse=True)
def _reset_registry():
    sources.reset_registry()
    yield
    sources.reset_registry()


class TestBundledRegistry:
    def test_known_sources_are_present(self):
        for name in ("agrovoc", "dbpedia", "wikidata", "off", "gpt", "tingbok"):
            assert sources.source_by_name(name) is not None, f"{name} missing"

    def test_labels(self):
        assert sources.source_label("off") == "OpenFoodFacts"
        assert sources.source_label("gpt") == "Google Product Taxonomy"

    def test_unknown_source_falls_back_to_a_title_cased_name(self):
        assert sources.source_label("brreg") == "Brreg"

    def test_the_bundled_table_mirrors_tingbok(self):
        """It is the offline fallback, so it must classify identically.

        A difference here means the same URI lands in a different
        ``category_by_source`` group depending on whether the network was up.
        """
        tingbok_sources = pytest.importorskip("tingbok.sources")
        theirs = {s.name: s for s in tingbok_sources.SOURCES}
        ours = {s.name: s for s in sources.BUNDLED_SOURCES}
        assert set(ours) == set(theirs)
        for name, mine in ours.items():
            assert mine.label == theirs[name].label, name
            assert set(mine.uri_prefixes) == set(theirs[name].uri_prefixes), name
            assert set(mine.hosts) == set(theirs[name].hosts), name
            assert mine.homepage == theirs[name].homepage, name
            assert mine.is_self == theirs[name].is_self, name

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("off:en:potatoes", "off"),
            # Language subdomains are real: four concepts in one inventory carry
            # them, and a startswith test on "https://dbpedia.org/" drops all four.
            ("https://de.dbpedia.org/resource/Cornflakes", "dbpedia"),
            ("https://fr.dbpedia.org/resource/Carbonated_Soft_Drink", "dbpedia"),
            ("http://de.dbpedia.org/resource/Saucen", "dbpedia"),
            ("https://wikidata.org/entity/Q10998", "wikidata"),
            ("http://tingbok.plann.no/api/vocabulary/food", "tingbok"),
            ("https://notdbpedia.org/resource/X", None),
            ("https://dbpedia.org.evil.example/x", None),
            ("gpt:632", "gpt"),
            ("http://aims.fao.org/aos/agrovoc/c_6139", "agrovoc"),
            ("https://aims.fao.org/aos/agrovoc/c_6139", "agrovoc"),
            ("http://dbpedia.org/resource/Potato", "dbpedia"),
            ("https://dbpedia.org/resource/Potato", "dbpedia"),
            ("http://www.wikidata.org/entity/Q10998", "wikidata"),
            ("https://www.wikidata.org/entity/Q10998", "wikidata"),
            ("https://tingbok.plann.no/api/vocabulary/food", "tingbok"),
            ("https://tingbok.plann.no/", "tingbok"),
            ("https://example.com/foo", None),
            ("", None),
        ],
    )
    def test_uri_to_source(self, uri, expected):
        assert sources.uri_to_source(uri) == expected


class TestFetchFromTingbok:
    def _response(self, payload):
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_a_source_tingbok_knows_about_needs_no_client_release(self):
        """The whole point: a new source reaches the client over the wire."""
        session = MagicMock()
        session.get.return_value = self._response(
            {
                "sources": [
                    {
                        "name": "brreg",
                        "label": "Brønnøysundregistrene",
                        "uri_prefixes": ["https://data.brreg.no/"],
                        "homepage": None,
                        "is_self": False,
                    }
                ]
            }
        )
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=session)
        assert sources.source_label("brreg") == "Brønnøysundregistrene"
        assert sources.uri_to_source("https://data.brreg.no/enhet/1") == "brreg"

    def test_an_unreachable_tingbok_leaves_the_bundled_registry_in_place(self):
        session = MagicMock()
        session.get.side_effect = OSError("no route to host")
        assert not sources.refresh_registry_from_tingbok("https://tingbok.example", session=session)
        assert sources.source_label("off") == "OpenFoodFacts"
        assert sources.uri_to_source("off:en:potatoes") == "off"

    def test_a_malformed_response_leaves_the_bundled_registry_in_place(self):
        session = MagicMock()
        session.get.return_value = self._response({"sources": "not a list"})
        assert not sources.refresh_registry_from_tingbok("https://tingbok.example", session=session)
        assert sources.source_label("off") == "OpenFoodFacts"

    def test_an_entry_missing_a_name_is_skipped_not_fatal(self):
        session = MagicMock()
        session.get.return_value = self._response(
            {"sources": [{"label": "Nameless"}, {"name": "off", "label": "OFF", "uri_prefixes": ["off:"]}]}
        )
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=session)
        assert sources.source_label("off") == "OFF"

    def test_the_embedded_answer_is_not_written_to_the_cache(self, tmp_path):
        """Otherwise one offline run suppresses HTTP for the whole TTL.

        The point of the feature is that a source added to tingbok reaches the
        client over the wire; caching a locally-computed answer would defeat
        that for 60 days, and contradict the documented "HTTP is tried first".
        """
        import types

        from inventory_md import tingbok_embedded

        module = types.ModuleType("tingbok.embedded")
        module.get_sources = MagicMock(
            return_value=[{"name": "off", "label": "Embedded OFF", "uri_prefixes": ["off:"]}]
        )
        tingbok_embedded._module = module
        try:
            dead = MagicMock()
            dead.get.side_effect = OSError("no route to host")
            assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=dead, cache_dir=tmp_path)
            assert sources.source_label("off") == "Embedded OFF"
            assert not (tmp_path / "sources.json").exists()
        finally:
            tingbok_embedded.reset()

    def test_an_empty_source_list_is_refused(self):
        """An empty list would silently blank out every source label."""
        session = MagicMock()
        session.get.return_value = self._response({"sources": []})
        assert not sources.refresh_registry_from_tingbok("https://tingbok.example", session=session)
        assert sources.source_label("off") == "OpenFoodFacts"


class TestRegistryCache:
    def test_a_fetched_registry_is_reused_from_disk(self, tmp_path):
        session = MagicMock()
        session.get.return_value = MagicMock(
            json=MagicMock(
                return_value={"sources": [{"name": "off", "label": "Cached OFF", "uri_prefixes": ["off:"]}]}
            ),
            raise_for_status=MagicMock(return_value=None),
        )
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=session, cache_dir=tmp_path)
        assert session.get.call_count == 1

        sources.reset_registry()
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=session, cache_dir=tmp_path)
        assert session.get.call_count == 1, "a cached registry should not be re-fetched"
        assert sources.source_label("off") == "Cached OFF"

    def test_an_expired_cache_is_refetched(self, tmp_path):
        cache = tmp_path / "sources.json"
        cache.write_text(
            json.dumps(
                {
                    "cached_at": "2020-01-01T00:00:00+00:00",
                    "sources": [{"name": "off", "label": "Stale OFF", "uri_prefixes": ["off:"]}],
                }
            ),
            encoding="utf-8",
        )
        session = MagicMock()
        session.get.return_value = MagicMock(
            json=MagicMock(return_value={"sources": [{"name": "off", "label": "Fresh OFF", "uri_prefixes": ["off:"]}]}),
            raise_for_status=MagicMock(return_value=None),
        )
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=session, cache_dir=tmp_path)
        assert sources.source_label("off") == "Fresh OFF"
