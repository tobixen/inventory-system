# Process Shopping

## Meta

This is a staged, resumable workflow for turning a shopping trip into:

* a spending **ledger**
* **inventory** entries
* **tingbok** product observations
* **Open Food Facts** product data (optional)
* **Open Prices** prices.

This is the generic guide — uses `$INVENTORY_DIR`, `$PHOTO_DIR`, `$LEDGER` as placeholders;
your personal skill fills in real paths, shops, and credentials.

User may provide information on where things was purchased, what was purchased, etc

## Important

(This is highlighted as "important" not because it is very important, but because the rules are broken on almost every run - and that's annoying).

The procedure is optimized for minimal AI-usage, and a minimum of permission-prompts for the user, but **only if those rules are followed**:

* The procedure in this file should be followed **point by point**.  Commands not listed in the procedure should only be run if the user requests it.
* **Do not** run commands like git, grep, sed to check the status - use the commands provided in the procedure.
* **Do not** chain together commands.
* **Do not** poll for a slow/background command with shell loops (`while kill -0`, `pgrep`, repeated `sleep`).  These are unlisted commands and each one is a permission-prompt — the user is often AFK during this skill and wants it to run unattended.  When a step (e.g. `extract_barcodes.py`, which is slow) is running in the background, simply **stop and wait**: the harness re-invokes you when the command finishes, or you may read its output file **once**.  Never busy-wait.

Exceptions may apply - but if it's needed to run extra commands, it should be considered (together with the user) to improve the documentation, skill files or scripts.

It's allowed to ask the user questions when needed.

The staging file should be the last human gate - it should be approved by the user.  Everything that cannot be reversed trivially (inventory write, tingbok PUT, OFF/Open Prices publish, git commit) happens *after* the staging file is reviewed.

## Procedure

Start a trip with the context command instead of grepping for conventions:
```bash
~/inventory-md/scripts/shopping_context.py "SHOP" --ledger $LEDGER --diary $DIARY
```
It prints, for the shop: the cached Open Prices OSM object, recent staging files
(a schema example to copy), recent **ledger rows** (prior prices, EANs and the
receipt-name/category convention), and recent diary expense lines. That is
deliberately everything you'd otherwise `tail`/`grep` for — so don't.

**Looking something up in the inventory itself** (does an item already exist?
what's in a section?) — use the parsed JSON, never `grep inventory.md`:
```bash
inventory-md lookup --match TERM   # existing items by id/name (e.g. an EAN already stocked)
inventory-md container ID          # contents of a section/container (e.g. 'floating')
```
`jq` on `inventory.json` covers anything else structured. These are exact and
allowlisted; grepping the markdown is neither.

## User instructions

- User should photograph the **receipt at the shop** so its EXIF GPS marks the location
  (used for Open Prices). Photograph product labels **upright and legible** — the
  best-before date is read by OCR, which honours EXIF orientation but can't read
  faint/sideways print.
- For products that exists in OFF, there should be one photo with the barcode and the next should be with the expiry date.  If both fits into the same photo, only one photo is taken.  For photos of products not existing in off, there should be photos of the front, ingrediences, nutrition information and package recycling information.

## Stage 1 — import (deterministic)

```bash
# Barcodes + best-before OCR on every photo (barcode shots included):
~/inventory-md/scripts/extract_barcodes.py --best-before $PHOTO_DIR/IMG_*.jpg --json --out barcodes.json

# Receipt + photos -> human-correctable staging file (EAN candidates via tingbok
# reverse receipt-name search; photos classified barcode/expiry/label):
~/inventory-md/scripts/shop_import.py --receipt RECEIPT.json --barcodes-json barcodes.json \
    --out $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml
```

**One staging file per shop visit** (canonical flat single-shop schema —
`session, shop, currency, items[]`; no multi-shop `shops:` wrapper). If a day
has more than one visit, suffix the file with the shop, e.g.
`shopping-YYYY-MM-DD-lidl.yaml`; the importer rejects a multi-shop file.

Receipt source: a JSON file from a receipt parser, or OCR/read a photographed
receipt into the same shape (`date, shop, total, items[name,price,quantity]`).
The importer emits one row per line item with `ean_candidates`, a classified
`loose_photos` list (each may carry a `bb` from the OCR pass), and `needs_review`
flags. A barcode photo with no date of its own is paired with the date from the
*immediately following* expiry photo, surfaced as `bb` with a `bb_from` pointer
to the source frame; treat a `bb_from` date as a positional guess to sanity-check.
It never decides a match or invents a date.

Photos needs to be manually inspected for barcodes that don't resolves and best-before dates that cannot be read by the OCR.  Run the scripts first and wait for them — the whole point of `extract_barcodes.py`/`shop_import.py` is to make manual photo inspection unnecessary.

Default assumption: each photo holds **nothing but a barcode and/or an expiry date**, and a product's best-before is either in its barcode photo, in the immediately following photo, or supplied by the user.

## Stage 2 — review (AI, or by user in an editor)

Edit the staging file: for each item pick the right `ean` from `ean_candidates`
(or add one), set `name`, `category`, `bb` (from the photo's `bb` candidate, else
`:EST`), `location`, and a unique `inventory_id`. Attach label `photos`. Clear
`needs_review`. **Set `to_tingbok: true` for items with a confirmed EAN,
`to_tingbok: false` for by-weight produce and items without a barcode.** The
importer scaffolds `to_tingbok: null` as a deliberate reminder — leave no item
at `null` before committing. This is the checkpoint to fix mistakes **before**
anything irreversible. Re-running stage 1 is safe (idempotent ledger; staging is yours).

**Categories — be specific.** Use the most specific leaf category, not a broad
bucket (`tomatoes`, not `vegetables`/`vegetable`; `cheese/kashkaval`, not
`cheese`; `food/eggs`, `fresh-milk`). Broad buckets are useless for the
shopping-list generator and expiry tracking, and `check_quality.py` **fails**
on them (`vegetables`, `fruit`, `nuts`, `meat`, `dairy`, `cheese`, `misc`, …).
A broad/parent category is allowed only when no narrower concept fits — then
exempt that item with the tag `category-broad-ok` (or run with
`--allow-broad-categories`). Get the canonical slug with
`inventory-md vocabulary lookup TERM` — it reports the concept `id` to use,
checks the local `vocabulary.json` first and transparently queries tingbok for
concepts not yet in it (exit code 1 in that case, with the tingbok result still
printed — that's expected for a category new to your inventory). Don't invent
slugs, and don't hand-roll `curl` calls to `/api/lookup/`. Watch mistranslated receipt names (Bulgarian
`КАРТОФИ ЛИЛАВИ` "purple potatoes" were actually purple **sweet** potatoes).

**Quantities — count, not weight.** For by-weight produce, `qty` is the piece
**count** (3 peppers), never the kg weight (`qty: 0.543` is wrong). Put the
**total** weight in `mass:` (`543g`) and the per-kg price in `price` with
`price_unit: kg`; the importer writes `qty:3 mass:543g/3 price:EUR:.../kg`
(single piece → bare `mass:543g`). Packaged multi-buys use the total too
(2×1l milk → `volume: 2l` → `volume:2l/2`). **Ask the user for the count**
when it isn't obvious from the receipt.

**tingbok cross-check (gate — the user MUST respond to these before you proceed):**
for every `ean` you assign, compare the tingbok record to what you bought:

- tingbok **has** the EAN and its description **matches** the purchase → fine,
  proceed silently.
- tingbok has the EAN but its description **does not match** (wrong product,
  wrong quantity) → **flag it and stop**; the user MUST confirm or correct the
  EAN before anything irreversible.
- the EAN is **not in tingbok** → **flag it**; the user MUST confirm the EAN.
  This applies to **any** barcoded item, food or not — push it once confirmed
  (use `tingbok_name`/`tingbok_categories` so the new tingbok entry is useful).
- a **food** product is not in tingbok → flag it and encourage the user to take
  front/ingredients/nutrition/packaging photos so it can be posted to OFF.

Batch these flags into one round of questions rather than asking item-by-item.

## Stage 3 — commit (script + thin AI, gated)

**Drive it with `pipeline.py` — one command, not a hand-chained pipeline.**
Once the staging file is reviewed, `pipeline.py` runs the ledger → inventory →
tingbok steps in order (reading/advancing the `status:` block, resumable) and
then validates (`parse` + `check_quality`):
```bash
~/inventory-md/scripts/pipeline.py $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml           # dry run — plan + previews
~/inventory-md/scripts/pipeline.py $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml --commit  # run pending stages + validate
```
A `status:` value of `done` skips a stage; `skipped` skips it permanently (e.g.
`tingbok_push: skipped` only when the visit has **no barcoded items at all** —
NOT for non-food hardware. tingbok is the general EAN/category/**price**
aggregator: barcoded tools, batteries, adhesives and chemicals all belong there
(the food-vs-non-food split governs only OFF vs Open Products Facts). On a stage failure it stops and
leaves the status unchanged, so re-running resumes there. `--from STAGE`
force-restarts at a stage. The remaining steps (photos, publishing,
commit) stay manual — see below. The numbered steps that follow are *what the
driver runs*; run them individually only to debug.

1. **Validate** — every item complete; every item has a unique `ID`; food items
   have a `bb` (or `:EST`); no duplicate IDs. (Folded into the inventory write
   and the final quality gate.)
2. **Ledger** — append/enrich `$LEDGER` (one row per line item):
   ```bash
   ~/inventory-md/scripts/ledger.py import-staging $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml --ledger $LEDGER
   ```
   Append-or-enrich: a raw row from a receipt importer is later filled in place
   with `ean`/`category`/`inventory_id` by the reviewed staging import (matched on
   `date, shop, receipt_name, qty, unit_price, total`; nulls never overwrite).
3. **Inventory** — write every reviewed row straight from the staging file; do
   **not** hand-edit `inventory.md`:
   ```bash
   ~/inventory-md/scripts/inventory_import.py $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml            # dry run — preview the plan
   ~/inventory-md/scripts/inventory_import.py $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml --commit
   ```
   It reads each item's `location` (→ container), `category`, `inventory_id`,
   `ean`, `bb` (`:EST` honoured), `qty`/`unit` (weighed lines → `mass`/`volume`)
   and `price`, formats the line, inserts it in the right section, and runs the
   QA checks as part of the write: duplicate `ID:`, food-without-`bb:` (hard
   error; `--no-bb-check` to override for fresh produce), and category resolution
   (`--strict` to fail on unresolved). `add_to_inventory: false` rows are skipped;
   rows whose `inventory_id` already exists are reported as `exists` and skipped,
   so re-running is safe. Missing `location` defaults to `floating`. So the review
   step (Stage 2) must fill `location`, `category`, `bb` and a unique
   `inventory_id` per row — there is nothing left to edit by hand here.
   This is `inventory-md add` applied per row; see `docs/ADDING-ITEMS.md` for the
   field reference and the single-item CLI.

   **One-off / non-receipt additions** — a single found item, an installed
   fixture, items reconstructed from an order history rather than a scanned
   receipt — use the single-item CLI directly:
   ```bash
   inventory-md add CONTAINER --category LEAF [--tag k:v]… [--ean …] [--qty N] [--price CUR:N/unit] "name"
   ```
   It supports `--tag` (repeatable), `--ean`, `--isbn`, `--qty`, `--mass`/`--volume`,
   `--price`, `--bb`/`--est` and `--id`, picks the container section, and folds in the
   same QA (duplicate-ID, category, bb) as the importer — so there is **still no
   reason to hand-edit `inventory.md`**. Note the trap: `inventory_import.py` does
   *not* write `--tag`, but `inventory-md add` does — needing a tag is **not** a
   licence to hand-edit. The **only** change that justifies touching the markdown is
   **modifying an existing line** (e.g. correcting an EAN), which the append-only
   `add` cannot do.
4. **Photos** (manual) — copy only **label** photos to `photos/LOCATION-ID/`; skip
   barcode/expiry close-ups; skip fast-consumed items. Never `git add` photos.
5. **tingbok** — push price + receipt-name observations for reviewed EANs (a
   merge PUT; prices/receipt_names appended, re-running is safe). Use the script,
   never a raw `curl`:
   ```bash
   ~/inventory-md/scripts/tingbok_push.py $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml            # dry run
   ~/inventory-md/scripts/tingbok_push.py $INVENTORY_DIR/staging/shopping-YYYY-MM-DD.yaml --commit
   ```
   It pushes only items with `to_tingbok: true` and an `ean`; per-item
   `tingbok_name`/`tingbok_categories`/`tingbok_quantity` override a poor or
   missing tingbok name.
6. **Quality gate** — regenerate and check (flags food without best-before,
   duplicate IDs, unresolvable categories). Two separate commands, not chained:
   ```bash
   inventory-md parse inventory.md
   ~/inventory-md/scripts/check_quality.py inventory.json
   ```
7. **Commit** (manual) `inventory.md` (+ staging file, + photo-registry.md if used).
   The ledger is committed in its own repo. (Personal workflows may add extra
   steps here — see the personal skill.)

## Stage 4 — contribute upstream (optional, gated)

**Missing OFF products** (EANs that don't resolve in OFF) — create them from a
curated YAML with front/ingredients/nutrition/packaging photos:
```bash
~/inventory-md/scripts/off_upload.py --products off-products.yaml          # dry run
~/inventory-md/scripts/off_upload.py --products off-products.yaml --commit  # writes to OFF
```

**Open Prices** — publish receipt prices (auth once via `op_auth.py`):
```bash
~/inventory-md/scripts/openprices_publish.py --shop "Shop" --date YYYY-MM-DD \
    --proof RECEIPT.jpg --osm WAY:NNN [--discount EAN=GROSS:SALE] [--commit]
# barcodeless items as CATEGORY prices:
    --no-products --category-price "en:baguettes=0.17,was=0.45,type=SALE"
```
Shop location is a **confirmed** OSM object (cached per shop), never auto-geocoded
— receipt photos are often taken away from the shop. PRODUCT prices must not set
`price_per`. Both OFF and Open Prices are **public** — treat as irreversible-ish
(Open Prices rows are deletable; you own them).

## Queries

```bash
~/inventory-md/scripts/ledger.py query --category food --since YYYY-MM-DD --until YYYY-MM-DD
~/inventory-md/scripts/ledger.py consumed --inventory inventory.md --since … --until …
```
`consumed` joins ledger rows to items removed from `inventory.md` (git history) to
cost what was actually used in a period — only resolves for rows enriched (ean/
category/inventory_id) through the reviewed staging flow.

## Tools

| Script (`~/inventory-md/scripts/`) | Role |
|---|---|
| `shopping_context.py` | read-only trip context: shop OSM, recent staging |
| `extract_barcodes.py --best-before` | barcodes + best-before OCR per photo |
| `bb_dates.py` | OCR-text → best-before date candidates (library) |
| `shop_import.py` | receipt + photos → staging YAML |
| `pipeline.py` | drive Stage-3 commit (ledger→inventory→tingbok→validate) from `status:` |
| `ledger.py` | purchases.jsonl: import / query / consumed |
| `inventory_import.py` | write reviewed staging rows into `inventory.md` |
| `tingbok_push.py` | push reviewed price/receipt-name observations to tingbok |
| `check_quality.py` | validation gate (food-bb, dup IDs, categories) |
| `off_upload.py` | create missing OFF products |
| `openprices_publish.py` / `op_auth.py` | publish prices / mint token |

`tingbok` (`GET/PUT /api/ean/{ean}`, `GET /api/ean/search?receipt_name=`) is the
EAN/category/price aggregator. There is **no `ean_cache.json`** — use tingbok.
Category/concept lookup goes through `inventory-md vocabulary lookup TERM` (no
raw curl). Ad-hoc **EAN** lookup (an EAN that didn't come through
`extract_barcodes.py`, which resolves scanned codes itself) has no wrapper yet —
a read-only `curl GET /api/ean/{ean}` is the sanctioned fallback for that one case.

## TODO

This skill and the scripts are quite fresh.  For each run, try to pinpoint problems and choke-points and suggest ways to improve the procedure.  Some thoughts:

* Almost every time I run the skill, the Claude agent goes off and breaks all the rules in the "important"-section, why is that and how can it be improved?
  * Root cause (2026-06-19): louder warnings don't help — the agent greps because
    `shopping_context.py` didn't surface everything it reaches for, and the rules
    live in a *second* file it reads only after it has already grepped on instinct.
  * Done: `shopping_context.py` now also prints recent **ledger rows** for the shop
    (`--ledger`), so there is no reason to `tail purchases.jsonl`; and the Procedure
    section now points inventory lookups at `inventory-md lookup`/`container` + `jq`,
    never `grep inventory.md`.
  * Still open: hoisting the one hard rule to the very top of the loaded artifact
    (personal SKILL.md / command body), so it is seen *before* the first action.
* Perhaps the directories above should go into a config file?
  * Still open. Would let `shopping_context.py`/`pipeline.py` find `$LEDGER`/`$DIARY`
    without the caller passing them each run. Mild win; only pursue if the path-passing
    keeps biting.
* Quantity vs mass — **mostly resolved** by the Stage-2 "Quantities — count, not weight"
  section (qty = piece count; total weight in `mass:`; per-kg price with `price_unit: kg`;
  packaged multi-buys use the total; ask the user for the count). Remaining decision:
  * Pin down per-unit vs total notation: the importer writes `mass:450g/3` (total/count),
    while `qty:3 mass:150g` (per-pack) was the original wish — pick one and document it.
  * The "rename ledger `qty`→`purchase-qty`" idea is **not** worth doing: the importer
    already distinguishes `mass`/`volume` from the count, so it would be churn.
* Ad-hoc EAN lookup (2026-07-02): category lookups now go through
  `inventory-md vocabulary lookup`, but looking up a *manually read* EAN (from a
  photo the scanner missed) still needs a raw `curl GET /api/ean/{ean}` →
  permission prompt. Consider `inventory-md ean EAN` or a `tingbok_lookup.py`
  helper so the whole skill runs unattended.
* Shop OSM cache too coarse — Lidl/Billa have **many branches per city**, so even
  "Lidl Varna" names one specific store.
  * Done: `match_shop_osm` now refuses to silently pick among multiple matches (returns
    nothing and lists the candidates); cache keys re-keyed to include the branch street.
  * When caching a new shop, key it by branch (shop + street), and confirm the OSM object
    is that exact store before publishing Open Prices.
