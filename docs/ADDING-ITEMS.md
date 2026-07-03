# Adding Items to the Inventory

This guide covers the data format and field conventions for inventory items, and
how to add a single found item and (optionally) contribute it upstream — without
going through the full shopping pipeline. For the bulk, receipt-driven workflows
(processing a shopping trip, processing a batch of container photos) see the skill
files under `claude-skills/`.

## Adding an item from the CLI

The preferred way to add an item is `inventory-md add`, which appends a
correctly-formatted line to a container's section and runs the quality checks
(duplicate `ID:`, food-without-`bb:`, category resolution) as part of the write:

```bash
inventory-md add food1 --category milk --bb 2026-07 --volume 1l "Whole milk 1l"
inventory-md add food1 --category potatoes --bb 2026-09 --est --mass 1200g Potatoes
inventory-md add A2 --category hammer --id bosch-hammer "Bosch hammer"
```

- `--id` is optional; if omitted a readable ID is generated from the category
  leaf, with the date appended for food (e.g. `milk-2026-06-14`).
- Food items without a `--bb` are rejected (pass `--no-bb-check` to override, e.g.
  for fresh produce that will be dated later via `inventory-md lookup`).
- An unresolved category is a warning; `--strict` turns it into an error.

The rest of this document describes the underlying line format, for reference and
for hand-editing.

## Moving an item between containers

When you repack physical storage — emptying a shelf into a crate, consolidating
boxes — use `inventory-md move` instead of hand-editing, which risks duplicating a
line or orphaning its sub-bullets:

```bash
inventory-md move wd40-200ml TB-23            # relocate the item into TB-23
inventory-md move sealant-soudal TB-24 --dry-run   # preview source → destination
```

- The destination container must already exist (create the section first).
- Only items that exist as a single `ID:` bullet can be moved; free-text list
  entries without an ID are not addressable. Any indented sub-bullets under the
  item move with it.
- `--dry-run` reports the source and destination container and the line that would
  move, without writing.

## Looking up a barcode (EAN)

Before adding a barcoded item, check whether the product is already known. Ask
**tingbok** — it is the single source: it answers from its own records and
transparently delegates to Open Food Facts when it doesn't know, so there is no
need to query OFF directly. This is **product/EAN** lookup — distinct from the
`/api/lookup/LABEL` *category* resolution described under
[Categories](#categories); do not use the category endpoint for an EAN.

```bash
curl -s https://tingbok.plann.no/api/ean/EAN                        # one product
curl -s "https://tingbok.plann.no/api/ean/search?receipt_name=NAME"   # by receipt name
```

From a photo, extract the barcode and look it up in one step:
```bash
scripts/extract_barcodes.py --lookup EAN
scripts/extract_barcodes.py --best-before PHOTO.jpg --json   # also OCRs the best-before
```

If tingbok returns "not found" (it found nothing and OFF has nothing either), the
product is new: add it to the inventory now (above), and consider contributing it
upstream ([below](#publishing-a-found-item-upstream)).

### Shop-local codes: prefix with the shop name

Not every code in the `EAN:` field is a global GTIN. Many shops sell items that
carry a shop-local identifier and no global barcode. Any such code must be
namespaced as `EAN:<shop>-<code>` (lowercase shop name). Two common patterns —
both apply to *any* shop, not just the examples given:

* **Shop catalogue / article numbers** — not scannable barcodes at all. E.g.
  Biltema `Art. 46-3491` → `EAN:biltema-463491` (drop the internal hyphen);
  likewise Clas Ohlson, Praktiker, etc.
* **In-store barcodes** in the GS1 restricted range (first digit `2`), used by
  many retailers for by-weight / loose goods. E.g. a Lidl weighed-goods code
  `20241988` → `EAN:lidl-20241988`.

Use whichever shop the item actually came from as the prefix (`biltema-`,
`lidl-`, `kaufland-`, `praktiker-`, …).

Why prefix: these numbers are **not globally unique** — different chains reuse
the same number for different products — so the shop name is needed to
disambiguate. (The bare code may still resolve in Open Food Facts; many in-store
codes do. That is *why* the prefix matters.) tingbok stores such codes under the
same shop-prefixed key; a real GTIN never contains a hyphen. `check_quality.py`
warns about any un-prefixed shop-local code.

## Item Line Format

Items are bullet points inside a container section in `inventory.md`:

```markdown
## ID:container-id Container description

* category:CONCEPT ID:item-id EAN:EANCODE bb:YYYY-MM qty:N mass:Xg PRODUCT NAME
```

Fields may appear in any order but the human-readable description should come last.

## Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `category:` | Yes | What the item IS (see [Categories](#categories)) |
| `ID:` | Yes | Unique identifier for cross-referencing |
| `tag:` | Optional | Attributes: condition, ownership, colour, etc. |
| `qty:` | Optional | Count of identical items |
| `mass:` | Optional | Net mass per unit (e.g. `mass:500g`, `mass:1.2kg`) |
| `volume:` | Optional | Volume per unit (e.g. `volume:1l`, `volume:400ml`) |
| `bb:` | Food/perishables | Best-before date (see [Best-before dates](#best-before-dates)) |
| `price:` | Optional | Price at purchase point (e.g. `price:EUR:2.49/pcs`) |
| `value:` | Optional | Sujective value estimate |
| `EAN:` | When known | Product barcode |
| `ISBN:` | When known | For books |

An item line may cover multiple identical items (e.g. six cans of beans). If items on the same line differ in expiry date or purchase price, split them onto separate lines.

Each line should have a unique ID.  If none is given, then use something readable (i.e. `id:dads-yellow-jacket`.  For food items, consider postfixing the ID with purchase/discovery date.  `id:carrots-2026-05-09`.

## Categories

A **category** classifies what an item IS — `milk`, `hammer`, `trousers`, `multimeter`. Every item should have at least one.  Tags rather than categories should be used for properties like ownership, color, condition, etc) can be

Use the `category:` prefix.

```markdown
* category:milk
* category:hammer
* category:potatoes
```

**Syntax details:**
- Simple label: `category:potatoes` — preferred
- Full path: `category:food/vegetables/potatoes` — allowed
- Multiple categories: `category:oatmeal,breakfast` — comma-separated
- Hierarchical disambiguation: use `category:hardware/nut` or `category:food/nuts` rather than `category:nuts`

All categories should be resolvable through Tingbok:
```
https://tingbok.plann.no/api/lookup/LABEL
```

**Be as specific as possible**.

**Examples:**
- **Don't use:** `category:vegetables`, `category:fruits`, `category:hardware`
- Dairy: `category:milk`, `category:cheese`, `category:yogurt`
- Vegetables: `category:potatoes`, `category:onions`, `category:carrots`
- Bread: `category:bread`, `category:baguette`
- Condiments: `category:soy sauce`, `category:ketchup`, `category:mayonnaise`
- Seafood: `category:salmon`, `category:tuna`, `category:shrimp`
- Tools: `category:hammer`, `category:drill`
- Clothes: `category:clothes/winter`, `category:trousers`

## Tags

Tags describe attributes of an item — condition, ownership, colour, size, intended user, etc. Use `tag:` prefix. Multiple tags are allowed.

```markdown
* category:trousers tag:old tag:children Winter trousers, size 128
* category:drill tag:brand:makita tag:condition:used Makita drill
```

Common cross-cutting tags: `tag:TODO` (needs review), `tag:condition:new`, `tag:condition:used`.

## Quantities and Measurements

- `qty:N` — number of identical items (e.g. `qty:6` for six tins)
- `mass:Xg` / `mass:Xkg` — **net mass per unit**. Use `mass:total/qty` for non-uniform items.
- `volume:Xl` / `volume:Xml` — volume per unit. Use for liquids; rarely combined with mass.

**Divisor convention** for non-uniform items: if 1.2 kg of onions were bought, counted as six, and four remain, write `qty:4 mass:1200g/6` — the average mass per onion is 200 g, giving ~800 g estimated total.  If the quantity of onions is unknown, then use just `mass:1200g`.

Do not round weights down to zero (e.g. 43 g of garlic → `mass:43g`, not omitted).

## Best-before Dates

Food and perishable items should include a `bb:` field.

**Formats:** `bb:YYYY-MM`, `bb:YYYY-MM-DD`, `bb:YYYY-MM-DDTHH:MM`

If the date is estimated rather than printed on the product, append `:EST`:

```markdown
* category:milk bb:2026-06-12 Whole milk 1l
* category:potatoes bb:2026-08:EST qty:4 mass:1200g/6 Potatoes
```

Note: Norwegian law distinguishes a soft "best before (often still good)" from a hard "use by (safety deadline)". No convention exists yet in this system to distinguish them.

**Typical shelf-life estimates** (for `:EST` use):
- Fresh milk: ~10 days from purchase
- Potatoes (cool/dark): ~3 months
- Chocolate: ~6–8 months
- Fresh bread: 3–5 days
- Bananas: 5–7 days

To find expiring items:
```bash
cd $INVENTORY_DIR
inventory-md parse --auto
inventory-md expiring             # items already expired
inventory-md expiring --limit 10  # top 10 soonest to expire
inventory-md expiring --before 2026-06
inventory-md expiring --food      # food only (uses vocabulary.json)
inventory-md expiring --all       # everything with a best-before date
```

To resolve specific items (including fresh produce with no best-before date yet),
use `inventory-md lookup`:
```bash
inventory-md lookup --id bacon-pikok --match onion --match tomato
```

The `scripts/find_expiring_items.py` and `scripts/lookup_items.py` wrappers accept
the same arguments and call these subcommands.

## Price and Value

- `price:CURRENCY:AMOUNT/UNIT` — what was paid (e.g. `price:EUR:2.49/pcs`, `price:NOK:49.90/kg`)
- `price:CURRENCY:AMOUNT` — The `/pcs` is optional.  It's informative if the avocadoes are sold per piece, but not so much if buying a bathtub, laptop or winter jacket.
- `value:CURRENCY:AMOUNT` — a subjective value estimate

When buying a bundle, record the **net per-unit price** (total paid ÷ quantity), not the list price.

The value of an item is of course non-trivial.  The real value may even be negative if it's difficult to discard the item.  The subjective value may be higher than the market value, nobody may want to buy your old sleeping bag, but if you use it often it may be almost as valuable as a new sleeping bag, as the alternative to using the old one may be to buy a new one.

## Publishing a found item upstream

You do **not** need the `/process-shopping` skill to record a single item you
found. After `inventory-md add`, optionally share the product so future lookups
resolve. Both targets are **public / irreversible-ish** — only post data you have
verified against the physical product.

### tingbok — for any barcoded product

The shopping pipeline's pusher, `scripts/tingbok_push.py`, is not coupled to the
rest of the pipeline — it reads a staging YAML and PUTs a merge (existing
prices/receipt_names are appended to, not overwritten). For a single found item,
hand-write a minimal staging file and run it directly:
```yaml
# found-item.yaml
session: 2026-06-15
shop: ""                 # found at home — no shop/price/receipt
currency: EUR
items:
  - ean: "3800214924577"
    to_tingbok: true
    tingbok_name: <name>
    tingbok_categories: [meats, dry sausages]
    tingbok_quantity: 550g
```
```bash
scripts/tingbok_push.py found-item.yaml            # dry run
scripts/tingbok_push.py found-item.yaml --commit   # actually PUT
```
An item with no `receipt_name`/`price` pushes only name/categories/quantity (no
empty receipt or price rows). Drop in `receipt_name`, `price` and `unit` if you do
have a receipt.

### Open Food Facts — food only, when tingbok didn't have the EAN

Curate a YAML and run `off_upload.py` (dry run first, then `--commit`):
```bash
scripts/off_upload.py --products off-products.yaml            # dry run
scripts/off_upload.py --products off-products.yaml --commit   # writes to OFF
```
```yaml
products:
  - code: "3800214924577"          # EAN, as a string
    lang: bg                       # product's own language
    product_name_bg: <name as printed>
    product_name_en: <English name>
    brands: <brand>
    quantity: 550 g
    categories: Meats, Prepared meats, Sausages, Dry sausages
    stores: <shop>
    countries: Bulgaria
    images:
      front:       /path/to/front.jpg
      ingredients: /path/to/ingredients.jpg
      nutrition:   /path/to/nutrition.jpg
      packaging:   /path/to/packaging.jpg
```
For a **new** OFF product, photograph **front, ingredients, nutrition and
packaging/recycling** info — legible and upright (OCR honours EXIF orientation
but can't read faint/sideways print). For a product that **already exists** in
OFF, one barcode photo plus one best-before photo is enough (a single photo if
both are legible in one frame). Auth uses your logged-in OFF browser-session
cookie — no password in the script.
