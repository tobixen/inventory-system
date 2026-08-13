# TODO — inventory-md

**Scope.** This project owns the inventory format and its tooling: parsing,
`add`/`edit`/`move`/`lookup`/`container`/`ean`, the vocabulary system,
`check_quality`, labels, the web UI, and barcode/best-before extraction from
photos. Identifying a physical object is inventory's business; deciding what a
*purchase* means is not — the receipt → ledger → publish layer lives in
[purchase-pipeline](https://github.com/tobixen/purchase-pipeline), and tasks about
receipts, prices, accounting or upstream publishing belong in its `TODO.md`.

Completed work is not kept here — the CHANGELOG records what shipped. What stays
behind after a task is done is only a decision or a negative result worth not
repeating.

---

## Categories and the vocabulary system

**The big one, and the least finished.**

The SKOS category work has a fully-ticked task list and still did not end up as
intended — the checklist measured features delivered, not whether categorising a
real inventory got easier. Treat that list as history.

Where the work lives: the category *data* — the vocabulary, the sources, the
hierarchy, the translations — is [tingbok](https://tingbok.plann.no)'s, and tasks
about it belong in `~/tingbok/TODO.md`. What is left here is how an inventory
*consumes* that data: resolving a category string on an item line, merging local
vocabulary on top, and degrading when tingbok is unreachable.

### 342 of 1736 concepts have no parent

Measured in `~/solveig-inventory/vocabulary.json` on 2026-08-13 (generated
2026-08-06 against a tingbok returning 200). A fifth of the tree is roots, which
is why the category browser reads as a flat list of oddities — `comma_splice`,
`brunost` and `dolmas` are all top-level.

The half that is this project's: **89 of those roots are inventory-sourced**,
i.e. labels tingbok resolved to nothing, so `vocabulary.py` created a local stub
with no parent. Some are near-duplicates of each other (`cling-film` *and*
`clingfilm`, `brie` *and* `bries`) and want normalising or aliasing before
anything is asked of tingbok. Of the remaining 253, **132 are tingbok-sourced**
and unparented — a gap in the hierarchy, tracked there — and 121 are `inferred`,
parents synthesised locally that never got a parent of their own.

Before treating this as a bug, decide what an unresolvable label *should* do. A
local stub at the root is a defensible answer; the complaint is only that nobody
chose it deliberately.

### Auto-write `category:` back into the inventory markdown

`parse` resolves and enriches categories from EAN lookups, but the result only
reaches `inventory.json` — the markdown line keeps whatever was typed. Writing it
back would make the enrichment durable and reviewable in git.

`inventory-md edit --category` already rewrites a line in place and is the manual
version of exactly this, so the mechanism exists; what is missing is the decision
about when a lookup is confident enough to edit the user's file unasked.

### Optional tingbok fallback

Make tingbok an optional dependency: if the library is installed and
`tingbok.plann.no` does not respond, call it directly instead of failing.

This also wants a review of which dependencies are optional at all — `mcp` is
clearly not needed for this.

### "Package vocabulary" is a name for something that no longer exists

`vocabulary.py` still calls it the "package vocabulary" — five times in comments
and docstrings, plus the `pkg_vocab` local — for what is now simply the tingbok
vocabulary; the function those comments describe is
`fetch_vocabulary_from_tingbok()`. Nothing bundles a vocabulary any more. Almost
entirely a rename, but it misleads on every read.

### `vocabulary.py` is a second implementation of tingbok's data model

Raised in `docs/code-review-2026-05-08.md`, still open at the 2026-06-11 review,
which called it the biggest architectural ROI in the codebase. `vocabulary.py`
carries:

* a `Concept` dataclass mirroring tingbok's `VocabularyConcept` Pydantic model —
  two representations of one thing, kept in sync by hand;
* `build_category_tree()`, which re-derives hierarchy (inferred parents, stub
  nodes, `category_by_source` virtual nodes) from the flat list tingbok serves.
  If tingbok changes how hierarchy works, this breaks silently;
* `_cache_read`/`_cache_write`, paralleling tingbok's own cache, with the TTLs
  set independently in the two projects — **7 days here, 60 days there**;
* `_SOURCE_LABELS` and `_uri_to_source()`, i.e. knowledge of which sources exist.

Most of this can be deleted rather than fixed, but only after tingbok serves the
answers — an ancestors endpoint, a pre-built tree, source names and language
chains, all tracked under "Serve hierarchy answers instead of making clients
compute them" in `~/tingbok/TODO.md`. Deleting first is not an option: the
duplication exists precisely because there is nothing to call yet.

### `sync_eans_to_inventory.py` should be a CLI subcommand

`inventory-md sync-eans`. Photo scan → EAN extract → tingbok lookup → markdown
insertion is a pipeline, not a one-off admin script, and the other three scripts
of that weight (`find_expiring_items`, `lookup_items`, `check_quality`) have all
graduated into the package.

The tests it lacked in May exist now (`tests/test_sync_eans_to_inventory.py`),
and the June round removed its duplicated barcode plumbing and section-scanning,
so what is left is genuinely just the move.

### `parse` does much more than parse

`parse_command` (`cli.py:175`) parses, thumbnails, generates listings, fetches
vocabulary, looks up EANs, pushes observations to tingbok and generates the
shopping list — about 300 lines. A command named `parse` writing to a network
service is surprising.

The June review added `--no-push` and fixed the leaked `niquests.Session`, but
explicitly left the rest: split the function into testable stages, and add an
`--offline` mode that means it.

### Odds and ends in `api_server.py`

Module-level mutable state — `inventory_data`, `inventory_path`, `aliases`
(`api_server.py:23-25`) — makes the server awkward to test and is the last
survivor of the 2025-12-28 review's structural findings. A small state class
behind a `Depends()` was the suggestion.

Related and smaller: eight `except Exception` handlers remain, each flattening a
real error into a string. The bare `except:` forms are gone.

---

## Barcode and best-before extraction from photos

### The undecoded-barcode heuristic is about half false positives

`looks_like_undecoded_barcode()` flags a photo that decoded to nothing but holds
a barcode-like pattern, so a photo whose barcode is torn or blurred is not
silently dropped. It fires on **15 of 47 photos** from the 2026-07-24/25 set, and
a hand-labelled sample of 6 came out roughly half false.

* True positives: both diving-mask shots (`IMG_20260725_0106*.jpg`, label torn
  through the quiet zone), and `IMG_20260715_123241.jpg` — a blurred sideways
  yoghurt label whose `3800207823016` is legible to a human and invisible to
  zbar. Exactly the case the flag exists for.
* False positives: `IMG_20260710_162936.jpg`, a charcoal bag whose artwork has
  decorative vertical stripes; and `IMG_20260724_174109.jpg`, a Billa receipt,
  whose `#####` separator rows are as vertically coherent as any barcode. Every
  shopping trip photographs a receipt, so that one fires every time.

What the heuristic actually separates is "busy striped region" from "blank or
plain", not "barcode" from "other striped things".

**Negative result, don't retry:** run-length periodicity does not discriminate.
Barcode bars were expected to be aperiodic (widths 1–4 modules) and `#####` rows
regular, but over the labelled sample the modal-run fraction (0.21–0.32 barcode
vs 0.21–0.57 noise), distinct-run count (11–13 vs 8–12) and mean run width
(3.5–5.6 vs 2.5–5.2) all overlap — the charcoal bag is statistically
indistinguishable from the real barcode. A useful test probably has to be
structural rather than statistical: look for the EAN guard pattern (`101` …
`01010` … `101`) at a plausible module width, which is what actually makes a
barcode a barcode.

### Best-before OCR is not reliable enough to skip reading photos

Goal: the agent never has to open a product photo. `extract_barcodes.py` should
extract every best-before date printed on a label, so a caller receives `ean` +
`bb` already populated and only genuinely unresolved items get flagged.

Today expiry OCR is hit-or-miss and the agent falls back to reading photos
itself. Orientation is handled (`extract_text_ocr_oriented()` auto-rotates), but
not the rest: dotted/dot-matrix printer fonts, curved and foil surfaces, low
contrast on white-on-white embossing.

This is the extraction half of a goal shared with purchase-pipeline, and it is
now the only half still open. Associating an extracted date with the *right item*
— pairing a barcode photo with the expiry in that photo or the immediately
following one, and matching both to a receipt line — was done on 2026-07-30 in
`purchase_pipeline.photo_match` (moved there out of `shop_import`): a scan fills
a receipt line's `ean`/`bb` when the line's own EAN candidates corroborate it,
and anything unsettled comes back flagged with a reason instead of guessed.

Two things that half now expects of this one:

* a `status: needs_review` or `NO_DECODE` result is routed to the reviewer as a
  `barcode_conflict` / `undecoded` photo carrying no EAN, and a `rejected` losing
  read is dropped — so those verdicts are worth keeping exactly as they are;
* a date this extractor cannot read stays unread all the way through. Nothing
  downstream invents one, which is why the accuracy of this half is now the whole
  of what stands between a trip and a staging file nobody had to open a photo for.

---

## Labels

### QR label printing needs testing with physical labels

The CLI feature exists (`inventory-md labels`); it has never been run against a
real sheet or a real printer.

* Pre-print sheets of labels (e.g. Avery 5260) with sequential IDs.
* QR codes link to the web UI (`https://inventory.example.com/item/ID`).
* Consider dedicated label printers (Brother QL-700, Dymo).
* Prior art worth reading: <https://hay-kot.github.io/homebox/tips-tricks/>

Sketch of the ID scheme: two letters and one digit. The **first** letter selects
the label variant — very small labels carrying only a QR code for small items;
bigger labels with QR code, visible ID text and possibly a print date for bigger
items (perhaps two stickers each); and the same again in sheets of ~6 copies for
labelling a container on every side. The second letter and the digit increment.

---

## Inventory format and data model

### Age ranges for children's items

Something like `age:6-8`. Undecided whether this is a `tag:` convention, a first-
class metadata key, or a category concern.

### Decide what the inventory repo should track about photos

Original ask: the inventory git repo should list the filenames of all photos —
backups run separately, but the listings are needed to roll photos out to the
right places.

Current state (measured in `~/solveig-inventory` on 2026-07-29): `photo-registry.md`
**is** tracked and holds 1712 filenames mapped to items and containers, which
covers the original purpose. `photo-listings/` is gitignored as generated. The gap
is that the registry only covers photos that have been *processed* — an unprocessed
photo appears in neither. Decide whether that matters before doing any work: if it
does, track a generated manifest; if not, close this.

---

## Web UI and deployment

### A demo site that shows off the features

The system runs two real inventories, "Solveig" (boat) and "Furuset" (home),
neither of which should go public. `example/` exists as a third, demo instance but
does not exercise much — it should be built out to demonstrate the features
properly (categories, expiry, search, labels, photos).

---

## Ideas, not yet tasks

* **Immich integration** — no defined scope. Photos are synced outside git and
  registered in `photo-registry.md`; what Immich would add over that is the
  question to answer before this becomes a task.
