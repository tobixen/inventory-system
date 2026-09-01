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

### 353 of 1736 concepts have no parent

Re-measured in `~/solveig-inventory/vocabulary.json` on 2026-09-01 (was 342 on
2026-08-13, so drifting upward). A fifth of the tree is roots, which is why the
category browser reads as a flat list of oddities — `comma_splice`, `brunost`
and `dolmas` are all top-level. Of the 353: **98 inventory-sourced** (labels
tingbok resolved to nothing, so a local stub with no parent), **134
tingbok-sourced** (a gap in the hierarchy, tracked in `~/tingbok/TODO.md`) and
121 `inferred`, parents synthesised locally that never got a parent of their own.

Two pieces of this are done:

* ~~Nine pathed concepts with no path parent~~ — **fixed 2026-09-01**. These
  were not top-level oddities but invisible: `epoxy/filler`, `epoxy/hardener`
  and `epoxy/pigment` all existed with no `epoxy` concept, and the root list
  excludes anything with a "/" in its id, so they were reachable from nowhere at
  all. `build_category_tree()` now creates the missing path ancestors first.
* ~~Near-duplicates (`cling-film` *and* `clingfilm`)~~ — **reported 2026-09-01**
  by `inventory-md-check-quality`, at INFO: 51 groups differing only in
  separator and 14 only in plural form. Deliberately not repaired; see below.

What is left is the decision, and it is still open: **what should an
unresolvable label do?** A local stub at the root is a defensible answer; the
complaint is only that nobody chose it deliberately. The alternative worth
considering is a holding node, the way `category_by_source` works, so the
browser's top level shows real categories and the unresolved ones are one click
away.

Note the near-duplicate finding cuts against the framing above: **46 of the 65
groups have both spellings marked tingbok-sourced**. `bike_hardware` is in
tingbok's `vocabulary.yaml` and `bike-hardware` is not — the inventory wrote the
latter, tingbok resolved it on its own, and the result is two concepts. So this
is not only about labels tingbok failed to resolve; it is also about labels it
resolved twice. Which spelling is canonical (dashes or underscores, singular or
plural) is an open question in `~/tingbok/TODO.md`, and normalising in this
project would decide it by accident — hence a report and not a rewrite.

### Auto-write `category:` back into the inventory markdown

`parse` resolves and enriches categories from EAN lookups, but the result only
reaches `inventory.json` — the markdown line keeps whatever was typed. Writing it
back would make the enrichment durable and reviewable in git.

`inventory-md edit --category` already rewrites a line in place and is the manual
version of exactly this, so the mechanism exists; what is missing is the decision
about when a lookup is confident enough to edit the user's file unasked.

### ~~Optional tingbok fallback~~ — done 2026-09-01

New `tingbok` extra and `inventory_md.tingbok_embedded`: where the tingbok
package is installed and `tingbok.plann.no` does not respond, the vocabulary,
the batch resolve, the ancestor chains and the source registry are answered
in-process through tingbok's new `tingbok.embedded` entry point. Reads only —
an EAN observation is a write to the service's data file, and a failed push
stays a failed push.

Two things this needed that were not obvious from the original note: tingbok had
no supported in-process entry point (reaching into `tingbok.app`'s private
globals from here would break on any refactor there), and `POST
/api/vocabulary/resolve` had to grow an `offline` flag, since a caller that
reaches the fallback has no network and the default would fall through to
DBpedia for every unknown label.

The dependency review it asked for: `mcp` is not a dependency of this project
and never was — nothing under `src/` imports it and it appears in no extra.

### `vocabulary.py` is a second implementation of tingbok's data model

Raised in `docs/code-review-2026-05-08.md`, still open at the 2026-06-11 review,
which called it the biggest architectural ROI in the codebase. `vocabulary.py`
carries:

* a `Concept` dataclass mirroring tingbok's `VocabularyConcept` Pydantic model —
  two representations of one thing, kept in sync by hand;
* `build_category_tree()`, which re-derives hierarchy (inferred parents, stub
  nodes, `category_by_source` virtual nodes) from the flat list tingbok serves.
  If tingbok changes how hierarchy works, this breaks silently;
* ~~`_cache_read`/`_cache_write` … **7 days here, 60 days there**~~ — **fixed
  2026-09-01**, both 60 days now, and tingbok's comment claiming they already
  matched is gone too. The two caches remain separate, which is fine: they cache
  different things at different layers;
* ~~`_SOURCE_LABELS` and `_uri_to_source()`~~ — **done 2026-09-01**. tingbok
  serves `GET /api/sources`, and the new `inventory_md.sources` module consumes
  it. The bundled table survives as the offline fallback but no longer has to be
  *updated*, which was the actual defect.

What is left is `Concept` and `build_category_tree()`, and here the framing
above needs correcting. "Most of this can be deleted rather than fixed, but only
after tingbok serves the answers" is only half true, and the ancestors endpoint
(added to tingbok 2026-09-01) proved it: **nothing was deleted**. A second code
path was added — `is_descendant_of()` consults tingbok for a concept the local
vocabulary cannot place, `check_quality` uses it for food classification more
than one hop from `food` — and both of those are real improvements, but neither
removes the local walk.

The reason is structural and will not change: `parse` generates a
`vocabulary.json` that a **static web UI reads with no server in the loop**, and
an inventory is routinely parsed with tingbok unreachable. `build_category_tree()`
therefore has to keep working offline whatever tingbok's API grows. What
"serve a pre-built tree" (tracked in `~/tingbok/TODO.md`) actually buys is that
tingbok becomes *authoritative* — the local build becomes a fallback whose
divergence is a bug rather than a design — not that the client shrinks. Worth
doing for that reason; not worth doing while expecting a deletion.

So the honest remaining task here is smaller than "delete a second
implementation": make `build_category_tree()` a documented offline fallback,
prefer a served tree when one is available, and compare the two so a divergence
is noticed.

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

### Container IDs that differ only in separator or padding are different containers

`A38` and `A-38` are meant to be the same box, and `A-38` is the spelling to
standardise on. `find_container_section()` casefolds an ID before comparing
(`parser.py:636-646`), but does nothing about the separator or the zero
padding, so `A-38` simply does not resolve against a `## ID:A38` heading —
verified: it returns `None`, and `add_item()` then raises
`ValueError: Container ID:A-38 not found`.

That is at least a loud failure rather than a duplicate container, so this is a
usability item, not a data-corruption one. But `~/furusetalle9-inventory`
writes its boxes `A1`, `A5`, `A38` with no separator throughout, and
`scripts/find-space-in-series.py` deliberately prints the canonical `A-38` — so
today the tool's advice and the tool's own writers disagree, and the heading has
to be renamed by hand before the ID it recommends can be used.

Worth noting while in there: a separator-less series interacts badly with the
prefix fallback. Against that same file, `A3` resolves to `A38` — unambiguously,
so no `AmbiguousContainerError` — which is fine when `A3` does not exist and
surprising when somebody expects it to be created.

Normalise on comparison — strip `-`/`_`/space, drop leading zeros, casefold —
in one place that both the parser and the writers use. Two questions to settle
first: whether `AmbiguousContainerError` should fire when normalising makes two
existing headings collide, and what the writers should do about a file whose
headings are inconsistent (rewrite them, or leave them and match loosely).

**Separately, and physically:** zero padding *should* be insignificant, but in
`~/furusetalle9-inventory` it is not. `A5` and `A05` are two different boxes,
as are `G5`/`G05` and `G6`/`G06`. That is a labelling problem to fix on the
boxes themselves, not something the code should be taught to support;
`find-space-in-series.py` warns when it sees such a pair.

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
