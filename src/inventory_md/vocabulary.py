"""
Local vocabulary management for SKOS-based category system.

Provides functions to:
- Load local vocabulary definitions from YAML files
- Merge local vocabularies with SKOS cache
- Build category trees for the UI
- Look up concepts by label (including altLabels)

Local vocabulary format (local-vocabulary.yaml):
    concepts:
      christmas-decorations:
        prefLabel: "Christmas decorations"
        altLabel: ["jul", "xmas", "julepynt"]
        broader: "seasonal/winter"

      boat-equipment:
        prefLabel: "Boat equipment"
        narrower:
          - "boat-equipment/safety"
          - "boat-equipment/navigation"

      boat-equipment/safety:
        prefLabel: "Safety equipment"
        altLabel: ["life vests", "flares"]

      seal:
        prefLabel: "Seal"
        altLabel: ["rubber seal", "gasket", "o-ring"]
        uri: "https://dbpedia.org/resource/Hermetic_seal"
        # source is always "local" unless explicitly overridden
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Caches keyed by (id(vocab), lang) — valid as long as the vocab dict is not mutated.
# Safe in normal use because the vocabulary dict is loaded once and lives for the
# process; short-lived dicts (mostly in tests) can however reuse a freed id() and
# get a stale hit — call clear_caches() between such uses.
_alias_map_cache: dict[tuple, dict[str, str]] = {}
_label_index_cache: dict[int, dict[str, str]] = {}


def clear_caches() -> None:
    """Drop the id()-keyed label/alias index caches.

    Only relevant when many short-lived vocabulary dicts are created in one
    process (e.g. a test suite), where a reused id() could otherwise return a
    cached index built for a different, already-collected dict.
    """
    _alias_map_cache.clear()
    _label_index_cache.clear()


if TYPE_CHECKING:
    import niquests

logger = logging.getLogger(__name__)

VIRTUAL_ROOT_ID = "_root"
CATEGORY_BY_SOURCE_ID = "category_by_source"

_EAN_CACHE_TTL_DAYS = 7
_LOOKUP_CACHE_TTL_DAYS = 7

# Human-friendly labels for known source identifiers
_SOURCE_LABELS: dict[str, str] = {
    "off": "OpenFoodFacts",
    "agrovoc": "AGROVOC",
    "dbpedia": "DBpedia",
    "wikidata": "Wikidata",
    "gpt": "Google Product Taxonomy",
    "tingbok": "Tingbok",
}


def _cache_read(path: Path, ttl_days: int) -> dict | None:
    """Read a JSON cache entry; return None if missing or expired."""
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(entry["cached_at"])
        age = datetime.now(timezone.utc) - cached_at.astimezone(timezone.utc)
        if age.days < ttl_days:
            return entry
    except Exception:  # noqa: BLE001
        pass
    return None


def _cache_write(path: Path, **fields: Any) -> None:
    """Write a JSON cache entry, adding a ``cached_at`` timestamp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"cached_at": datetime.now(timezone.utc).isoformat(), **fields}
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


class TingbokUnavailableError(RuntimeError):
    """Raised when the tingbok service cannot be reached or returns an error."""


# =============================================================================
# VOCABULARY FILE DISCOVERY
# =============================================================================


def find_vocabulary_files() -> list[Path]:
    """Find all vocabulary files, in merge order (lowest priority first).

    Searches in order:
    1. /etc/inventory-md/vocabulary.yaml
    2. ~/.config/inventory-md/vocabulary.yaml
    3. ./vocabulary.yaml or ./local-vocabulary.yaml (highest priority)

    The canonical package vocabulary is fetched from tingbok; use
    load_global_vocabulary(tingbok_url=...) for the full vocabulary.

    Returns:
        List of found vocabulary files. Files later in the list override earlier.
    """
    found_files: list[Path] = []
    vocab_filenames = ["vocabulary.yaml", "vocabulary.yml", "vocabulary.json"]
    # vocabulary.json is excluded from the CWD list because it is the generated
    # parse output; accepting it as input would cause a feedback loop.
    local_vocab_filenames = [
        "local-vocabulary.yaml",
        "local-vocabulary.yml",
        "local-vocabulary.json",
        "vocabulary.yaml",
        "vocabulary.yml",
    ]

    # 1. System-wide config (/etc/inventory-md/)
    etc_dir = Path("/etc/inventory-md")
    if etc_dir.exists():
        for filename in vocab_filenames:
            path = etc_dir / filename
            if path.exists():
                found_files.append(path)
                logger.debug("Found system vocabulary: %s", path)
                break

    # 2. User config (~/.config/inventory-md/)
    user_dir = Path.home() / ".config" / "inventory-md"
    if user_dir.exists():
        for filename in vocab_filenames:
            path = user_dir / filename
            if path.exists():
                found_files.append(path)
                logger.debug("Found user vocabulary: %s", path)
                break

    # 3. Current directory (highest priority) - also check local-vocabulary.*
    cwd = Path.cwd()
    for filename in local_vocab_filenames:
        path = cwd / filename
        if path.exists():
            found_files.append(path)
            logger.debug("Found local vocabulary: %s", path)
            break

    return found_files


def load_global_vocabulary(
    tingbok_url: str | None = None,
    skip_cwd: bool = False,
    session: niquests.Session | None = None,
) -> dict[str, Concept]:
    """Load and merge vocabulary from all standard locations.

    The canonical package vocabulary is fetched from tingbok (lowest priority).
    Local overrides from /etc/inventory-md/, ~/.config/inventory-md/, and the
    current directory are merged on top (highest priority last).

    Args:
        tingbok_url: URL of a running tingbok service. If provided, the package
            vocabulary is fetched from tingbok. If unreachable, no package-level
            concepts are loaded.
        skip_cwd: If True, skip vocabulary files found in the current working
            directory (useful when local vocab is loaded separately).

    Returns:
        Merged vocabulary dictionary mapping concept IDs to Concept objects.
    """
    merged: dict[str, Concept] = {}

    # Fetch package vocabulary from tingbok (lowest priority)
    if tingbok_url:
        pkg_vocab = fetch_vocabulary_from_tingbok(tingbok_url, session=session)
        if pkg_vocab:
            logger.info("Loaded %d concepts from tingbok (%s)", len(pkg_vocab), tingbok_url)
            merged.update(pkg_vocab)

    for vocab_path in find_vocabulary_files():
        try:
            if skip_cwd and vocab_path.parent == Path.cwd():
                continue
            vocab = load_local_vocabulary(vocab_path)
            logger.info("Loaded %d concepts from %s", len(vocab), vocab_path)
            # Later files override earlier ones
            merged.update(vocab)
        except Exception as e:
            logger.warning("Failed to load vocabulary from %s: %s", vocab_path, e)

    logger.info("Total vocabulary: %d concepts", len(merged))
    return merged


def fetch_vocabulary_from_tingbok(url: str, session: niquests.Session | None = None) -> dict[str, Concept]:
    """Fetch the package vocabulary from a running tingbok service.

    Args:
        url:     Base URL of the tingbok service (e.g. "https://tingbok.plann.no").
        session: Optional niquests.Session to reuse (enables HTTP/2 multiplexing).

    Returns:
        Dictionary mapping concept IDs to Concept objects with source="tingbok",
        or an empty dict if the service is unreachable or returns an error.
    """
    import niquests

    getter = session.get if session is not None else niquests.get
    base = url.rstrip("/")
    endpoint = f"{base}/api/vocabulary"
    try:
        response = getter(endpoint, timeout=5.0)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception as e:
        raise TingbokUnavailableError(f"Failed to fetch vocabulary from tingbok {endpoint}: {e}") from e

    concepts: dict[str, Concept] = {}
    for concept_id, raw in data.items():
        raw = dict(raw)  # shallow copy — avoid mutating the parsed response dict
        # tingbok uses "altLabel" (SKOS convention); Concept.from_dict expects "altLabels"
        raw["altLabels"] = raw.pop("altLabel", {})
        raw["id"] = concept_id
        raw["source"] = "tingbok"
        # Convert source_uris from list[str] → dict[str, str] (source name → URI)
        raw_source_uris: list[str] = raw.pop("source_uris", [])
        raw_source_paths: dict[str, str] = raw.pop("source_paths", {})
        raw_path_aliases: dict[str, list[str]] = raw.pop("path_aliases", {})
        try:
            concept = Concept.from_dict(raw)
            for u in raw_source_uris:
                src = _uri_to_source(u)
                if src and src not in concept.source_uris:
                    concept.source_uris[src] = u
            concept.source_paths = raw_source_paths
            concept.path_aliases = raw_path_aliases
            concepts[concept_id] = concept
        except Exception as e:
            logger.warning("Skipping malformed concept '%s' from tingbok: %s", concept_id, e)

    return concepts


def resolve_vocabulary_from_tingbok(
    labels: list[str],
    url: str,
    lang: str = "en",
    session: niquests.Session | None = None,
) -> dict[str, Concept]:
    """Resolve inventory category labels via POST /api/vocabulary/resolve.

    Returns a vocabulary that covers all requested labels plus their ancestors.
    Labels not found in tingbok's vocabulary come back as inventory-sourced stubs.
    Prefer this over :func:`fetch_vocabulary_from_tingbok` when you already know
    which labels the inventory uses: one round-trip, tailored result.
    """
    import niquests  # noqa: PLC0415

    poster = session.post if session is not None else niquests.post
    base = url.rstrip("/")
    endpoint = f"{base}/api/vocabulary/resolve"
    try:
        response = poster(endpoint, json={"labels": labels, "lang": lang}, timeout=60.0)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
    except Exception as e:
        raise TingbokUnavailableError(f"Failed to resolve vocabulary from tingbok {endpoint}: {e}") from e

    concepts: dict[str, Concept] = {}
    for concept_id, raw in data.get("concepts", {}).items():
        raw = dict(raw)
        raw["altLabels"] = raw.pop("altLabel", {})
        raw["id"] = concept_id
        # Stubs returned for unknown labels have no source_uris → mark as inventory
        raw_source_uris: list[str] = raw.pop("source_uris", [])
        raw["source"] = "tingbok" if raw_source_uris else "inventory"
        raw_source_paths: dict[str, str] = raw.pop("source_paths", {})
        raw_path_aliases: dict[str, list[str]] = raw.pop("path_aliases", {})
        try:
            concept = Concept.from_dict(raw)
            for u in raw_source_uris:
                src = _uri_to_source(u)
                if src and src not in concept.source_uris:
                    concept.source_uris[src] = u
            concept.source_paths = raw_source_paths
            concept.path_aliases = raw_path_aliases
            concepts[concept_id] = concept
        except Exception as e:
            logger.warning("Skipping malformed concept '%s' from tingbok resolve: %s", concept_id, e)

    return concepts


@dataclass
class Concept:
    """A SKOS concept with labels and hierarchy."""

    id: str  # Unique identifier (path like "food/vegetables/potatoes")
    prefLabel: str  # Preferred display label (primary language)
    altLabels: dict[str, list[str]] = field(default_factory=dict)  # lang -> alternative labels
    broader: list[str] = field(default_factory=list)  # Parent concept IDs
    narrower: list[str] = field(default_factory=list)  # Child concept IDs
    source: str = "local"  # "local", "agrovoc", "dbpedia"
    uri: str | None = None  # Original SKOS URI (for external linking)
    labels: dict[str, str] = field(default_factory=dict)  # lang -> prefLabel translations
    description: str | None = None  # Short description (from Wikipedia/DBpedia)
    wikipediaUrl: str | None = None  # Link to Wikipedia article
    descriptions: dict[str, str] = field(default_factory=dict)  # lang -> description
    source_uris: dict[str, str] = field(default_factory=dict)  # source name -> URI
    source_paths: dict[str, str] = field(default_factory=dict)  # source name -> tingbok-normalised path
    excluded_sources: list[str] = field(default_factory=list)  # sources checked and rejected
    path_aliases: dict[str, list[str]] = field(default_factory=dict)  # lang -> [alias paths]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "prefLabel": self.prefLabel,
            "altLabels": self.altLabels,
            "broader": self.broader,
            "narrower": self.narrower,
            "source": self.source,
        }
        if self.uri:
            result["uri"] = self.uri
        if self.labels:
            result["labels"] = self.labels
        if self.description:
            result["description"] = self.description
        if self.wikipediaUrl:
            result["wikipediaUrl"] = self.wikipediaUrl
        if self.descriptions:
            result["descriptions"] = self.descriptions
        if self.source_uris:
            result["source_uris"] = self.source_uris
        if self.excluded_sources:
            result["excluded_sources"] = self.excluded_sources
        return result

    def get_label(self, lang: str) -> str:
        """Get label for a specific language, falling back to prefLabel."""
        return self.labels.get(lang, self.prefLabel)

    def get_alt_labels(self, lang: str | None = None) -> list[str]:
        """Get altLabels for a specific language, or all if lang is None."""
        if lang is None:
            seen: set[str] = set()
            result: list[str] = []
            for labels in self.altLabels.values():
                for label in labels:
                    if label not in seen:
                        seen.add(label)
                        result.append(label)
            return result
        return list(self.altLabels.get(lang, []))

    def get_all_alt_labels_flat(self) -> list[str]:
        """All altLabels across all languages (deduplicated)."""
        return self.get_alt_labels(lang=None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Concept:
        """Create from dictionary."""
        raw_alt = data.get("altLabels", {})
        if isinstance(raw_alt, list):
            alt_labels = {"en": raw_alt} if raw_alt else {}
        elif isinstance(raw_alt, dict):
            alt_labels = raw_alt
        else:
            alt_labels = {}
        return cls(
            id=data["id"],
            prefLabel=data.get("prefLabel", data["id"]),
            altLabels=alt_labels,
            broader=data.get("broader", []),
            narrower=data.get("narrower", []),
            source=data.get("source", "local"),
            uri=data.get("uri"),
            labels=data.get("labels", {}),
            description=data.get("description"),
            wikipediaUrl=data.get("wikipediaUrl"),
            descriptions=data.get("descriptions", {}),
            source_uris=data.get("source_uris", {}),
            excluded_sources=data.get("excluded_sources", []),
        )


@dataclass
class CategoryTree:
    """Hierarchical tree structure for category browser UI."""

    concepts: dict[str, Concept]  # All concepts by ID
    roots: list[str]  # Top-level concept IDs (no broader)
    label_index: dict[str, str]  # Maps lowercase labels to concept IDs

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "concepts": {k: v.to_dict() for k, v in self.concepts.items()},
            "roots": self.roots,
            "labelIndex": self.label_index,
        }


def load_local_vocabulary(path: Path, default_source: str = "local") -> dict[str, Concept]:
    """Load local vocabulary from YAML or JSON file.

    Args:
        path: Path to local-vocabulary.yaml or local-vocabulary.json
        default_source: Default source for concepts without an explicit source
            field. Use "tingbok" for the bundled package vocabulary.

    Returns:
        Dictionary mapping concept IDs to Concept objects.
    """
    if not path.exists():
        logger.debug("Local vocabulary file not found: %s", path)
        return {}

    try:
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as e:
                raise ImportError(
                    "PyYAML required for .yaml vocabulary files. Install with: pip install inventory-md[yaml]"
                ) from e
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
    except Exception as e:
        logger.warning("Failed to load vocabulary from %s: %s", path, e)
        return {}

    concepts_data = data.get("concepts", {})
    concepts = {}

    for concept_id, concept_data in concepts_data.items():
        if concept_data is None:
            concept_data = {}

        # Handle altLabels as string, list, or dict.  Hand-written YAML uses the
        # singular "altLabel"; machine-generated vocabulary.json (Concept.to_dict)
        # uses the plural "altLabels" — accept either (preferring the plural).
        raw_alt = concept_data.get("altLabels")
        if raw_alt is None:
            raw_alt = concept_data.get("altLabel", {})
        if isinstance(raw_alt, str):
            alt_labels = {"en": [raw_alt]}
        elif isinstance(raw_alt, list):
            alt_labels = {"en": raw_alt} if raw_alt else {}
        elif isinstance(raw_alt, dict):
            alt_labels = {k: ([v] if isinstance(v, str) else v) for k, v in raw_alt.items()}
        else:
            alt_labels = {}

        # Handle broader as string or list
        broader = concept_data.get("broader", [])
        if isinstance(broader, str):
            broader = [broader]

        # Handle narrower as string or list
        narrower = concept_data.get("narrower", [])
        if isinstance(narrower, str):
            narrower = [narrower]

        # Handle labels dict for translations
        labels = concept_data.get("labels", {})

        # The URI is just metadata for enrichment (translations, descriptions)
        # not an indication of where the concept definition comes from
        uri = concept_data.get("uri")
        source = concept_data.get("source", default_source)

        concepts[concept_id] = Concept(
            id=concept_id,
            prefLabel=concept_data.get("prefLabel", concept_id),
            altLabels=alt_labels,
            broader=broader,
            narrower=narrower,
            source=source,
            uri=uri,
            labels=labels,
            description=concept_data.get("description"),
        )

    create_broader_stubs(concepts)
    return concepts


def merge_vocabularies(local: dict[str, Concept], base: dict[str, Concept]) -> dict[str, Concept]:
    """Merge local vocabulary with a base vocabulary.

    Local vocabulary takes precedence over base concepts.

    Args:
        local: Local vocabulary concepts (higher priority).
        base: Base vocabulary concepts (lower priority).

    Returns:
        Merged vocabulary with local concepts taking precedence.
    """
    merged = base.copy()
    merged.update(local)  # Local overrides base
    return merged


def build_label_index(concepts: dict[str, Concept]) -> dict[str, str]:
    """Build an index mapping all labels to concept IDs.

    Includes prefLabel and all altLabels, lowercased for case-insensitive lookup.
    Result is cached by dict identity — valid as long as concepts is not mutated.

    Args:
        concepts: Dictionary of concepts.

    Returns:
        Dictionary mapping lowercase labels to concept IDs.
    """
    key = id(concepts)
    if key in _label_index_cache:
        return _label_index_cache[key]
    index = {}
    for concept_id, concept in concepts.items():
        index[concept.prefLabel.lower()] = concept_id
        for alt_label in concept.get_all_alt_labels_flat():
            index[alt_label.lower()] = concept_id
        index[concept_id.lower()] = concept_id
    _label_index_cache[key] = index
    return index


def lookup_concept(label: str, vocabulary: dict[str, Concept]) -> Concept | None:
    """Look up a concept by label (prefLabel or altLabel).

    Args:
        label: Label to search for (case-insensitive).
        vocabulary: Dictionary of concepts.

    Returns:
        Concept if found, None otherwise.
    """
    label_lower = label.lower()

    # First, check if label matches a concept ID directly
    if label in vocabulary:
        return vocabulary[label]

    # Build label index and search
    index = build_label_index(vocabulary)
    concept_id = index.get(label_lower)

    if concept_id:
        return vocabulary.get(concept_id)

    return None


def is_descendant_of(
    concept_id: str,
    ancestor_id: str,
    vocabulary: dict[str, Concept],
    _visited: set[str] | None = None,
) -> bool:
    """Return True if ``concept_id`` is ``ancestor_id`` or a transitive descendant of it.

    Walks ``broader`` links upward, following every parent (concepts may have
    multiple broader parents). Used e.g. to decide whether a category is a kind
    of ``food``. Category matching is a general problem, so it lives here rather
    than in individual consumers (shopping list, expiry report, ...).
    """
    if concept_id == ancestor_id:
        return True
    visited = _visited if _visited is not None else set()
    if concept_id in visited:
        return False
    visited.add(concept_id)
    concept = vocabulary.get(concept_id)
    if not concept:
        return False
    return any(is_descendant_of(b, ancestor_id, vocabulary, visited) for b in concept.broader)


def _infer_hierarchy(concepts: dict[str, Concept]) -> None:
    """Infer hierarchy relationships from concept IDs with path separators.

    For concepts like "food/vegetables/potatoes", automatically adds:
    - broader: ["food/vegetables"] (if not already set from SKOS)
    - narrower: ["food/vegetables/potatoes"] to parent (always)

    Modifies concepts in place.

    Args:
        concepts: Dictionary of concepts to update.
    """
    # Sort by path depth to process parents before children
    concept_ids = sorted(concepts.keys(), key=lambda x: x.count("/"))

    for concept_id in concept_ids:
        concept = concepts[concept_id]

        # Infer parent from path
        if "/" in concept_id:
            parent_id = "/".join(concept_id.split("/")[:-1])
            if parent_id and parent_id in concepts:
                # Set broader if not already set from SKOS
                if not concept.broader:
                    concept.broader = [parent_id]
                # ALWAYS add this concept to parent's narrower list
                # This ensures the path hierarchy is preserved for navigation
                parent = concepts[parent_id]
                if concept_id not in parent.narrower:
                    parent.narrower.append(concept_id)


def create_broader_stubs(concepts: dict[str, Concept]) -> None:
    """Create stub Concept nodes for broader references pointing to non-existent IDs.

    Handles Wikidata taxonomy paths (e.g. "primary_commodity/raw_material/oil/cooking_oil")
    that appear in broader lists but have no corresponding concept entry.  All ancestor
    segments of each missing path are also created so the hierarchy is fully traversable.

    Modifies concepts in place.
    """
    to_create: set[str] = set()
    for concept in concepts.values():
        for broader_id in concept.broader:
            if broader_id not in concepts:
                to_create.add(broader_id)
                parts = broader_id.split("/")
                for i in range(1, len(parts)):
                    anc = "/".join(parts[:i])
                    if anc not in concepts:
                        to_create.add(anc)

    for stub_id in sorted(to_create, key=lambda x: x.count("/")):
        label = stub_id.split("/")[-1].replace("_", " ").title()
        broader = ["/".join(stub_id.split("/")[:-1])] if "/" in stub_id else []
        concepts[stub_id] = Concept(
            id=stub_id,
            prefLabel=label,
            broader=broader,
            source="inferred",
        )

    # Link all narrower references so the hierarchy is navigable
    for concept in list(concepts.values()):
        for broader_id in concept.broader:
            parent = concepts.get(broader_id)
            if parent is not None and concept.id not in parent.narrower:
                parent.narrower.append(concept.id)


def _ensure_source_path_node(
    node_id: str,
    concepts: dict[str, Concept],
    label: str,
    broader: str,
) -> None:
    """Ensure a virtual intermediate node exists, creating it if needed."""
    if node_id not in concepts:
        concepts[node_id] = Concept(
            id=node_id,
            prefLabel=label,
            narrower=[],
            broader=[broader],
            source="inventory",
        )


def _add_category_by_source_nodes(concepts: dict[str, Concept]) -> None:
    """Dynamically add ``category_by_source`` virtual nodes to *concepts* in-place.

    For sources that provide a ``source_paths`` path (e.g. GPT), proper
    intermediate nodes are created so the concept appears at the right depth
    in the source subtree rather than as a spurious root-level child.
    For sources without path information, the concept is added directly under
    the source node (flat list, as before).

    Concepts whose ID already starts with ``category_by_source`` are skipped so
    that repeated calls are idempotent.
    """
    source_node_ids: set[str] = set()

    for cid, concept in list(concepts.items()):
        if cid.startswith(CATEGORY_BY_SOURCE_ID):
            continue
        for src in concept.source_uris:
            src_root = f"{CATEGORY_BY_SOURCE_ID}/{src}"
            source_node_ids.add(src_root)
            src_path = concept.source_paths.get(src)

            if src_path and "/" in src_path:
                # Build intermediate virtual nodes along the source path.
                # Prefix all nodes with category_by_source/{src}/ so they
                # don't collide with the main vocabulary tree.
                parts = src_path.split("/")
                for depth in range(1, len(parts)):
                    segment = parts[depth - 1]
                    node_id = src_root + "/" + "/".join(parts[:depth])
                    parent_id = src_root if depth == 1 else src_root + "/" + "/".join(parts[: depth - 1])
                    _ensure_source_path_node(node_id, concepts, segment.replace("_", " ").title(), parent_id)
                    source_node_ids.add(node_id)

                # The leaf: place cid under the deepest intermediate node
                leaf_parent_id = src_root + "/" + "/".join(parts[:-1])
                parent_node = concepts[leaf_parent_id]
                if cid not in parent_node.narrower:
                    parent_node.narrower.append(cid)
            else:
                # No path info — fall back to flat list directly under source node
                _ensure_source_path_node(
                    src_root,
                    concepts,
                    _SOURCE_LABELS.get(src, src.title()),
                    CATEGORY_BY_SOURCE_ID,
                )
                src_node = concepts[src_root]
                if cid not in src_node.narrower:
                    src_node.narrower.append(cid)

    if not source_node_ids:
        return

    # Ensure top-level source nodes have correct label/broader
    for src_root in source_node_ids:
        if src_root.count("/") == 1:  # direct child of category_by_source
            src = src_root.split("/", 1)[1]
            _ensure_source_path_node(
                src_root,
                concepts,
                _SOURCE_LABELS.get(src, src.title()),
                CATEGORY_BY_SOURCE_ID,
            )

    direct_source_roots = sorted(n for n in source_node_ids if n.count("/") == 1)
    concepts[CATEGORY_BY_SOURCE_ID] = Concept(
        id=CATEGORY_BY_SOURCE_ID,
        prefLabel="Category by Source",
        narrower=direct_source_roots,
        source="inventory",
    )


def _break_narrower_cycles(concepts: dict[str, Concept]) -> None:
    """Remove cycles from the ``narrower`` graph so the UI tree is a DAG.

    Some upstream sources (notably tingbok) serve contradictory SKOS relations
    where a concept lists another -- or itself -- in *both* ``broader`` and
    ``narrower`` (e.g. ``lentil`` with ``narrower == broader == ["lentil"]``, or
    the ``rope`` <-> ``rope/cord`` pair).  The search.html category tree walks
    ``narrower`` recursively, so such cycles caused infinite recursion / a stack
    overflow ("Error loading data").

    This drops self-references and any ``narrower`` edge that closes a cycle
    (a back-edge in a DFS), keeping the first-seen edges.  The matching reverse
    ``broader`` entry is removed too, to keep the two relations consistent.
    """
    # 1. Strip self-references from both relations.
    for cid, concept in concepts.items():
        if cid in concept.narrower:
            concept.narrower = [n for n in concept.narrower if n != cid]
        if cid in concept.broader:
            concept.broader = [b for b in concept.broader if b != cid]

    # 2. Find back-edges in the narrower graph via DFS (iterative, to avoid
    #    Python recursion limits on deep vocabularies), then remove them.
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(concepts, WHITE)
    back_edges: list[tuple[str, str]] = []

    def visit(root: str) -> None:
        # Stack holds [node, index-of-next-child-to-process].
        stack: list[list] = [[root, 0]]
        color[root] = GREY
        while stack:
            node, idx = stack[-1]
            children = concepts[node].narrower
            if idx >= len(children):
                color[node] = BLACK
                stack.pop()
                continue
            stack[-1][1] = idx + 1
            child = children[idx]
            if child not in concepts:
                continue
            if color[child] == GREY:
                back_edges.append((node, child))  # closes a cycle
            elif color[child] == WHITE:
                color[child] = GREY
                stack.append([child, 0])

    for cid in concepts:
        if color[cid] == WHITE:
            visit(cid)

    for node, child in back_edges:
        concepts[node].narrower = [c for c in concepts[node].narrower if c != child]
        concepts[child].broader = [b for b in concepts[child].broader if b != node]


def build_category_tree(vocabulary: dict[str, Concept], infer_hierarchy: bool = True) -> CategoryTree:
    """Build a category tree structure for the UI.

    Args:
        vocabulary: Dictionary of concepts.
        infer_hierarchy: If True, infer parent/child relationships from paths.

    Returns:
        CategoryTree with roots and label index.
    """
    # Make a copy to avoid modifying the original
    concepts = {
        k: Concept(
            id=v.id,
            prefLabel=v.prefLabel,
            altLabels={lang: ls.copy() for lang, ls in v.altLabels.items()},
            broader=v.broader.copy(),
            narrower=v.narrower.copy(),
            source=v.source,
            uri=v.uri,
            labels=v.labels.copy() if v.labels else {},
            description=v.description,
            wikipediaUrl=v.wikipediaUrl,
            descriptions=v.descriptions.copy() if v.descriptions else {},
            source_uris=v.source_uris.copy() if v.source_uris else {},
            source_paths=v.source_paths.copy() if v.source_paths else {},
            path_aliases={lang: list(aliases) for lang, aliases in v.path_aliases.items()},
        )
        for k, v in vocabulary.items()
    }

    if infer_hierarchy:
        _infer_hierarchy(concepts)

    create_broader_stubs(concepts)
    _add_category_by_source_nodes(concepts)
    _break_narrower_cycles(concepts)

    # Find roots - concepts that should appear at the top level of the tree
    if VIRTUAL_ROOT_ID in concepts:
        # Virtual root defines explicit roots via its narrower list.
        # This is a whitelist: only concepts named in _root.narrower appear at
        # the top of the tree.  External/orphaned concepts are excluded.
        virtual_root = concepts[VIRTUAL_ROOT_ID]
        roots = [cid for cid in virtual_root.narrower if cid in concepts]
        del concepts[VIRTUAL_ROOT_ID]
    else:
        # Fallback: infer roots from concepts with no broader and no "/"
        roots = [cid for cid, c in concepts.items() if "/" not in cid and not c.broader]
        roots.sort(key=lambda x: concepts[x].prefLabel.lower())

    # Build label index
    label_index = build_label_index(concepts)

    return CategoryTree(
        concepts=concepts,
        roots=roots,
        label_index=label_index,
    )


def resolve_category(
    category: str,
    concepts: dict[str, Concept],
    lang: str = "en",
) -> str | None:
    """Resolve a raw category string to a canonical concept ID.

    Tries in order:
    1. Direct match as a known concept ID path (e.g. ``food/vegetables/potatoes``)
    2. Language-specific path alias (e.g. Norwegian ``klær/vinter`` → ``clothing/thermal``)
    3. Leaf name match — last path component of any concept ID (e.g. ``potatoes``)

    Does not do label/altLabel matching across languages; that belongs to
    the Tingbok vocabulary project.  Returns ``None`` if no match is found;
    the caller should fall back to using the raw category string.
    """
    cat_lower = category.lower()

    # 1. Direct concept ID
    if cat_lower in concepts:
        return cat_lower

    # 2. Language-specific path alias
    alias_map = _build_path_alias_map(concepts, lang)
    if cat_lower in alias_map:
        return alias_map[cat_lower]

    # 3. Leaf name lookup (last path component of concept ID)
    for concept_id in concepts:
        if concept_id.startswith(CATEGORY_BY_SOURCE_ID + "/"):
            continue
        if concept_id.split("/")[-1] == cat_lower:
            return concept_id

    # 4. prefLabel / altLabel index.  Tingbok folds synonym and singular/plural
    # variants of a category into the canonical concept's altLabels (e.g.
    # food/vegetables carries "vegetable"), so a raw category string that is a
    # synonym resolves to the canonical concept.  Reuses the same label index as
    # lookup_concept rather than re-implementing label matching here.
    matched = build_label_index(concepts).get(cat_lower)
    if matched is not None and not matched.startswith(CATEGORY_BY_SOURCE_ID):
        return matched

    return None


def _build_path_alias_map(vocab: dict[str, Concept], lang: str) -> dict[str, str]:
    """Build a reverse map from alias path (lower) to canonical concept ID.

    Considers only aliases for the given language (treating 'no'/'nb'/'nn' as
    equivalent since they all refer to varieties of Norwegian).
    Result is cached by (id(vocab), lang) — valid as long as vocab is not mutated.
    """
    cache_key = (id(vocab), lang)
    if cache_key in _alias_map_cache:
        return _alias_map_cache[cache_key]

    _nb_langs = {"nb", "no", "nn"}

    def _matches(alias_lang: str) -> bool:
        if alias_lang == lang:
            return True
        return alias_lang in _nb_langs and lang in _nb_langs

    result: dict[str, str] = {}
    for concept_id, concept in vocab.items():
        for alias_lang, aliases in concept.path_aliases.items():
            if _matches(alias_lang):
                for alias in aliases:
                    result[alias.lower()] = concept_id
    _alias_map_cache[cache_key] = result
    return result


def _build_altlabel_index(vocab: dict[str, Concept], lang: str) -> dict[str, str]:
    """Build an index mapping lowercased altLabels (and language prefLabels) to concept IDs.

    Used to resolve inventory category root components written in a localised
    language (e.g. Norwegian ``klær``) to their canonical concept IDs (e.g.
    ``clothing``).

    Considers ``altLabels`` for the given language and also ``labels`` (per-
    language prefLabel translations).  Norwegian variants ``nb``/``no``/``nn``
    are treated as equivalent.

    Args:
        vocab: Vocabulary to index.
        lang: Target language code.

    Returns:
        Dictionary mapping lowercase label → concept ID.
    """
    _nb_langs = {"nb", "no", "nn"}

    def _matches(lcode: str) -> bool:
        return lcode == lang or (lcode in _nb_langs and lang in _nb_langs)

    index: dict[str, str] = {}
    for concept_id, concept in vocab.items():
        for alt_lang, labels in concept.altLabels.items():
            if _matches(alt_lang):
                for label in labels:
                    index[label.lower()] = concept_id
        for lbl_lang, label in concept.labels.items():
            if _matches(lbl_lang):
                index[label.lower()] = concept_id
    return index


def build_vocabulary_from_inventory(
    inventory_data: dict[str, Any],
    local_vocab: dict[str, Concept] | None = None,
    lang: str = "en",
) -> dict[str, Concept]:
    """Build vocabulary from categories used in inventory data.

    Scans all items in inventory for category: metadata and creates concepts
    for each unique category path found.  Resolution order for each path:

    1. **Full path_alias** — if the whole path matches a language-specific
       ``path_aliases`` entry, redirect to the canonical concept (e.g.
       ``klær/vinter`` → ``clothing/thermal``).
    2. **Root altLabel** — if the *first* path component is a language-specific
       altLabel or translated prefLabel of a known concept, the sub-path is
       created as inventory-local concepts wired under that canonical parent
       (e.g. ``klær/jakke`` with ``clothing.altLabels.nb = ["klær"]`` creates
       concept ``klær/jakke`` with ``broader = ["clothing"]``, no ``klær``
       node).
    3. **Verbatim** — the path is added as-is, creating inventory-local concepts.

    Args:
        inventory_data: Parsed inventory JSON data.
        local_vocab: Optional local vocabulary to merge with.
        lang: Inventory language used to match path aliases and altLabels.

    Returns:
        Dictionary of concepts from inventory categories.
    """
    concepts: dict[str, Concept] = {}

    # Start with local vocabulary if provided
    if local_vocab:
        concepts.update(local_vocab)

    # Build resolution maps for the inventory language
    alias_map = _build_path_alias_map(concepts, lang)
    altlabel_index = _build_altlabel_index(concepts, lang)

    # Add all category paths from inventory items
    for container in inventory_data.get("containers", []):
        for item in container.get("items", []):
            for category_path in item.get("metadata", {}).get("categories", []):
                path_lower = category_path.lower()

                # 1. Full path_alias wins
                canonical = alias_map.get(path_lower)
                if canonical:
                    _add_category_path(concepts, canonical)
                    continue

                # 2. Root altLabel resolution
                root = path_lower.split("/")[0]
                canonical_root = altlabel_index.get(root)
                if canonical_root:
                    _add_category_path(concepts, category_path, root_alias=canonical_root)
                    continue

                # 3. Verbatim
                _add_category_path(concepts, category_path)

    return concepts


def _add_category_path(
    concepts: dict[str, Concept],
    path: str,
    root_alias: str | None = None,
) -> None:
    """Add a category path and all its parent paths to concepts.

    For "food/vegetables/potatoes", adds:
    - "food"
    - "food/vegetables"
    - "food/vegetables/potatoes"

    When *root_alias* is given, the first path component is treated as an
    alias for an existing canonical concept (e.g. ``klær`` → ``clothing``).
    In that case:

    - No concept is created for the first component (``klær``).
    - The immediate child (``klær/jakke``) is created with
      ``broader = [root_alias]`` and added to ``root_alias.narrower``.
    - Deeper levels (``klær/jakke/barn``) follow normal path inference.

    Args:
        concepts: Dictionary to add concepts to.
        path: Category path to add.
        root_alias: Canonical concept ID that the first path component aliases.
    """
    parts = path.split("/")

    for i in range(len(parts)):
        # Skip creating a concept for the aliased root component
        if i == 0 and root_alias is not None:
            continue

        concept_id = "/".join(parts[: i + 1])
        if concept_id not in concepts:
            # Create a concept with default prefLabel from the last part
            concepts[concept_id] = Concept(
                id=concept_id,
                prefLabel=parts[i].replace("-", " ").replace("_", " ").title(),
                source="inventory",
            )

            # Wire the direct child of the aliased root to the canonical parent
            if i == 1 and root_alias is not None:
                concepts[concept_id].broader = [root_alias]
                if root_alias in concepts and concept_id not in concepts[root_alias].narrower:
                    concepts[root_alias].narrower.append(concept_id)


def save_vocabulary_json(
    vocabulary: dict[str, Concept],
    output_path: Path,
    category_mappings: dict[str, list[str]] | None = None,
) -> None:
    """Save vocabulary as JSON file for search.html.

    Args:
        vocabulary: Dictionary of concepts.
        output_path: Path to write vocabulary.json.
        category_mappings: Optional mapping from simple labels to expanded paths.
                          Used for SKOS hierarchy mode to enable search expansion.
    """
    tree = build_category_tree(vocabulary)
    output_data = tree.to_dict()

    # Include category mappings if provided (for SKOS hierarchy mode)
    if category_mappings:
        output_data["categoryMappings"] = category_mappings

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def count_items_per_category(inventory_data: dict[str, Any]) -> dict[str, int]:
    """Count items in each category (including items in child categories).

    Args:
        inventory_data: Parsed inventory JSON data.

    Returns:
        Dictionary mapping category paths to item counts.
    """
    counts: dict[str, int] = {}

    for container in inventory_data.get("containers", []):
        for item in container.get("items", []):
            categories = item.get("metadata", {}).get("categories", [])
            for category_path in categories:
                # Count the category itself
                counts[category_path] = counts.get(category_path, 0) + 1
                # Also count all parent categories
                parts = category_path.split("/")
                for i in range(len(parts) - 1):
                    parent_path = "/".join(parts[: i + 1])
                    counts[parent_path] = counts.get(parent_path, 0) + 1

    return counts


def resolve_categories_via_tingbok(
    unknown_labels: list[str],
    tingbok_url: str,
    lang: str = "en",
    sources: list[str] | None = None,
    session: niquests.Session | None = None,
) -> tuple[dict[str, Concept], dict[str, list[str]]]:
    """Resolve unknown category labels to hierarchy paths via tingbok.

    For each label, queries tingbok's ``/api/skos/hierarchy`` endpoint across
    multiple SKOS sources.  Stops at the first source that finds the concept.

    Args:
        unknown_labels: Category labels to resolve (e.g. ``["cumin", "bouillon"]``).
        tingbok_url:    Base URL of the tingbok service.
        lang:           BCP-47 language code for label matching.
        sources:        SKOS sources to try, in order.  Defaults to
                        ``["agrovoc", "dbpedia", "wikidata"]``.

    Returns:
        Tuple of:

        * *new_concepts* — ``dict[str, Concept]`` for all resolved path
          segments (including intermediate paths like ``"food/spices"``).
        * *category_mappings* — ``{label_lower: [path, ...]}`` for each
          successfully resolved label.
    """
    import niquests

    getter = session.get if session is not None else niquests.get
    if sources is None:
        sources = ["agrovoc", "dbpedia", "wikidata"]

    base = tingbok_url.rstrip("/")
    new_concepts: dict[str, Concept] = {}
    category_mappings: dict[str, list[str]] = {}

    for label in unknown_labels:
        for source in sources:
            try:
                response = getter(
                    f"{base}/api/skos/hierarchy",
                    params={"label": label, "lang": lang, "source": source},
                    timeout=5.0,
                )
                response.raise_for_status()
                data: dict = response.json()
            except Exception as exc:
                logger.debug("Category resolution failed for '%s' via %s: %s", label, source, exc)
                continue

            if data.get("found") and data.get("paths"):
                paths: list[str] = data["paths"]
                category_mappings[label.lower()] = paths
                for path in paths:
                    _add_category_path(new_concepts, path)
                break  # Found in this source — skip remaining sources

    return new_concepts, category_mappings


def enrich_categories_via_lookup(
    labels: list[str],
    tingbok_url: str,
    lang: str = "en",
    session: niquests.Session | None = None,
    cache_dir: Path | None = None,
) -> tuple[dict[str, Concept], dict[str, list[str]]]:
    """Enrich category concepts via ``GET /api/lookup/{label}``.

    Works for both bare labels (e.g. ``"cumin"``) and full paths (e.g.
    ``"food/spices/cumin"``).  All SKOS sources are queried in parallel by
    tingbok and the results merged, so the returned concepts carry translations,
    altLabels, descriptions, and source URIs from every available source.

    Args:
        labels:      Category IDs or bare labels to look up.
        tingbok_url: Base URL of the tingbok service.
        lang:        Preferred language for the lookup request.
        session:     Optional niquests.Session to reuse (enables HTTP/2 multiplexing).
        cache_dir:   Directory for the client-side lookup cache.  Successful
                     results are cached for :data:`_LOOKUP_CACHE_TTL_DAYS` days.
                     Pass ``None`` to disable (default).

    Returns:
        Tuple of:

        * *new_concepts* — enriched ``dict[str, Concept]`` for all resolved labels
          and their path segments (e.g. ``"food"``, ``"food/spices"``, ``"food/spices/cumin"``).
        * *category_mappings* — ``{label_lower: [path]}`` for bare labels that
          resolved to a different concept ID (used for search expansion).
    """
    import niquests

    getter = session.get if session is not None else niquests.get
    base = tingbok_url.rstrip("/")
    new_concepts: dict[str, Concept] = {}
    category_mappings: dict[str, list[str]] = {}

    total = len(labels)
    for i, label in enumerate(labels, 1):
        print(f"   [{i}/{total}] Looking up {label!r} ...", end=" ", flush=True)
        # Normalize the query label for SKOS sources: use the leaf node of a path,
        # replace hyphens with spaces, and strip OFF-style language tag prefixes
        # (e.g. "en:mashed-vegetables" → "mashed vegetables", "sk:džem" → "džem").
        query_label = label.split("/")[-1].replace("-", " ").replace("_", " ").strip()
        query_label = re.sub(r"^[a-z]{2,3}:", "", query_label)
        if not query_label:
            query_label = label

        data: dict | None = None
        if cache_dir is not None:
            cache_key = re.sub(r"[^\w.-]", "_", query_label)
            cache_path = cache_dir / f"lookup_{cache_key}.json"
            entry = _cache_read(cache_path, _LOOKUP_CACHE_TTL_DAYS)
            if entry is not None:
                data = entry.get("data")
                print("(cached)", end=" ", flush=True)

        if data is None:
            try:
                response = getter(f"{base}/api/lookup/{query_label}", params={"lang": lang}, timeout=120.0)
                if response.status_code == 404:
                    print("not found")
                    logger.debug("No lookup result for %r", label)
                    if cache_dir is not None:
                        _cache_write(cache_path, data=None)
                    continue
                response.raise_for_status()
                data = response.json()
                if cache_dir is not None:
                    _cache_write(cache_path, data=data)
            except Exception as exc:
                print(f"error: {exc}")
                logger.debug("Concept lookup failed for %r: %s", label, exc)
                continue

        concept_id: str = data.get("id", label)
        print(f"→ {concept_id}")

        # Convert VocabularyConcept format → Concept (same as fetch_vocabulary_from_tingbok)
        data["altLabels"] = data.pop("altLabel", {})
        data["id"] = concept_id
        data["source"] = "tingbok"
        raw_source_uris: list[str] = data.pop("source_uris", [])
        try:
            concept = Concept.from_dict(data)
        except Exception as exc:
            logger.warning("Skipping malformed lookup response for %r: %s", label, exc)
            continue
        for u in raw_source_uris:
            src = _uri_to_source(u)
            if src and src not in concept.source_uris:
                concept.source_uris[src] = u

        # Ensure all path segments exist (unenriched stubs for intermediates)
        _add_category_path(new_concepts, concept_id)
        # Overwrite the leaf with the fully enriched concept
        new_concepts[concept_id] = concept

        # Record mapping if a bare label resolved to a different (path-based) ID
        if label.lower() != concept_id.lower() and "/" not in label:
            category_mappings[label.lower()] = [concept_id]

    return new_concepts, category_mappings


def lookup_ean_via_tingbok(
    ean: str,
    tingbok_url: str,
    session: niquests.Session | None = None,
    cache_dir: Path | None = None,
) -> dict | None:
    """Look up a product by EAN via the tingbok service.

    Queries ``GET {tingbok_url}/api/ean/{ean}`` and returns the parsed JSON
    response dict (compatible with ``tingbok.models.ProductResponse``) or
    ``None`` on 404 or network failure.

    When *cache_dir* is provided, successful responses are cached for
    :data:`_EAN_CACHE_TTL_DAYS` days so repeat runs avoid unnecessary network
    calls.

    Args:
        ean:         EAN/UPC barcode string.
        tingbok_url: Base URL of the tingbok service.
        session:     Optional niquests.Session to reuse (enables HTTP/2 multiplexing).
        cache_dir:   Directory for the client-side EAN cache.  Pass ``None``
                     to disable caching (default).

    Returns:
        Product dict with keys ``ean``, ``name``, ``brand``, ``quantity``,
        ``categories``, ``image_url``, ``source`` — or ``None``.
    """
    import niquests

    if cache_dir is not None:
        cache_path = cache_dir / f"{ean}.json"
        entry = _cache_read(cache_path, _EAN_CACHE_TTL_DAYS)
        if entry is not None:
            return entry.get("data")  # None means 404 was cached

    getter = session.get if session is not None else niquests.get
    base = tingbok_url.rstrip("/")
    try:
        response = getter(f"{base}/api/ean/{ean}", timeout=5.0)
        if response.status_code == 404:
            if cache_dir is not None:
                _cache_write(cache_dir / f"{ean}.json", data=None)
            return None
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.debug("EAN lookup failed for %s: %s", ean, exc)
        return None

    if cache_dir is not None:
        _cache_write(cache_dir / f"{ean}.json", data=data)
    return data


def ean_observation_needed(
    product: dict | None,
    categories: list[str],
    name: str | None,
    quantity: str | None,
    prices: list[dict] | None,
) -> bool:
    """Return True if a PUT is needed because *product* does not already reflect our observations.

    Compares the GET response from tingbok with what we would push.  A PUT is
    skipped when every piece of our inventory data is already present in the
    response — meaning a previous run already pushed it successfully.

    Args:
        product:    Result of :func:`lookup_ean_via_tingbok` (may be ``None``).
        categories: Category paths from the inventory.
        name:       Product name from the inventory (``None`` = unknown).
        quantity:   Weight/volume string (``None`` = unknown).
        prices:     Price observations to push (``None`` or empty = none).
    """
    if not categories and not name and not quantity and not prices:
        return False
    if product is None:
        return bool(categories or name or quantity or prices)

    existing_cats: list[str] = product.get("categories") or []
    if any(c not in existing_cats for c in categories):
        return True

    if quantity and quantity != product.get("quantity"):
        return True

    existing_prices: list[dict] = product.get("prices") or []

    # Compare on (currency, price, unit) only — date is omitted because inventory
    # rows are not new observations, and the date may differ from what the server
    # stored on a previous push.
    def _price_key(p: dict) -> tuple:
        return (p.get("currency"), p.get("price"), p.get("unit"))

    existing_keys = {_price_key(p) for p in existing_prices}
    if prices and any(_price_key(p) not in existing_keys for p in prices):
        return True

    return False


def report_ean_to_tingbok(
    ean: str,
    categories: list[str],
    name: str | None,
    tingbok_url: str,
    session: niquests.Session | None = None,
    quantity: str | None = None,
    prices: list[dict] | None = None,
    cache_dir: Path | None = None,
) -> None:
    """PUT inventory-sourced observations for *ean* to tingbok.

    Sends ``PUT {tingbok_url}/api/ean/{ean}`` with category, name, quantity
    and price data from the inventory.  Failures are silently ignored.

    When *cache_dir* is provided, the EAN GET cache is invalidated after a
    successful PUT so the next :func:`lookup_ean_via_tingbok` call fetches
    fresh data (which will reflect the PUT and suppress future pushes via
    :func:`ean_observation_needed`).

    Args:
        ean:         EAN/UPC barcode string.
        categories:  Category paths as classified in the inventory.
        name:        Clean product name from the inventory item text.
        tingbok_url: Base URL of the tingbok service.
        session:     Optional niquests.Session to reuse.
        quantity:    Weight or volume string (e.g. ``"140g"``).
        prices:      List of price dicts (``{currency, price, unit, date}``).
        cache_dir:   EAN cache directory.  On successful PUT the cache entry
                     for *ean* is deleted so the next GET is always fresh.
    """
    import niquests

    if not categories and not name and not quantity and not prices:
        return

    putter = session.put if session is not None else niquests.put
    base = tingbok_url.rstrip("/")
    payload: dict = {}
    if categories:
        payload["categories"] = categories
    if name:
        payload["name"] = name
    if quantity:
        payload["quantity"] = quantity
    if prices:
        payload["prices"] = prices
    try:
        response = putter(f"{base}/api/ean/{ean}", json=payload, timeout=5.0)
        if not response.ok:
            logger.warning("EAN PUT %s → HTTP %s: %s", ean, response.status_code, response.text[:500])
            return
        logger.debug("Reported EAN %s to tingbok: %s", ean, payload)
        if cache_dir is not None:
            cache_path = cache_dir / f"{ean}.json"
            if cache_path.exists():
                cache_path.unlink()
    except Exception as exc:
        logger.warning("Failed to report EAN %s to tingbok: %s", ean, exc)


def _uri_to_source(uri: str) -> str | None:
    """Determine the source name from a URI prefix."""
    if uri.startswith("off:"):
        return "off"
    if uri.startswith("gpt:"):
        return "gpt"
    if "aims.fao.org/" in uri:
        return "agrovoc"
    if "dbpedia.org/" in uri:
        return "dbpedia"
    if "wikidata.org/" in uri:
        return "wikidata"
    if uri.startswith("https://tingbok.plann.no/"):
        return "tingbok"
    return None
