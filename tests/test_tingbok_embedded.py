"""Tests for the in-process tingbok fallback.

When ``tingbok.plann.no`` does not answer and the ``tingbok`` package happens to
be installed, ask it directly rather than degrading.  Optional by design: the
overwhelmingly common case is a client with no tingbok installed at all, and
that must keep working exactly as before.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from inventory_md import sources, tingbok_embedded, vocabulary


@pytest.fixture(autouse=True)
def _reset():
    tingbok_embedded.reset()
    sources.reset_registry()
    yield
    tingbok_embedded.reset()
    sources.reset_registry()


@pytest.fixture
def no_tingbok(monkeypatch):
    """Make the in-process tingbok look uninstalled.

    Stubbing ``sys.modules["tingbok.embedded"]`` does **not** do this: the
    import is ``from tingbok import embedded``, which resolves through
    ``getattr(tingbok, "embedded")`` and only consults ``sys.modules`` when that
    attribute is missing.  Once anything in the process has imported
    ``tingbok.embedded`` the attribute is set for good, so a sys.modules stub is
    silently ignored and the test exercises the real package — which is exactly
    what happens on the machine this feature targets.
    """
    monkeypatch.setattr(tingbok_embedded, "_module", False)


@pytest.fixture
def fake_tingbok(monkeypatch):
    """Install a stand-in ``tingbok.embedded`` module."""
    module = types.ModuleType("tingbok.embedded")
    module.get_sources = MagicMock(
        return_value=[{"name": "off", "label": "Embedded OFF", "uri_prefixes": ["off:"], "is_self": False}]
    )
    module.get_ancestors = MagicMock(return_value=["food/legumes", "food"])
    module.get_vocabulary = MagicMock(
        return_value={"food": {"id": "food", "prefLabel": "Food", "altLabel": {}, "broader": [], "narrower": []}}
    )
    module.resolve_vocabulary = MagicMock(
        return_value={
            "concepts": {"food": {"id": "food", "prefLabel": "Food", "altLabel": {}, "broader": [], "narrower": []}}
        }
    )
    monkeypatch.setattr(tingbok_embedded, "_module", module)
    return module


def _dead_session():
    session = MagicMock()
    session.get.side_effect = OSError("no route to host")
    session.post.side_effect = OSError("no route to host")
    return session


class TestAvailability:
    def test_no_tingbok_installed_is_not_an_error(self, no_tingbok):
        assert tingbok_embedded.get_module() is None

    def test_the_import_is_attempted_once(self, monkeypatch):
        calls = []
        real_import = __import__

        def counting_import(name, *args, **kwargs):
            # ``from tingbok import embedded`` imports "tingbok" with a fromlist.
            if name in ("tingbok", "tingbok.embedded"):
                calls.append(name)
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", counting_import)
        for _ in range(3):
            assert tingbok_embedded.get_module() is None
        assert len(calls) == 1, "a missing tingbok should not be re-imported on every call"


class TestSourceRegistryFallback:
    def test_an_unreachable_tingbok_falls_back_to_the_installed_package(self, fake_tingbok):
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=_dead_session())
        assert sources.source_label("off") == "Embedded OFF"

    def test_no_installed_package_leaves_the_bundled_table(self, no_tingbok):
        assert not sources.refresh_registry_from_tingbok("https://tingbok.example", session=_dead_session())
        assert sources.source_label("off") == "OpenFoodFacts"

    def test_a_reachable_tingbok_is_not_second_guessed(self, fake_tingbok):
        session = MagicMock()
        session.get.return_value = MagicMock(
            json=MagicMock(return_value={"sources": [{"name": "off", "label": "HTTP OFF", "uri_prefixes": ["off:"]}]}),
            raise_for_status=MagicMock(return_value=None),
        )
        assert sources.refresh_registry_from_tingbok("https://tingbok.example", session=session)
        assert sources.source_label("off") == "HTTP OFF"
        fake_tingbok.get_sources.assert_not_called()


class TestAncestorsFallback:
    def test_an_unreachable_tingbok_falls_back(self, fake_tingbok):
        assert vocabulary.fetch_ancestors_from_tingbok(
            "soybeans", "https://tingbok.example", session=_dead_session()
        ) == ["food/legumes", "food"]

    def test_is_descendant_of_uses_it(self, fake_tingbok):
        vocab = {"food": vocabulary.Concept(id="food", prefLabel="Food")}
        assert vocabulary.is_descendant_of(
            "soybeans", "food", vocab, tingbok_url="https://tingbok.example", session=_dead_session()
        )

    def test_no_installed_package_means_no_answer(self, no_tingbok):
        assert (
            vocabulary.fetch_ancestors_from_tingbok("soybeans", "https://tingbok.example", session=_dead_session())
            is None
        )


class TestVocabularyFallback:
    def test_fetch_falls_back(self, fake_tingbok):
        vocab = vocabulary.fetch_vocabulary_from_tingbok("https://tingbok.example", session=_dead_session())
        assert "food" in vocab
        assert vocab["food"].source == "tingbok"

    def test_resolve_falls_back_and_asks_for_offline_resolution(self, fake_tingbok):
        vocab = vocabulary.resolve_vocabulary_from_tingbok(["food"], "https://tingbok.example", session=_dead_session())
        assert "food" in vocab
        assert fake_tingbok.resolve_vocabulary.call_args.kwargs["offline"] is True

    def test_without_the_package_the_error_still_surfaces(self, no_tingbok):
        with pytest.raises(vocabulary.TingbokUnavailableError):
            vocabulary.fetch_vocabulary_from_tingbok("https://tingbok.example", session=_dead_session())

    def test_an_embedded_failure_still_surfaces_the_original_error(self, fake_tingbok):
        fake_tingbok.get_vocabulary.side_effect = RuntimeError("vocabulary.yaml is missing")
        with pytest.raises(vocabulary.TingbokUnavailableError):
            vocabulary.fetch_vocabulary_from_tingbok("https://tingbok.example", session=_dead_session())
