# Code Review: inventory-md + tingbok (2026-05-08)

## Separation of concerns: mostly good, with one big blur

The high-level split is solid: tingbok owns authoritative category knowledge (SKOS
resolution, EAN lookups, vocabulary YAML), inventory-md owns the markdown files, photos,
shopping lists, and user interaction. The HTTP boundary is clean on paper.

The blur lives in **`vocabulary.py` (1478 lines)**. It contains:

- A full `Concept` dataclass that mirrors tingbok's `VocabularyConcept` Pydantic model.
  Two representations of the same thing, kept in sync manually.
- `build_category_tree()` — transforms the flat vocabulary dict into a hierarchy for the
  UI. It embeds rules about inferred hierarchy, stub nodes, `category_by_source` virtual
  nodes, etc. If tingbok changes how hierarchy works, this breaks silently.
- Language fallback chains duplicated in both places — inventory-md config and tingbok
  hardcoded.
- Cache management (`_cache_read` / `_cache_write`) that parallels tingbok's own cache
  infrastructure.

The cleaner model: tingbok serves a pre-built tree (not just a flat concept list), and
inventory-md's `vocabulary.py` becomes mostly glue code. The current `GET /api/vocabulary`
returns a flat list that inventory-md then re-structures — that's responsibility leaking
the wrong way.

## Duplicated code

1. **Cache layer**: `_cache_read` / `_cache_write` in `vocabulary.py` reimplements what
   tingbok's cache services already do. TTLs are set in two places (7 days in
   inventory-md, 60 days in tingbok).

2. **Language fallbacks**: `get_fallback_chain()` / `expand_languages_with_aliases()` in
   `vocabulary.py` vs. hardcoded in tingbok services. This should be canonical in tingbok
   (it owns language knowledge) and returned as part of the vocabulary API response or a
   dedicated endpoint.

3. **`_SOURCE_LABELS` dict**: Maps `"off"` → `"OpenFoodFacts"` etc. This knowledge
   belongs in tingbok. If tingbok adds a new source, inventory-md must also be updated.

4. **`_uri_to_source()`**: URI-scheme-to-source-name mapping in inventory-md. Same issue
   — tingbok is the authority on what sources exist.

## Scripts: what should move into the application

**`scripts/find_expiring_items.py`** — The "soybeans aren't recognized as food" bug
exists because the script does a naive string match instead of walking the hierarchy. The
fix logic is already present in `shopping_list.py`'s category matching, so it's
duplicated too. Should become `inventory-md expiring [--category food]`, reusing the
vocabulary machinery.

**`scripts/check_quality.py`** — Category validation is closely related to the parse
pipeline. The `--fix-categories` flag in particular belongs as
`inventory-md parse --fix-categories` rather than a separate script with its own tingbok
session setup.

**`scripts/sync_eans_to_inventory.py`** — Complex enough (photo scan → EAN extract →
tingbok lookup → markdown insertion) to deserve a proper `inventory-md sync-eans`
subcommand with tests. Currently a standalone script with no test coverage (unlike
`extract_barcodes.py` which has `tests/test_extract_barcodes.py`).

`scripts/analyze_inventory.py` and `scripts/migrate-tags.py` feel like one-off admin
tools; leaving them as scripts is fine.

## The categories problem

The core issue is that **category identity is still string-path-based**, not URI-based.
Because there's no canonical tingbok URL for concepts yet, inventory-md can't reliably say
"these two paths are the same thing" without reimplementing tingbok's resolution logic
locally. This is why `shopping_list.py` has category-matching algorithms instead of just
asking tingbok "is `food/legumes/soy-beans` a descendant of `food`?"

The fix described in `TODO-CATEGORIES.md` (retired 2026-08-13; the item now lives
under "Canonical tingbok URLs" in `~/tingbok/TODO.md`) — give concepts canonical tingbok URLs, let
clients navigate the tree by URL) would let inventory-md delete most of its
category-matching code and replace it with "does this item's concept URL appear under this
ancestor concept URL?" — a single tingbok API call.

Until that's done, the practical improvement is: **add a
`GET /api/concept/{id}/ancestors` endpoint to tingbok** so the "is soybeans food?"
question has a correct, authoritative answer, and both the shopping list generator and
`find_expiring_items` can use it without duplicating hierarchy-walking code.

## Summary

| Issue | Severity | Location |
|-------|----------|----------|
| No canonical tingbok URLs → client reimplements hierarchy | High | `vocabulary.py`, `shopping_list.py`, scripts |
| `build_category_tree` in client, not server | Medium | `vocabulary.py:818` |
| `Concept` dataclass duplicates tingbok model | Medium | `vocabulary.py:370` |
| Language fallbacks in two places | Low | `vocabulary.py:262`, tingbok/services |
| `_SOURCE_LABELS` / `_uri_to_source` belong in tingbok | Low | `vocabulary.py:56`, `vocabulary.py:1464` |
| `find_expiring_items.py` doesn't use vocabulary hierarchy | Medium | `scripts/` |
| `sync_eans_to_inventory.py` has no tests, should be a CLI subcommand | Low–medium | `scripts/` |

The biggest ROI: implement canonical tingbok concept URLs, add an ancestors endpoint, and
let inventory-md drop its local hierarchy logic. That also fixes the `find_expiring_items`
soybeans-as-food bug as a side effect.
