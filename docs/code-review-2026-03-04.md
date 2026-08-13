# Code Review — 2026-03-04

> **Swept 2026-08-13.** All five findings are marked Fixed; nothing was migrated
> to a TODO. This file is a record, not a worklist.

## `vocabulary.py`

### `fetch_vocabulary_from_tingbok` (lines 230–238)

Line 232 is a no-op rename: `raw.pop("excluded_sources", [])` is immediately reassigned back to `raw["excluded_sources"]`. This is fine but redundant — you could just leave the key in `raw` and let `Concept.from_dict` pick it up. Minor style nit.

```python
raw["excluded_sources"] = raw.pop("excluded_sources", [])  # equivalent to nothing
```

**Fixed:** Line removed.

### `_uri_to_source` — missing `https://` variants for external sources

The function handles `http://www.wikidata.org/` but Wikidata entity URIs can also appear as `https://www.wikidata.org/` (e.g. from newer API responses). Similarly DBpedia sometimes returns `https://dbpedia.org/`. The existing code is not new here, but with the introduction of `_should_query_source` relying on this function (indirectly via `concept.source_uris`), wrong classification could cause a source to be re-queried unnecessarily. Probably we should stick to the https URLs.

**Fixed:** Both `https://dbpedia.org/` and `https://www.wikidata.org/` now recognised, with tests added.

### `_should_query_source` — "tingbok" hardcoded as string

The function special-cases `source == "tingbok"` with a string literal. If this source name ever changes (it's defined via `_uri_to_source`), this breaks silently. Consider a constant or at least a comment pointing to the string's origin.

**Fixed:** Comment added pointing to `_uri_to_source`.

### `_resolve_missing_uris` — inconsistency with `_should_query_source`

The candidate filtering at lines 1870–1875 partially duplicates the logic in `_should_query_source` but doesn't use it. Specifically, the individual `source in concept.excluded_sources` check per-source (which `_should_query_source` handles) is still missing in the inner loop:

```python
for source in sources_to_try:
    result = client.lookup_concept(label, lang, source=source)
```

If a concept has `excluded_sources=["agrovoc"]`, this function won't consult `agrovoc` anyway (it only tries `dbpedia`/`wikidata`), but the inconsistency is a latent bug: if `sources_to_try` ever includes `agrovoc`, the per-source exclusion won't be respected. The outer skip only short-circuits when **both** dbpedia and wikidata are excluded — but if only one is excluded, the loop will still try both. Should be:

```python
for source in sources_to_try:
    if not _should_query_source(source, concept):
        continue
    ...
```

**Fixed:** `_should_query_source` check added inside the inner loop.

### `build_vocabulary_with_skos_hierarchy` — AGROVOC skip logic cleanup

The old `skip_agrovoc` logic was removed and replaced with `_should_query_source`. Good simplification.

---

## `tests/test_vocabulary.py`

Tests are well-structured and directly test the new behaviour. One gap:

### Missing test: `_resolve_missing_uris` respects per-source exclusion

There's no test covering the case where a concept has `excluded_sources=["dbpedia"]` but not `["wikidata"]` — to verify the inner loop still queries wikidata (and skips dbpedia). The bug described above would not be caught by existing tests.

**Fixed:** `test_respects_per_concept_excluded_sources` added to `TestResolveMissingUris`.

---

## `docs/` changes

Pure prose/planning — no issues.

---

## Summary

| Severity | Issue | Status |
|---|---|---|
| Bug | `_resolve_missing_uris` inner loop doesn't call `_should_query_source`, so per-source exclusion isn't enforced there | Fixed |
| Nit | `raw["excluded_sources"] = raw.pop("excluded_sources", [])` is a no-op | Fixed |
| Minor | `"tingbok"` string hardcoded in `_should_query_source`, not tied to `_uri_to_source` | Fixed (comment) |
| Minor | `_uri_to_source` doesn't handle `https://` for wikidata/dbpedia URIs | Fixed |
| Test gap | No test for partial `excluded_sources` in `_resolve_missing_uris` | Fixed |
