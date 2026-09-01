"""Which category sources exist, what to call them, and how to recognise one.

A concept's ``source_uris`` say where it came from — ``off:en:potatoes`` is
OpenFoodFacts, ``gpt:632`` is the Google Product Taxonomy — and the category
browser groups concepts by source under ``category_by_source``, so it needs both
a URI-prefix table and a display name for each source.

tingbok is the authority on which sources exist, and now says so over
``GET /api/sources``.  This module fetches that list and caches it; the
:data:`BUNDLED_SOURCES` table below is the offline fallback, not the truth.  An
inventory is routinely parsed with tingbok unreachable — and the generated
``vocabulary.json`` is read by a static web UI with no server at all — so the
bundled copy has to exist, but it no longer has to be *updated* for a new source
to show up.

Note the deliberate difference from tingbok's own ``uri_to_source()``: that one
returns ``None`` for tingbok's own concept URIs, because it is used to decide
where to fetch labels from upstream and there is nothing upstream to fetch.
Here a tingbok URI resolves to ``"tingbok"``, because grouping concepts by
source has to put tingbok-native concepts somewhere.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from inventory_md import tingbok_embedded

if TYPE_CHECKING:
    import niquests

logger = logging.getLogger(__name__)

#: How long a fetched registry stays usable.  Matches tingbok's own SKOS cache
#: TTL (``tingbok.services.skos.CACHE_TTL_SECONDS``); the source list changes
#: about as often as tingbok gains a new upstream, i.e. rarely.
REGISTRY_CACHE_TTL_DAYS = 60


@dataclass(frozen=True)
class Source:
    """One category source.

    Attributes:
        name: Short identifier used in ``source_uris`` keys and in
            ``category_by_source/{name}`` node IDs.
        label: Human-readable name, for display in the category browser.
        uri_prefixes: Literal prefixes for sources whose URIs are not http(s)
            at all — ``off:en:potatoes``, ``gpt:632``.
        hosts: Domains identifying an http(s) source URI, matched against the
            URI's host and its subdomains.  A prefix test is not enough:
            upstream data carries ``de.dbpedia.org`` and ``fr.dbpedia.org`` as
            well as ``dbpedia.org``, ``wikidata.org`` with and without ``www.``,
            and both http and https spellings of all of them.
        homepage: Where a human can read about the source.
        is_self: True for tingbok's own concept URIs — a concept tingbok defines
            itself rather than one resolved from an upstream source.
    """

    name: str
    label: str
    uri_prefixes: tuple[str, ...] = field(default_factory=tuple)
    hosts: tuple[str, ...] = field(default_factory=tuple)
    homepage: str | None = None
    is_self: bool = False


#: Offline fallback, mirroring ``tingbok.sources.SOURCES`` field for field.
#: Used when tingbok has never been reached.  The mirroring matters more than it
#: looks: a difference here means the same URI is classified into a different
#: ``category_by_source`` group depending on whether the network happened to be
#: up.  ``tests/test_sources.py`` asserts the two tables agree whenever the
#: tingbok package is importable.
BUNDLED_SOURCES: tuple[Source, ...] = (
    Source("agrovoc", "AGROVOC", hosts=("aims.fao.org",), homepage="https://agrovoc.fao.org/"),
    Source("dbpedia", "DBpedia", hosts=("dbpedia.org",), homepage="https://www.dbpedia.org/"),
    Source("wikidata", "Wikidata", hosts=("wikidata.org",), homepage="https://www.wikidata.org/"),
    Source("off", "OpenFoodFacts", uri_prefixes=("off:",), homepage="https://world.openfoodfacts.org/"),
    Source(
        "gpt",
        "Google Product Taxonomy",
        uri_prefixes=("gpt:",),
        homepage="https://www.google.com/basepages/producttype/taxonomy-with-ids.en-US.txt",
    ),
    Source(
        "tingbok",
        "Tingbok",
        hosts=("tingbok.plann.no",),
        homepage="https://tingbok.plann.no/",
        is_self=True,
    ),
)

#: The registry in force for this process.  Replaced wholesale by a successful
#: :func:`refresh_registry_from_tingbok`.
_registry: tuple[Source, ...] = BUNDLED_SOURCES


def reset_registry() -> None:
    """Drop any fetched registry and go back to :data:`BUNDLED_SOURCES`."""
    global _registry
    _registry = BUNDLED_SOURCES


def get_registry() -> tuple[Source, ...]:
    """Return the source registry in force."""
    return _registry


def source_by_name(name: str) -> Source | None:
    """Return the registry entry called *name*, or ``None``."""
    for source in _registry:
        if source.name == name:
            return source
    return None


def source_label(name: str) -> str:
    """Return a human-readable label for the source called *name*.

    A source the registry does not know about — which is what an out-of-date
    bundled table looks like — gets its own name title-cased rather than
    nothing, so the category browser degrades to "Brreg" rather than to a blank.
    """
    source = source_by_name(name)
    return source.label if source else name.title()


def _host_matches(host: str, domain: str) -> bool:
    """True if *host* is *domain* or a subdomain of it, with a dot boundary."""
    host = host.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def uri_to_source(uri: str) -> str | None:
    """Return the name of the source *uri* belongs to, or ``None``.

    Unlike tingbok's function of the same name, tingbok's own concept URIs
    resolve to ``"tingbok"`` here — see the module docstring.
    """
    host = ""
    if "://" in uri:
        host = (urlsplit(uri).hostname or "").lower()
    for source in _registry:
        if source.uri_prefixes and uri.startswith(source.uri_prefixes):
            return source.name
        if host and any(_host_matches(host, domain) for domain in source.hosts):
            return source.name
    return None


def _sources_from_payload(payload: Any) -> tuple[Source, ...]:
    """Build a registry tuple from a ``GET /api/sources`` response body.

    Entries without a usable ``name`` are skipped rather than raising: a client
    should not fall over because tingbok grew a field it does not understand.
    """
    raw = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise ValueError("response has no 'sources' list")
    parsed: list[Source] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name or not isinstance(name, str):
            logger.debug("Skipping source entry with no name: %r", entry)
            continue
        prefixes = entry.get("uri_prefixes") or []
        hosts = entry.get("hosts") or []
        parsed.append(
            Source(
                name=name,
                label=entry.get("label") or name.title(),
                uri_prefixes=tuple(p for p in prefixes if isinstance(p, str)),
                hosts=tuple(h for h in hosts if isinstance(h, str)),
                homepage=entry.get("homepage"),
                is_self=bool(entry.get("is_self")),
            )
        )
    if not parsed:
        raise ValueError("no usable sources in response")
    return tuple(parsed)


def _cache_path(cache_dir: Path) -> Path:
    return cache_dir / "sources.json"


def _read_cache(cache_dir: Path) -> tuple[Source, ...] | None:
    try:
        entry = json.loads(_cache_path(cache_dir).read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(entry["cached_at"])
        age = datetime.now(timezone.utc) - cached_at.astimezone(timezone.utc)
        if age.days >= REGISTRY_CACHE_TTL_DAYS:
            return None
        return _sources_from_payload(entry)
    except Exception:  # noqa: BLE001 — a bad cache is a cache miss, nothing more
        return None


def _write_cache(cache_dir: Path, registry: tuple[Source, ...]) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_dir).write_text(
            json.dumps(
                {
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "sources": [
                        {
                            "name": s.name,
                            "label": s.label,
                            "uri_prefixes": list(s.uri_prefixes),
                            "hosts": list(s.hosts),
                            "homepage": s.homepage,
                            "is_self": s.is_self,
                        }
                        for s in registry
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not cache the source registry: %s", exc)


def refresh_registry_from_tingbok(
    url: str,
    session: niquests.Session | None = None,
    cache_dir: Path | None = None,
) -> bool:
    """Replace the process registry with tingbok's, if it can be had.

    Args:
        url: Base URL of the tingbok service.
        session: Optional ``niquests.Session`` to reuse.
        cache_dir: Where to keep the fetched list.  A cached list younger than
            :data:`REGISTRY_CACHE_TTL_DAYS` is used without a request.

    Returns:
        True if the registry now comes from tingbok — freshly fetched, read from
        a cache younger than the TTL, or computed in-process.  False leaves
        :data:`BUNDLED_SOURCES` — or whatever was already in force — untouched,
        which is the whole point of having a bundled copy: an unreachable
        tingbok must not blank out the source labels.

    Note the cache is consulted *before* the request, so a cached list means no
    HTTP call at all until it expires.  An in-process answer is never cached,
    so it never suppresses a later request.
    """
    global _registry

    if cache_dir is not None:
        cached = _read_cache(cache_dir)
        if cached is not None:
            _registry = cached
            return True

    try:
        import niquests  # noqa: PLC0415

        getter = session.get if session is not None else niquests.get
        response = getter(f"{url.rstrip('/')}/api/sources", timeout=5.0)
        response.raise_for_status()
        registry = _sources_from_payload(response.json())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not fetch the source registry from %s: %s", url, exc)
        payload = tingbok_embedded.call("get_sources")
        if payload is None:
            return False
        try:
            registry = _sources_from_payload({"sources": payload})
        except Exception as embedded_exc:  # noqa: BLE001
            logger.debug("In-process tingbok returned an unusable source list: %s", embedded_exc)
            return False
        # Deliberately not cached.  The whole point of fetching this list is
        # that a source added to tingbok reaches the client without a client
        # release; writing a locally-computed answer to the cache would suppress
        # the request for the whole TTL and defeat exactly that.
        _registry = registry
        return True

    _registry = registry
    if cache_dir is not None:
        _write_cache(cache_dir, registry)
    return True
