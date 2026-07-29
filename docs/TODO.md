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

**The big one, and the least finished.** See `docs/TODO-CATEGORIES.md` for the
detail; it is a live document, not a leftover.

The SKOS category work has a fully-ticked task list and still did not end up as
intended — the checklist measured features delivered, not whether categorising a
real inventory got easier. Treat that list as history and `TODO-CATEGORIES.md` as
the current state.

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

This is the extraction half of a goal shared with purchase-pipeline. Associating
an extracted date with the *right item* — pairing a barcode photo with the expiry
in that photo or the immediately following one, and matching both to a receipt
line — happens in `purchase_pipeline.shop_import` (`classify_photo_result()`) and
is tracked there. Neither half delivers the goal alone.

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
