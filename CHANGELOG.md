# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **`inventory-md parse` is quiet by default** — the per-EAN and per-category tingbok lookup lines (hundreds on a large inventory, drowning the shopping pipeline's own output) now require `parse --verbose`/`-v`; the default prints summary counts only. `vocabulary.enrich_categories_via_lookup()` grew a `verbose` flag (off by default; the interactive `vocabulary lookup` command keeps its progress line).
- **Unknown-category warnings consult tingbok before crying wolf** — `add_item()` (and thus `inventory-md add` and the staging importer) now falls back to tingbok's vocabulary when a category doesn't resolve locally, so categories merely *new to this inventory* no longer warn or fail `--strict`. When tingbok is unreachable the local verdict stands. New optional `tingbok_url` parameter, supplied from config by the CLI and `inventory_import.py`.

### Fixed
- **`shopping_context.py` no longer resolves a bare chain name to whichever branch happens to be cached** — `match_shop_osm()` fell back to a substring match when it was *unambiguous*, on the theory that a single cached "Lidl Varna" makes a bare "lidl" unambiguous. Uniqueness in the cache is a fact about which shops have been visited before, not about which shop the caller means: on 2026-07-24 a trip to **Billa Sozopol** asked for `"Billa"`, matched the one cached Billa, and confidently returned the **Varna** branch's `WAY:1016681733` — a wrong shop location with no ambiguity for the old guard to trip on. The cache is branch-keyed (`Billa Varna ул. Андрей Сахаров`), so a bare chain name is not an under-specified key but no key at all: resolution now requires an **exact** (case-insensitive, whitespace-stripped) cache key and nothing else. A partial match prints the candidate branch keys — by name only, since printing their OSM ids alongside would invite copy-pasting one without checking the branch — and the CLI now lists them for a *single* candidate too, which is precisely the case the old code resolved silently. `openprices_publish.py`, which does the actual publishing, already required an exact key and was never affected.
- **Shopping trips are booked at the net charged amount, not the pre-discount gross** — `shop_import.py` read `total_price_no_saving` (the gross) as `receipt_total`, so a discounted trip was booked too high (the 2026-07-21 Lidl trip: gross 54.43 against a 51.77 net charge, a 2.66 EUR overstatement across four discounted lines), and it recomputed each line as `price * qty` instead of using the till's printed per-line total (a 2.398 kg melon at 0.99 EUR/kg prints 2.37 but computes 2.374 — a real 1-cent error). The parser now books **net**: `receipt_total` is the net charged total, with `receipt_total_gross` and `receipt_discount_total` surfaced alongside; each line's `line_total` is the printed net amount, and a discounted line additionally carries `line_total_gross`, `line_discount`, `price_net` (net per-unit) and a `discounts` list — one entry per discount (a line can carry several of different kinds: the 07-21 кисело краве мляко line has both a Lidl Plus coupon and a separate 20% short-expiry markdown), each mapped to its Open Prices `discount_type` (`lidlplus_coupon`→`LOYALTY_PROGRAM`, `markdown`→`EXPIRES_SOON`). `ledger.py` now books the net `line_total` and stores the net per-unit price (`price_net`) as `unit_price`, so `openprices_publish.py` posts the price actually paid with the gross supplied via `--discount EAN=GROSS:TYPE`. Receipts with no discount data (the old Lidl schema, hand-transcribed Billa/cash trips) book gross == net and gain no discount fields, so nothing crashes or silently zeroes. New `openprices_discount_type()` helper; see `scripts/staging.py` for the full field semantics.
- **`ledger.py import-staging` no longer drops a repeated receipt line** — a reviewed staging file that listed the same product on two separate lines (e.g. two identical 4.09 Lurpak butters on the Бурлекс 2026-07-08 trip) had its duplicate silently collapsed by `upsert_rows`'s identity dedup, undercounting the ledger by the line total (that trip booked 45.16 against a 49.25 receipt). `staging_to_rows()` now runs `combine_duplicate_lines()` before upsert, exactly as the Lidl and Decathlon importers already did — two qty-1 lines merge to one qty-2 row.
- **`bb_est: true` in a staging file is no longer discarded, turning an estimate into an assertion** — a staging row can express an estimated best-before inline (`bb: 2026-07-09:EST`) or out of band (`bb: '2027-01-01'` plus `bb_est: true`). `staging_item_to_kwargs()` only ever looked at the suffix and at the free-text `bb_source`, so the separate key was dropped silently and the line was written as a bare `bb:2027-01-01` — a shelf-life guess recorded as a printed date, which is exactly the error `:EST` exists to prevent. The 2026-07-21 Lidl trip imported 9 such rows with no `:EST` marker at all (2026-07-10 the same). Both spellings are now honoured and reconciled in one place, the new `additem.resolve_bb_est()`: an explicit flag wins over the `bb_source` heuristic, and a `:EST` suffix contradicted by `bb_est: false` (or a non-boolean `bb_est`) is a loud `ValueError`, never a silent pick. `add_item()` accepts a `:EST` suffix on `bb` too, and its `bb_est` parameter grew a third state (`None` = unspecified) so `inventory-md add --bb 2026-09:EST` no longer collides with the implicit `--est` default.
- **Items are no longer filed into the wrong container by a substring ID match** — `find_container_section()` located a container with a bare `f"ID:{container_id}" in line` test, so resolution went by *file order* rather than by identity: a staging row with `location: temp` matched the earlier `## ID:temp-boxes` heading, whose section spans a whole tree of tool boxes, and `insertion_index()` duly appended the bullet after that span's last item — inside `#### ID:TC-01` (Einhell batteries). Cornflakes and biscuits were written into a tool box, silently. Resolution is now two-pass: an exact (case-insensitive) ID match always wins, and only when there is none do we fall back to a prefix match — which must be unambiguous, several candidates raising the new `AmbiguousContainerError` (a `ValueError`) listing them instead of picking the first. `add_item()`'s container-existence check is case-insensitive too and passes the container's *stored* spelling on to the writer. New `parser.heading_container_id()` helper; `AmbiguousContainerError` is exported from the package root.
- **`shop_import.py --receipt` imported the wrong shopping trip** — it took the last array element, but `lidl_receipts.json` is sorted by receipt *id* and the id is not chronological: the 2026-07-21 trip (19 items) sorts *before* the 2026-07-17 one (6 items), so asking for the newest trip silently produced the older one. Selection is now by purchase date, with new `--receipt-id` and `--date` selectors for a specific trip; a selector matching several receipts (two visits in one day is normal — 2026-07-10 has two) fails and lists the candidates rather than guessing. New `select_receipt()`/`receipt_date()` helpers; the module docstring and `--receipt --help` no longer claim "latest entry is used".
- **`inventory-md add`/staging import no longer crash on YAML-native best-before dates** — an unquoted `bb: 2027-02-12` in a staging file reaches `add_item()` as `datetime.date` and `validate_bb_format()` raised TypeError. Date/datetime values are now coerced to their ISO string form (same YAML-typing family as the `tingbok_push.py` session-date fix below).
- **`shop_import.py` no longer stamps the Lidl header onto hand-transcribed receipts** — a receipt JSON with generic `date`/`shop`/`currency`/`total` keys used to come out as `shop: Lidl Varna`, `receipt_total: 0.0`, `source: lidl_receipts.json`. Generic header keys now win over the CLI defaults, item rows honour explicit `unit`/`unit_price` (the printed line total stays authoritative), and `source` records the actual receipt filename.
- **`bread` is no longer treated as a too-broad category** — removed from `DEFAULT_BROAD_CATEGORIES` in `check_quality.py`. `bread` is a usable leaf category, so a `category:bread` item no longer fails QA (`bakery` stays broad).
- **Markdown list nesting deeper than one level is no longer dropped** — `build_section_items()` only descended a single level of nested bullets, so a 3-deep overview list (e.g. `### ID:aft-cabin` → starboard side → wardrobe → *top shelf*) lost its deepest items. The flattening is now fully recursive; every bullet below the top level is kept and marked `indented`.
- **A second `ID:`/`ean:`/… on an item line no longer overrides the first** — only `category:` and `tag:` legitimately repeat and accumulate; every other key is single-valued, so `extract_metadata()` now consumes only the first occurrence and leaves later same-key tokens in the name. Fixes lines that quote a device id in their description (a GPS tracker `… ID:gps-tracker-fl1 … (IMEI:…, ID:280425160522)` was parsed under `280425160522` with its name truncated at the stray token).
- **Items under an ID-less sub-heading are no longer silently dropped** — a heading without an `ID:` is treated as a structural/organisational wrapper (e.g. `# Attic storage`), but the parser also discarded any list items it carried directly. People (and agents) use such headings purely for human-readable grouping *within* a container — e.g. `### ID:C-04` holding 68 children's books split across `#### English/Norwegian/Swedish children's books` — with all the machine-readable data on each item line. The parser dropped every one of those items: against the real `solveig-inventory` markdown, **487 of ~1480 item IDs (~33%) were missing** from `inventory.json`, so they were invisible to search, the web UI, the shopping list and expiry reports (the original symptom: `vocabulary search book` returned only the single book listed directly under a container). `process_section()` now attaches an ID-less section's items (and `**X:**` pseudo-headers) to the nearest ID-bearing ancestor container before recursing; the wrapper still creates no container of its own. The item-building block is extracted into `build_section_items()` so both branches share it.
- **`tingbok_push.py` no longer crashes on a bare YAML `session:` date** — `session: 2024-11-18` is parsed by PyYAML as a `datetime.date`, which is not JSON-serialisable once embedded as the price/receipt-name observation date, so `--commit` failed with "Object of type date is not JSON serializable" (the dry run masked it by never serialising the payload). `_shops()` now coerces a `datetime.date`/`datetime` session to an ISO string; a quoted-string session passes through unchanged.
- **Category-tree cycles no longer crash `search.html`** — some upstream (tingbok) concepts arrive with contradictory SKOS relations that list a concept in *both* `broader` and `narrower`, including self-references (e.g. `lentil` with `broader == narrower == ["lentil"]`, and the `rope` ⇄ `rope/cord` pair). The web UI walks `narrower` recursively, so once such a looping category had items (count > 0) the tree recursed until the JS stack overflowed — the page showed only "Error loading data. Check that inventory.json exists." (a misleading message, since the data loaded fine). `build_category_tree()` now strips self-references and breaks `narrower` cycles (DFS back-edge removal) so generated `vocabulary.json` is always a DAG, and `renderCategoryNode()` in the template carries an ancestor set as a defensive guard so a malformed tree can never hang the page regardless of data source.

### Added
- **A staging file must now balance: line items have to sum to `receipt_total`** — `require_flat()` (which every consumer already calls: `ledger.py`, `tingbok_push.py`, `inventory_import.py`) refuses a file whose items do not add up, raising the new `staging.ReconciliationError`. Transcribing a photographed receipt is the one point in the pipeline where a human reads numbers off an image, and the sum is the only cross-check that exists for that reading — on 2026-07-24 it was the only thing that caught Billa's multiplier-line quirk, the line items coming to 18.12 exactly under the correct reading and not under the naive one. One cent of per-line rounding is tolerated (`RECONCILE_TOLERANCE`); two is not. A file whose items carry money must state a `receipt_total`, since omitting it would otherwise be a way to skip the check; a file with no money on any line (inventory-only, recording things acquired rather than bought) needs none — demanding a `receipt_total: 0` there would only teach writing one to silence the gate. An unpriced line among priced ones counts as 0.00: right for a free carrier bag, and for a price left out by mistake it unbalances the sum, which is the point. New `staging.reconcile_total()` and `staging.line_total_of()`.
- **`receipt-formats.json` + `scripts/receipt_formats.py` — per-chain receipt layout quirks** — the things you must know to transcribe a photographed receipt correctly, printed as a checklist before you start: `receipt_formats.py "Billa Sozopol"`. Records which address line identifies the branch, whether an `N x unit_price` multiplier belongs to the line above or below it, how discounts and deposits print, dual-currency totals, and how weighed lines are marked. Billa's entry is the reason it exists: the multiplier is printed **above** its item, so on 2026-07-24 `3 x 0.71` under `BILLA ПОП КЪРПИ 5Б` (belonging to the `ШУМЕНСКО` line below) billed three beers to a pack of cleaning cloths — and Billa's header address is the company's registered one while the *store* address, the one OSM matches, is in the card-terminal footer. Keyed by **chain**, not branch (a chain's receipts look the same in every town, unlike its prices), with an ambiguous chain prefix raising rather than resolving. An entry exists only for a chain whose receipt has actually been read and must carry a `source` naming it; an unrecorded chain prints as unrecorded, because a guessed layout gets trusted exactly like a known one.
- **`extract_barcodes.py` auto-rotates OCR for sideways/upside-down photos** — the best-before / label OCR now runs the EXIF-corrected orientation first and, when a photo reads as garbage (the 1-2 char fragment scatter typical of a shot saved physically rotated with no/wrong EXIF tag), retries at 90°/270°/180° and keeps the best-scoring orientation. Best-before dates that were silently lost on rotated grocery photos are recovered; upright photos incur no extra cost. New `extract_text_ocr_oriented()`/`_text_quality()` helpers and an `angles=` parameter on `extract_text_ocr()`.
- **Shop-prefixed local article numbers in `tingbok_push.py`** — in-store / GS1
  restricted-distribution codes (Lidl's 8-digit `2x` PLUs, Mercadona's `0x` EAN-8,
  7-digit shop article numbers) are not globally unique, so they are now pushed under a
  `<chain>-<code>` key derived from the staging `shop` (`20004132` @ "Lidl Varna" →
  `lidl-20004132`). New `canonical_ean()`/`chain_slug()`/`is_local_instore_code()` helpers;
  genuine global EANs, 13-digit `2x` weight barcodes, hand-written prefixed keys, and
  shopless ad-hoc pushes are left bare. Matches tingbok's server-side forwarding so a
  shopping import no longer creates a bare duplicate of an already-prefixed record.
- **`inventory-md edit <item-id> [--ean … --bb … --est/--no-est --mass … --volume … --qty … --price … --category … --name … --tag …]`** — change fields on an item line that is already in the file. `add` is append-only and `move` only changes the container, so correcting a line (a mistyped EAN, a best-before from a late-arriving label photo, a shop-local barcode needing its chain prefix, an estimate recorded as a hard date) was the last remaining reason to hand-edit `inventory.md` — it bit three times in one evening. The line is rewritten in place: existing fields are substituted where they stand so the line's own field order and spacing survive, new fields are inserted at the canonical position, an empty value removes a field, and indented sub-bullets plus every other line in the file are untouched. `--est`/`--no-est` on their own flip the `:EST` marker on the date already present (the repair path for the `bb_est` bug above). The ID must match exactly one bullet — an unknown or duplicated ID is an error, not a guess — and the same QA as `add` applies (category resolution, `--strict`, food-without-`bb:`, `--no-bb-check`), plus `--dry-run` and `--file`. New module `edititem.py`; `moveitem.find_item_blocks()` (plural) and `additem.category_qa()` are extracted so lookup and category/food checks are shared rather than reimplemented.
- **`inventory-md move <item-id> <container-id>`** — relocate an existing `ID:`-tagged item bullet from wherever it sits into another container's section, carrying any of its indented sub-bullets along. The counterpart to `add`, for the recurring chore of repacking physical storage; doing it by hand-editing markdown risks duplicating a line instead of moving it, or orphaning sub-bullets. The destination container must already exist; only single `ID:` bullets are addressable (free-text list entries without an ID are not). Supports `--dry-run` (reports source → destination and the line, writes nothing) and `--file`. New module `moveitem.py`; the bullet-insertion slot logic is shared with `add` via the extracted `additem.insertion_index()`.

### Removed
- **Language-fallback subsystem** — `DEFAULT_LANGUAGE_FALLBACKS`, `get_fallback_chain()` and `apply_language_fallbacks()` in `vocabulary.py`, plus `Config.language_fallbacks` / `Config.get_language_fallback_chain()` and the `language_fallbacks` config default. It was dead code (no production caller; the live resolver `resolve_category()` already delegates cross-language matching to tingbok), and keeping a second copy duplicated logic that belongs to the tingbok service. Cross-language *fallback* resolution is now solely tingbok's concern. Supersedes the v0.14.0 "Language fallback data deduplicated" change.
- **Same-language alias helper** — `LANGUAGE_CODE_ALIASES` / `expand_languages_with_aliases()` in `vocabulary.py`. Dead code: only its own tests referenced it; label fetching (and any nb/no equivalence) is handled by tingbok.
- **Other dead helpers** — `vocabulary.get_broader_concepts()` / `get_narrower_concepts()`, `md_adapter.parse_markdown_file()` (only the string variant is used) and `shopping_list.generate_shopping_list_if_needed()`. None had callers, tests, or `__all__` exports.

## [v0.14.0] - 2026-06-20

I've been hammering on this project for several month now forgetting to make releases "on the go".  The following CHANGELOG seems overwhelming, it's AI-generated, probably full of junk, but I believe I'm the only user of this project so I just let it slide through.

### Added
- **`scripts/pipeline.py`** — drives the Stage-3 commit steps from a reviewed staging file's `status:` block: runs `ledger` → `inventory` → `tingbok` in order (each as a sub-process of the existing single-purpose script), updating each `status:` value on success so an interrupted run resumes, then validates with `inventory-md parse` + `check_quality.py`. Dry run by default (`--commit` to execute; `--from STAGE` to force-restart). The point is that the whole commit stage becomes *one* command instead of a hand-chained `ledger && inventory && tingbok && parse && check` — a chained shell string can't be pre-approved, so chaining is what forced the per-action approval prompts. Diary (separate repo, may split one card charge across categories) and the public `off_upload`/`open_prices` writes are deliberately left as explicit manual steps so the staging review stays the single checkpoint. Status edits are line-based to preserve the reviewer's comments (a YAML round-trip would drop them).
- **`scripts/shopping_context.py`** — read-only situational context for a shopping run: the shop's cached Open Prices OSM object, the most recent staging files for that shop (as a schema/convention example), and (with `--diary`) the shop's recent diary expense lines. Replaces the ad-hoc `grep`/`cat`/`awk` the skill used to run to rediscover these each trip — which defeated the command allowlist.
- **All pipeline scripts are now executable** — `inventory_import.py` and `bb_dates.py` had a shebang but no `+x` bit, so they had to be invoked via an explicit `python3 …` prefix while their siblings ran bare; the inconsistency is fixed so a single `~/inventory-md/scripts/X.py` allowlist form works uniformly.
- **`add` CLI subcommand** — `inventory-md add CONTAINER --category CAT [...] NAME` appends a validated item line to a container in `inventory.md`, replacing hand-editing in the shopping pipeline's Stage 3. Folds the quality checks into the write step: duplicate-ID detection (across all containers and items), the food-without-best-before check (a hard error unless `--no-bb-check`), and category resolution against the local vocabulary (a warning, or an error with `--strict`). `--id` is optional — when omitted a readable ID is generated from the category leaf, plus the purchase date for food items (e.g. `milk-2026-06-14`). Reuses `parser.find_container_section`, `queries._is_food` and `vocabulary.resolve_category` rather than duplicating logic.
- **`scripts/inventory_import.py`** — writes a whole reviewed shopping staging file into `inventory.md` in one pass (the Stage-3 *Inventory* step, scripted). Imports `inventory_md.additem` directly rather than shelling out: maps each `add_to_inventory` row's `location`→container, `category`, `inventory_id`, `ean`, `bb` (`:EST` honoured), `qty`/`unit` (weighed lines → `mass`/`volume`) and `price` to an item line, runs the same QA checks per row, and reports add/skip/exists/error counts. Dry run by default; `--commit` writes. Re-running is safe — rows whose `inventory_id` already exists are skipped. Missing `location` defaults to the `floating` container.
- **Best-before OCR from product photos** — `scripts/bb_dates.py` turns OCR text into normalised ISO date candidates (DD.MM.YYYY, DD.MM.YY, MM.YYYY, ISO, spaced/dashed) and picks the most likely best-before, preferring a date next to a best-before keyword (bg/en/de). `extract_barcodes.py --best-before` now runs OCR on every image — barcode photos included — and attaches `best_before` + candidates, since the date usually shares the photo with the barcode. OCR honours EXIF orientation and downscales large photos; OCR language set is bg+en. Verified reading real Lidl/Billa date stamps (2027-01-05, 2028-02-10).
- **`scripts/openprices_publish.py`** — publish receipt prices to OFF Open Prices: uploads the receipt photo once as a RECEIPT proof, then POSTs one price per ledger line item with an EAN. Shop location is an explicit, human-confirmed OSM object (`--osm TYPE:ID`, cached per shop in `~/.config/inventory-md/shop-osm.json`) — never auto-geocoded, since receipt photos are often taken away from the shop (`--suggest-from-photo` only hints from EXIF GPS). Dry-run by default. Companion `scripts/op_auth.py` mints a durable Open Prices token from a password via `getpass` (stored 0600 under `~/.config/inventory-md/`, never in a script). Barcodeless items publish as explicit CATEGORY prices (`--category-price en:baguettes=0.17,was=0.45,type=SALE`, `--no-products`); discounts via `--discount EAN=GROSS:SALE`; `--proof-id` reuses an uploaded proof. See `docs/open-prices-integration.md`.
- **`expiring` and `lookup` CLI subcommands** — the logic from `scripts/find_expiring_items.py` and `scripts/lookup_items.py` now lives in the package (`inventory_md.queries`) and ships with `inventory-md`. `inventory-md expiring` lists items by best-before date (`--food`, `--limit`, `--all`, `--before`); `inventory-md lookup --id/--match` resolves items by id or text, including items with no best-before date. The standalone scripts remain as thin wrappers. `--food` now uses the vocabulary hierarchy (`vocabulary.is_descendant_of`) so e.g. soybeans are correctly recognised as food. `inventory-md expiring --category CAT` (`-c`) restricts the report to a single category and its descendants (hierarchy-aware via `vocabulary.json`, e.g. `--category rice` also surfaces risoni); without a vocabulary it falls back to a case-insensitive substring match on the raw category labels. Matching is on the item's `categories` metadata, not its ID.
- **`check_quality.py` enforces best-before on food products** — `check_food_without_bb` flags inventory items whose category resolves under the `food/` hierarchy (via tingbok concept ancestry) but have no `bb` date. Non-food (detergent, epoxy, …) is exempt. An explicit path root is trusted (`hardware/nut` is not food even though the leaf `nut` resolves to `food/nuts`), disambiguating fasteners from edible nuts. Surfaces as a warning.
- **`scripts/off_upload.py`** — create/update Open Food Facts products for EANs missing from OFF, from a curated reviewable YAML. Dry-run by default; `--commit` writes via the `openfoodfacts` SDK using the browser session cookie (browser_cookie3, no password in the script) and uploads the front image, then verifies. `--env net` targets staging. Used to add 2 Bulgarian products (Oberon tomatoes, Billa rice) to OFF production.
- **`ledger.py combine_duplicate_lines()`** — receipts that print the same product on two qty-1 lines (instead of one qty-2 line) are now merged into a single row with summed qty/total in the raw importers, instead of being silently dropped by the upsert identity match. Verified on a real Billa receipt.
- **`scripts/ledger.py`** — append-only purchases ledger (`purchases.jsonl`), one line per receipt line-item, the single source of truth for spending. Importers for raw Lidl receipts, Decathlon purchases (carry the EAN), and reviewed `shop_import` staging files; idempotent re-import. `query` slices spending by category/date/shop; `consumed` joins ledger rows to items removed from `inventory.md` (via git history) to cost what was actually consumed in a period. Note: raw Lidl rows have no category/EAN, so category and consumption queries only resolve for rows enriched through the reviewed staging flow. See `docs/shopping-workflow-redesign-2026-06-06.md`.
- **`scripts/shop_import.py`** — first stage of a staged shopping-import pipeline. Parses a Lidl receipt (JSON) into one row per line item, classifies barcode-extraction photos as barcode/expiry/label, and gathers candidate EANs per line via tingbok's reverse receipt-name lookup (`GET /api/ean/search`). Emits a human-correctable staging YAML; EAN matching and best-before reading are deferred to a later review step. See `docs/shopping-workflow-redesign-2026-06-06.md`.
- **`shopping-list` CLI subcommand** — regenerates `shopping-list.md` without running a full parse. Reads from `inventory.json` (must exist) and `wanted-items.md`. Supports `--stdout` to print to stdout instead of writing the file, and `--no-dated` to skip dated wanted-items files. Auto-detects all paths from config/CWD.
- **`vocabulary.resolve_category()`** — new public function that resolves a raw category string (leaf name, path alias, or full concept path) to a canonical concept ID. Used by the shopping list to normalise both inventory categories and wanted-item categories before matching.
- **`category:` syntax in wanted-items.md** — wanted-items now accept `* category:potatoes` in addition to the legacy `* tag:food/grains/pasta` syntax.

### Changed
- **Shopping list reads `inventory.json`** instead of `inventory.md`. Category matching uses the vocabulary to resolve leaf names to canonical concept IDs; ancestor/prefix matching replaces the old "parts extraction" heuristic.
- **Typed fields in `inventory.json`**: `qty` is now stored as a float (supports half-packages), `mass` is stored as `mass_g` (float, grams), `volume` is stored as `volume_l` (float, liters), `bb` is always a full ISO date string (`YYYY-MM-DD`; partial dates like `2026-03` are extended to the last day of the month/year). A new `bb_inferred: true` flag marks best-before dates estimated by the owner rather than read from the package label (`EST` token in markdown).
- **Expired items count toward stock** — the shopping list no longer silently excludes items past their best-before date. Disposing of expired items is a separate activity from shopping.
- **Volume unit standardised to liters** — `volume_l` replaces `volume_ml` throughout. `parse_amount()` normalises ml/cl/dl to liters.
- **`tag_matches()` simplified** — uses strict ancestor/prefix matching on canonical concept ID paths. The old "all path parts present" heuristic is removed.
- **`tingbok_push.py` usable for single found items, not just shopping trips** — items with no `receipt_name` no longer push an empty (null-named) `receipt_names` row, and items with no `price` push no `prices` row, so a minimal hand-written staging file can record an ad-hoc found product without running the rest of the pipeline. `docs/ADDING-ITEMS.md` now documents the standalone add-and-publish flow: EAN lookup via tingbok (`GET /api/ean/{ean}`, which delegates to OFF — distinct from the `/api/lookup/` *category* endpoint), pushing with `tingbok_push.py`, and contributing missing food to OFF with `off_upload.py`. First tests for `tingbok_push.py`.
- **Deduplication: `_is_descendant` removed from `shopping_list.py`** — `tag_matches()` now calls `vocabulary.is_descendant_of()` directly (code-review-2026-06-11 §3.2).
- **`create_broader_stubs()` made public and auto-called** — renamed from `_create_broader_stubs`, now called automatically at the end of `load_local_vocabulary()` so callers don't need to invoke it manually; three redundant call sites in `queries.py`, `shopping_list.py`, `cli.py` removed (code-review-2026-06-11 §3.7).
- **Language fallback data deduplicated** — `DEFAULT_LANGUAGE_FALLBACKS` in `vocabulary.py` is now the single source of truth; `config.py`'s `DEFAULTS["language_fallbacks"]` is built from it, and `Config.get_language_fallback_chain()` delegates to `vocabulary.get_fallback_chain()` (code-review-2026-06-11 §3.1).

### Fixed
- **Dated wanted-items files with a recipe-name suffix are no longer skipped** — `find_dated_wanted_files()` globbed `wanted-items-*.md` but then filtered with a regex that required the date to be immediately followed by `.md`, so the documented `wanted-items-YYYY-MM-DD-recipe-name.md` form (the one the `suggest-recipe` skill actually writes) was silently dropped from the shopping list. The regex now allows an optional `-recipe-name` suffix; the master `wanted-items.md` is still excluded. First tests for `find_dated_wanted_files`. The `suggest-recipe` skill doc, which contradicted itself, is corrected to the suffixed form.
- **`find_container_section()` now locates nested (`###` and deeper) sub-containers** — it previously matched only `#`/`##` headings, so `inventory-md add` (and the pipeline's `inventory_import.py`) raised "Container ID:… not found" for any sub-container such as `pantry-fridge`. Heading depth is now computed generically and a section ends at the next heading of the same-or-higher level, so adds to nested containers work.

### Removed
- `scripts/generate_shopping_list.py` — deleted; it was a duplicate of `shopping_list.py` without vocabulary support.

### Breaking Changes
- **Config directory changed from `/etc/inventory-system/` to `/etc/inventory-md/`** — systemd service files and Makefile now reference `/etc/inventory-md/*.conf`. On existing deployments, copy or symlink the config directory and run `systemctl daemon-reload` (and restart services) after deploying updated service files.

## [v0.13.0] - 2026-03-10

Lots of changes - still trying to get the category system to work reasonably well.

(version number jump to match the verisoning in Tingbok)

### Added
- **EAN observations pushed to tingbok** — after each parse run, `inventory-md` PUTs
  EAN observations (categories, name, quantity, price) to `PUT /api/ean/{ean}` on the
  configured tingbok server.  This feeds locally-observed product data back into the
  shared EAN database without requiring git-tracked JSON files.
- **`report_ean_to_tingbok()`** in `vocabulary.py` — helper that PUTs a single EAN
  observation to tingbok; silently ignores network failures so parse runs are never blocked.
- **`receipt_names` support in EAN observations** — the Lidl shopping skill now PUTs
  receipt name observations (Bulgarian/local receipt text) to tingbok via `curl -X PUT`
  instead of writing to the local `ean_cache.json`.
- **Client-side caching for EAN and category lookups** — `lookup_ean_via_tingbok()`,
  `enrich_categories_via_lookup()`, and `report_ean_to_tingbok()` accept an optional
  `cache_dir`; successful responses are cached under `~/.cache/inventory-md/tingbok/`
  with a 7-day TTL.  `parse --auto` wires all three to this cache automatically.
- **`ean_observation_needed()`** helper — encapsulates comparison of a would-be PUT
  payload against the current GET response from tingbok to decide whether a re-push
  is needed.
- **`source_paths` field on `Concept`** — tracks the normalised path for each source
  (e.g. GPT).  `_add_category_by_source_nodes()` now builds proper intermediate virtual
  nodes for sources that supply `source_paths`, with a flat-list fallback for others.
- **Path alias support in vocabulary building** — new `path_aliases` field on `Concept`
  (parsed from tingbok); `build_vocabulary_from_inventory()` silently redirects aliased
  paths (e.g. `klær/vinter` with `lang=nb`) to the canonical concept instead of
  creating spurious inventory nodes.
- **Dynamic `category_by_source/*` virtual nodes** — generated at runtime from
  `concept.source_uris`; all sources present in the vocabulary appear automatically
  (off, agrovoc, dbpedia, wikidata, gpt, …) without hardcoded names.
- **Source badge tooltips** in search UI — OFF and GPT badges show the human-readable
  category name (e.g. "OpenFoodFacts: potatoes" / "Google Product Taxonomy #455");
  `gpt:` and `off:` URIs no longer produce dead hyperlinks.
- **GPT source badge** (blue) added to the search UI.
- **`navigateCategoryInModal()`** keeps the detail modal open when clicking
  broader/narrower links — the modal updates in place instead of closing.

### Changed
- **EAN deduplication replaced** — TTL-based "already reported within N days" tracking
  is replaced by comparison-based logic: the GET response from tingbok is compared with
  what would be pushed, and the PUT is skipped when every field is already reflected.
  After a successful PUT the local cache entry is invalidated so the next run re-fetches
  fresh data.

### Fixed
- **`enrich_categories_via_lookup`** now normalises labels before sending to
  `/api/lookup`: path-like labels (e.g. `bag/dry-bag`, `electronics/solar-panel`)
  use only the leaf node, and hyphens/underscores are replaced with spaces.
  Previously the raw path was sent verbatim, causing DBpedia to match wildly wrong
  concepts (e.g. `electronics/solar-panel` → `south_african_standard_time`).
- **Category count propagation** now walks SKOS `broader` links recursively
  (cycle-safe).  Single-segment concepts (e.g. `bouillon` with `broader: food/spices`)
  previously never contributed to ancestor category counts and were invisible when
  filtering by a parent category.
- **OFF language tag prefixes** (`en:`, `sk:`, …) stripped from EAN category labels
  before lookup — old cached tingbok entries with raw OFF tags (e.g. `en:mashed-vegetables`)
  now normalise to `mashed vegetables` before the label lookup.
- **EAN price comparison** no longer includes the observation date — prices are compared
  on `(currency, price, unit)` only, so the same price does not trigger a redundant
  re-push just because the stored date differs.  `_parse_inventory_price` no longer
  auto-assigns today's date to inventory observations.
- **`_uri_to_source()`** now recognises both `http://` and `https://` URI prefixes for
  AGROVOC, DBpedia, and Wikidata.
- **Clothing source=inventory bug** — `enrich_categories_via_lookup` creates
  `source='inventory'` stub concepts for intermediate path segments (e.g. `clothing`
  when enriching `clothing/outdoor_clothing`).  These stubs were overwriting
  tingbok-sourced parent concepts.  The parse command now restores any global-vocab
  (tingbok) concept overwritten by an inventory stub after merging resolved concepts.
- **EAN PUT failures** logged at `WARNING` level (was `DEBUG`) so 4xx errors are
  visible without enabling debug logging.

### Removed
- **`skos.py`** module (SKOSClient, SPARQL queries to AGROVOC/DBpedia/Wikidata) — all
  source-specific lookups are now handled exclusively by tingbok.
- **`off.py`** module (Open Food Facts taxonomy client) — OFF lookups moved to tingbok.
- **`build_vocabulary_with_skos_hierarchy()`** and `_enrich_with_skos()` from
  `vocabulary.py` — hierarchy expansion is no longer done in inventory-md.
- **`inventory-md skos`** CLI command (`expand`, `lookup`, `cache` subcommands).
- **`--skos` / `--hierarchy`** flags from `inventory-md parse`.
- `skos_enabled`, `skos_hierarchy_mode`, and related config properties.

## [v0.7.0] - 2026-03-04

### Breaking Change
Ref the "Changed" section further down, this release is efficiently adding a hard dependency on my tingbok.plann.no service being up.  Tingbok, including the data, is open source and available both from pypi and github, so should the service be down it's easy to work around this dependency.

(There may be other breaking changes as well that I have forgotten to mention - it's still the 0.x-series, so I'm in my full rights to reorganize things - and as for now, I suppose I'm the only user in the world.  However, this is a concern I find worth flagging)

### Fixed
- **Category tree orphan promotion** removed — `build_category_tree()` no longer
  promotes unreachable concepts to root level.  `_root.narrower` is a whitelist;
  external orphans are excluded.
- **`vocabulary.json` feedback loop** — `find_vocabulary_files()` no longer picks up
  the generated `vocabulary.json` from the CWD as input vocabulary.
- **Shopping list `category:` items** — `parse_inventory_for_shopping()` now processes
  items with `category:` fields (the majority), mapping them to full vocabulary tag
  paths via `vocabulary.json`.  Previously only `tag:` items were processed.
- **`find_expiring_food.py`** — was checking `metadata.tags` (always empty) instead of
  `metadata.categories`; zero food items were found.  Now checks both.

### Added
- **`augmentContainerImagesFromRegistry()`** — items photographed at a parent-container
  level now appear when browsing a sub-container or filtering by category.
- **Multi-source URI support** via `source_uris` and `excluded_sources` on the `Concept`
  dataclass.  When fetched from tingbok, `source_uris` (a list in the API response) is
  converted to a `{source_name: uri}` dict, and `excluded_sources` is passed through.
- **`_should_query_source(source, concept)`** helper — centralised guard for deciding
  whether to query a given external source for a concept:
  - Always `False` for `"tingbok"` (informational only, no upstream lookups).
  - `False` when the source is in `concept.excluded_sources`.
  - `True` otherwise (auto-discover, including sources already in `source_uris`).
- **`_uri_to_source()`** now recognises `https://tingbok.plann.no/` URIs as `"tingbok"`.
### Changed
- **Source label `"package"` renamed to `"tingbok"`** throughout.  The
  `category_by_source/` mirror path now uses the matched concept's actual source
  instead of hardcoding `"local"`, so projects using only the tingbok vocabulary
  see `category_by_source/tingbok/` rather than `category_by_source/local/`.
- **Bundled `vocabulary.yaml` removed** — tingbok is now the sole authoritative source
  for the package vocabulary.  `_get_package_data_dir()` removed.  Local overrides in
  `/etc/inventory-md/`, `~/.config/inventory-md/`, and the current directory continue
  to work as before.  `fetch_vocabulary_from_tingbok()` now raises
  `TingbokUnavailableError` on any network or HTTP error; `parse` and `vocabulary`
  commands abort with `❌ …` and exit code 1 rather than writing a degraded
  `vocabulary.json`.
- **Expansion loop source guards**: all four sources (OFF, AGROVOC, DBpedia, Wikidata)
  now use `_should_query_source()`.  The previous ad-hoc `skip_agrovoc` heuristic
  (skip when concept has a non-AGROVOC URI) is removed; use `excluded_sources:
  [agrovoc]` in `vocabulary.yaml` instead.
- **`_resolve_missing_uris()`** skips concepts whose `source_uris` already contains
  `dbpedia` or `wikidata`, or where both are in `excluded_sources`.

## [v0.6.1] - 2026-02-24

### Fixed
- **Wheel packaging** — removed redundant `artifacts` and `force-include`
  entries for `inventory_md/data/`; `packages = ["src/inventory_md"]` already
  covers git-tracked data files, the duplicate entries caused a 400 error from
  PyPI on upload

## [v0.6.0] - 2026-02-24

### Added
- **Tingbok integration** — inventory-md now fetches the package vocabulary
  from [tingbok.plann.no](https://tingbok.plann.no) by default, with
  transparent fallback to the bundled `vocabulary.yaml` if unreachable
  - New `fetch_vocabulary_from_tingbok()` in `vocabulary.py`
  - `load_global_vocabulary()` gains `tingbok_url` and `skip_cwd` parameters
  - `Config.tingbok_url` property (config key `tingbok.url`,
    env var `INVENTORY_MD_TINGBOK__URL`); defaults to `https://tingbok.plann.no`
  - Set `tingbok.url` to an empty string or `"false"` to disable
- **Direct/REST lookups for DBpedia and Wikidata** — reduces SPARQL load and
  avoids Wikidata rate limiting
  - DBpedia: direct URI construction (Title_Case → resource URL) verified
    with a lightweight SPARQL query, before REST search and full SPARQL
  - Wikidata: MediaWiki Action API (`wbsearchentities` + `wbgetentities`),
    not subject to SPARQL rate limits, before SPARQL label search
  - Wikidata broader concept chain (P31/P279) resolved via REST, making the
    REST lookup path fully SPARQL-free
- **Retry with exponential backoff** for SPARQL and DBpedia REST queries —
  respects `Retry-After` headers on 429s; retries up to 3 times
- **Circuit breaker** — after 5 consecutive endpoint failures, subsequent
  queries are skipped immediately to avoid cascading timeouts
- **SKOS cache directory configurable** via `INVENTORY_MD_SKOS__CACHE_DIR`
  env var; defaults to `~/.cache/inventory-md/skos/`; cache TTL increased
  from 30 to 60 days
- **Multi-source tracking per concept** — new `source_uris` field on `Concept`
  tracks all taxonomy sources (OFF, AGROVOC, DBpedia, Wikidata) that matched
  each concept, with their URIs
  - `_populate_source_uris()` fills `source_uris` from hierarchy-building data
  - `_find_additional_translation_uris()` discovers supplementary DBpedia/Wikidata
    URIs for concepts originally matched via OFF/AGROVOC only
  - Translation phases use `source_uris` directly instead of filtering by URI prefix
  - Search UI shows colored badges for all sources per concept
  - `source_uris` persisted in vocabulary.json for downstream consumers
- **Global vocabulary shipped with package** — default vocabulary bundled in `inventory_md/data/`
  - Multi-location vocabulary loading with merge precedence:
    1. Package default (lowest priority)
    2. `/etc/inventory-md/vocabulary.yaml`
    3. `~/.config/inventory-md/vocabulary.yaml`
    4. `./vocabulary.yaml` or `./local-vocabulary.yaml` (highest priority)
  - New functions: `find_vocabulary_files()`, `load_global_vocabulary()`
- **Language fallback chains** for translations
  - Scandinavian: `nb` → `no` → `da` → `nn` → `sv` → `en`
  - Germanic: `de` → `de-AT` → `de-CH` → `nl` → `en`
  - Romance: `es` → `pt` → `it` → `fr` → `en`
  - Slavic: `ru` → `uk` → `be` → `bg` → `en`
  - Configurable via `language_fallbacks` in config
  - Integrated into AGROVOC (`_get_all_labels`) and OFF (`get_labels`) lookups
  - When a translation is missing, tries related languages before English
  - New functions: `get_fallback_chain()`, `apply_language_fallbacks()`
- **Config file naming** — `config.yaml`/`config.json` now supported in project directory
  - `inventory-md.yaml`/`inventory-md.json` still supported for backward compatibility
- **DBpedia descriptions, Wikipedia URLs, and source attribution**
  - Concepts enriched with short descriptions from DBpedia/Wikipedia
  - Wikipedia article links stored on concepts for UI linking
  - Source attribution tracks which external source provided each concept
- **Local vocab enrichment via DBpedia** — even concepts not in inventory get
  DBpedia metadata (URI, description, wikipediaUrl) when they have a `broader` field
- **`category_by_source` hierarchy preservation** — original source hierarchies
  stored under `category_by_source/<source>/` (OFF, AGROVOC, DBpedia, Wikidata)
  so the raw taxonomy paths survive root mapping
- **Virtual root node** (`_root`) for explicit root control and display ordering
- **Multi-source translation with URI resolution and gap filling**
  - OFF → AGROVOC → DBpedia → Wikidata translation pipeline
  - Each phase fills gaps without overwriting earlier sources
  - Sanity checks reject mismatched labels from every source
- **Wikidata as full independent category source**
  - Concept lookup via Wikidata API
  - Hierarchy building via P31 (instance of) and P279 (subclass of) relations
  - `category_by_source/wikidata/` entries following the same pattern as DBpedia
  - Opt-in via `enabled_sources=["off", "agrovoc", "dbpedia", "wikidata"]`
- **Wikidata translation source and final language fallback pass**
  - Wikidata labels fetched via sitelinks for multilingual coverage
  - Final pass applies `DEFAULT_LANGUAGE_FALLBACKS` to every concept after all
    translation phases, filling gaps like `nb` from `sv`/`da`/`nn`
- **Auto-resolve URIs for local vocab concepts** — new `_resolve_missing_uris()`
  helper batch-queries DBpedia/Wikidata by prefLabel for concepts without URIs,
  enabling translations for previously unreachable concepts

### Changed
- **SKOS lookups routed through tingbok on cache miss** — when `tingbok.url`
  is configured, `SKOSClient` calls tingbok's `/api/skos/lookup` and
  `/api/skos/labels/batch` instead of contacting upstream AGROVOC/DBpedia/Wikidata
  REST APIs directly; network errors fall back to the direct path transparently
- **Skip AGROVOC database load when tingbok is configured** —
  `build_vocabulary_with_skos_hierarchy()` now accepts `tingbok_url` and,
  when set, creates `SKOSClient(use_oxigraph=False)` so the local AGROVOC
  Oxigraph database (~30 s load) is never loaded; upstream SKOS lookups on
  cache misses fall through to the REST APIs as before
- **`Concept.altLabels` changed from `list[str]` to `dict[str, list[str]]`**
  (language → labels) — prevents cross-language false matches (e.g. Norwegian
  "barn" matching English "Barn"); new helpers `get_alt_labels(lang)` and
  `get_all_alt_labels_flat()`; backward compat: flat list wrapped as `{"en": [...]}`
- **Language alias expansion in translation fetch** — `nb↔no` and other aliases
  resolved in all four translation phases (OFF, AGROVOC, DBpedia, Wikidata) so
  OFF's `"no"` labels are fetched and normalised to `"nb"` via fallback chain
- **Distinct `source="package"` for bundled vocabulary** — concepts loaded from the
  package data directory now get `source="package"` instead of `source="local"`,
  making it possible to distinguish package-provided concepts from user-defined ones
- **Wikidata enabled by default** — `enabled_sources` now includes `"wikidata"` in
  all defaults (vocabulary.py, config.py, cli.py); no longer opt-in
- **SPARQL timeout reduced** from 300 s to 30 s
- **Cache empty label results** from succeeded SPARQL queries (to avoid redundant
  re-fetches of concepts with no labels in a given language)
- Merged 18 root categories down to 10: new `recreation` root (outdoor, sports,
  transport); `hardware` absorbs construction and consumables; `household` absorbs
  office, books, documents; `medical` renamed "Health & Safety" and absorbs
  safety-equipment; `hobby` deleted (redundant with transport)
- Renamed `toilet_consumable_paper` → `toilet_paper` in package vocabulary
- Vocabulary deduplication: flat concepts with `broader` are merged into their
  path-prefixed form (e.g., `ac-cable` → `electronics/ac-cable`), removing 138
  orphaned flat duplicates
- Vocabulary slimmed to ~258 concepts (from 596) by removing pure-redirect leaves
- `lang` field written to `inventory.json` so the search UI can auto-detect the
  inventory language; bare `no` in YAML config correctly mapped to language code
- Category label language in search UI initialised from inventory `lang` config
  (was hardcoded to `en`)

### Fixed
- **Parser dropping containers under ID-less structural sections** — sections
  without an explicit `ID:` tag are now treated as organizational wrappers; their
  subsections are still processed as containers but the wrapper itself is not added
  to the inventory; previously a section like "# Oversikt over boksene" caused a
  hard return that silently dropped all 189 containers nested beneath it; hard-coded
  Norwegian/English section name strings removed — configurable via
  `sections.intro` and `sections.numbering_scheme` config keys
- **AGROVOC cross-language mismatches** — leaf URI looked up from the full path
  key; singular/plural variants accepted; false positives from cross-language
  matches eliminated
- **AGROVOC mismatch warnings eliminated** — 14 further false-positive warnings
  during vocabulary build suppressed:
  - AGROVOC lookup skipped when local concept already has a non-AGROVOC URI (9 cases)
  - DBpedia URIs added to mushrooms, lumber, marine_propulsion, medicine (4 cases)
- **altLabel translation map** not using language fallback chain (fixed)
- **Orphan categories promoted** to tree roots for UI visibility
- **Oxigraph startup warning** silenced when `use_oxigraph=False`
- Multi-source translation URI resolution: candidate URIs collected from both
  `all_uri_maps` and `concept.uri`, filtered by source type
- Duplicate connector definitions removed from vocabulary.yaml
- Full broader chain resolution (e.g., `sandpaper-sheet` → `consumables/sandpaper/sandpaper-sheet`)
- OFF mapped roots excluded from URI map to prevent translation mismatches

## [v0.5.0] - 2026-02-04

### Added
- `--version` / `-V` flag to display installed version
- Shell tab completion support via argcomplete
  - Install with `pip install 'inventory-md[completion]'`
  - Activate with `eval "$(register-python-argcomplete inv-md)"`

### Fixed
- `parse` command now respects `skos.enabled` and `skos.hierarchy_mode` config settings even without `--auto` flag

## [v0.4.0] - 2026-01-28

### Added
- QR label generation feature for printing inventory labels **Not tested at all** (sorry - I'll get to it)
  - New `labels` command with `generate`, `formats`, and `preview` subcommands
  - Support for label sheets (configurable formats in mm)
  - Three label styles: standard (QR + ID + date), compact (QR only), duplicate (two QRs)
  - Configurable via config file (`labels.base_url`, `labels.sheet_format`, etc.)
  - `--dupes` option to print multiple copies of each label
- Configuration files
  - Supports `inventory-md.json`, `inventory-md.yaml`
  - Config file may be in the inventory repository, under ~/.config/inventory-md/ or under /etc/inventory-md.
  - If multiple config files are found, data is merged, with local config taking pecedence.
  - All CLI options can be set as defaults in config
  - Environment variables (`INVENTORY_MD_*`) have highest priority
  - Language supported
      - default language for instance
	  - alternative languages for the categories
- Photo registry integration for item-specific photo viewing
  - New `photo_registry.py` parser converts `photo-registry.md` to JSON
  - Parse command generates `photo-registry.json` alongside other files
  - Search interface shows 📷 icon next to items with photos in registry
  - Item-specific lightbox mode for viewing only photos of a specific item
- Proper error handling with tracebacks for server startup
- `update-template` command to refresh search.html to latest version (it's a simple copy actually)
- SKOS vocabulary support for hierarchical tag expansion
  - New `skos` command with `expand`, `lookup`, and `cache` subcommands
  - Queries AGROVOC and DBpedia SPARQL endpoints
  - On-demand lookups with local caching (~/.cache/inventory-md/skos/)
  - Expands simple tags to hierarchical paths (e.g., "potatoes" → "vegetables/potatoes")
  - `--skos` flag for `parse` command to enable SKOS enrichment
  - Category browser in search.html for navigating hierarchical categories
  - Local Oxigraph support for offline AGROVOC lookups
  - DBpedia REST Lookup API support as fallback
  - Multi-language support for category labels (Norwegian, English)
  - Wikipedia links in vocabulary entries
  - Generates `vocabulary.json` with category metadata
- Open Food Facts taxonomy as primary food category source
  - Uses OFF product categories for food item classification
  - AGROVOC mismatch detection with warnings
- New markdown-it-py based parser implementation
- Shared `md-viewer-common.js` library for search interface

### Changed
- Systemd service config path changed to `/etc/inventory-system/`
- Switched HTTP library from `requests` to `niquests` (actively maintained fork)

## [0.3.0] - 2026-01-16

### Added
- `--host` option for `serve` and `api` commands to bind to specific interfaces
- `--api-proxy` option for built-in reverse proxy in `serve` command
- Quick Start Makefile targets (`make quickstart`, `make dev`, `make serve-demo`)
- OCR support for text extraction from images
- Norwegian National Library (nb.no) API for ISBN lookup
- Support for dated wanted-items files in shopping list generator
- Puppet module for automated deployment (puppet-inventory-md)
- GitHub Actions workflows for CI and PyPI publishing
- Pre-commit hooks configuration
- Automatic image discovery from filesystem
  - Parser now scans `photos/{container_id}/` directories for source images
  - Automatically creates missing thumbnails in `resized/{container_id}/`
  - No more manual image list maintenance in markdown
  - Supports `.jpg`, `.jpeg`, `.png`, `.gif` formats
  - Images automatically sorted by filename
  - Uses PIL/Pillow for high-quality resizing (max 800px, quality 85)
- Photo directory metadata support
  - Containers can specify photo directory via `photos:dirname` in heading
  - Allows split containers to share photo directories
- Container-level tag support
  - Tags can be added to container headings (e.g., `tag:jul,påske`)
  - Search interface shows container-level tag badges when filtering
  - Parser extracts metadata from container headings
- Click-to-view full resolution in lightbox
  - Clicking on lightbox image opens full resolution in new tab
  - Zoom-in cursor and tooltip indicate clickability
  - Provides access to original unscaled images

### Changed
- Migrated build system from setuptools to Hatch with hatch-vcs
- Renamed package from `inventory-system` to `inventory-md` as inventory-system is occupied on pypi.
- Default binding changed to localhost (127.0.0.1) for security
- Ruff configuration updated to use recommended rule sets
- **Breaking:** Image references and photo links in markdown are now ignored
  - Images are discovered from filesystem instead of markdown `![...]` syntax
  - Workflow: copy photos to directories → re-parse → done
  - Optional `photos:dirname` metadata may be included
  - Parser no longer parses photo link lines
  - Cleaner markdown files with less clutter
- Parser creates `metadata` field for all containers
  - Includes tags, parent, type, photos, and other metadata from headings

## [0.2.0] - 2025-12-15

### Added
- Multi-language support with English and Norwegian translations
  - Configurable via `LANGUAGE` constant in search.html
  - All UI strings translated (titles, labels, messages, etc.)
- Hierarchical heading parsing for all markdown heading levels (H1-H6)
  - Automatic parent-child relationships inferred from heading structure
  - Supports deeply nested location hierarchies (e.g., boat compartments)
- Dynamic filter button generation based on container ID prefixes
  - No more hardcoded filter buttons for specific series
  - Automatically detects and displays top 10 container prefixes
- Improved container ID generation from headings
  - Sanitizes heading text to create valid IDs
  - Handles special characters and spaces
  - Truncates long IDs to 50 characters
- Demo inventory with comprehensive examples
  - Shows hierarchical organization
  - Demonstrates tagging system
  - Includes sample data for testing
- `.gitignore` file for Python projects

### Changed
- Generic container terminology throughout UI
  - Changed "bokser" (boxes) to "containere" (containers)
  - Removed hardcoded references to specific box series
  - Search placeholder updated to be more generic
- Parser now creates containers for all heading levels, not just H1 and H2
- Heading stack tracking for proper parent inference
- Python version requirement changed to >=3.13,<4.0 (was >=3.14,<4.0)

### Fixed
- Container navigation links now work properly
  - Fixed event bubbling issue with parent links
  - Toggle container function checks if click originated from link
- Filter matching updated to work with dynamic prefixes
  - Uses same prefix extraction logic as filter generation

## [0.1.0] - 2025-12-15

### Added
- Initial release of inventory-md package
- Markdown-based inventory parser
  - Parse inventory.md files into structured JSON
  - Support for hierarchical containers
  - Metadata extraction (ID, parent, type, tags)
  - Image reference parsing
- CLI tool with three commands:
  - `init` - Initialize new inventory
  - `parse` - Parse and validate inventory
  - `serve` - Start local web server
- Web-based search interface
  - Searchable container and item database
  - Lazy-loaded images with lightbox viewer
  - Tag-based filtering with AND logic
  - Gallery view for browsing all images
  - Alias search support
- Package structure with templates
  - Reusable search.html template
  - Aliases.json template for search aliases
  - Example inventory.md template
- Automatic version management with setuptools-scm
- Ruff configuration for code quality
