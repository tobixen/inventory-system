# Process Inventory Photos

Process photos of inventory locations (boxes, shelves, cupboards, storage areas) and update the inventory system.

For item format details (categories, quantities, best-before, IDs, etc.) see `docs/ADDING-ITEMS.md`.

## Trigger
Use when the user asks to process inventory photos, e.g.:
- "process photos from PATH"
- "there are new inventory photos"
- "process the new photos"

## Workflow

### 1. Find and count photos

```bash
ls $PHOTO_DIR/PATTERN* | wc -l
ls $PHOTO_DIR/PATTERN*
```

If no pattern is given:
```bash
find $PHOTO_DIR -type f -mmin -60
```

ALL photos must be processed.

### 2. Extract barcodes FIRST

Before analyzing photos visually, extract any barcodes to get product info:

```bash
~/inventory-md/scripts/extract_barcodes.py $PHOTO_DIR/PATTERN*.jpg
```

This will:
- Extract any EAN/UPC barcodes visible in the photos
- Look up product info in Open Food Facts
- Output product names, brands, and quantities

**Use this output while analyzing photos** — you'll already know what many products are.

### 2b. Manual barcode/article lookups

For items not in Open Food Facts, try manual lookups:

**BILTEMA articles** (Art. XX-XXXXX format — a catalogue number, *not* a
scannable EAN barcode):
- Try: `https://www.biltema.no/search?q=XXXXX`
- Record as a shop-prefixed EAN: `EAN:biltema-XXXXXX` (lowercase shop name,
  hyphen dropped: `Art. 46-3491` → `EAN:biltema-463491`).

**Clas Ohlson articles** (XX.XXXX-X format):
- Try: `https://www.clasohlson.com/no/search?q=XXXXXXX`
- Record as `EAN:clasohlson-XXXXXXX`.

**EAN codes**: Always include in inventory as `EAN:XXXXXXXXXXXXX`.

**Shop-local codes generalise to any shop** — the shops named above are only
examples. Any shop-local identifier with no global barcode gets prefixed with
that shop's name: `EAN:<shop>-<code>` (`biltema-`, `clasohlson-`, `lidl-`,
`kaufland-`, `praktiker-`, …). Two patterns:
- **Catalogue / article numbers** (not scannable barcodes) — as with Biltema /
  Clas Ohlson above.
- **In-store barcodes** in the GS1 restricted range (first digit `2`), used by
  many retailers for by-weight / loose goods, e.g. Lidl `20241988` →
  `EAN:lidl-20241988`. These *are* scannable, but the number is assigned by the
  shop and is **not globally unique** — different chains reuse the same number —
  so the shop prefix disambiguates. (The bare code may still resolve in Open
  Food Facts; that is exactly *why* the prefix is needed.)

`check_quality.py` warns about both un-prefixed forms: first-digit-`2` in-store
codes and bare numbers that aren't a valid GTIN length (catalogue numbers).

**Always record from photos:**
- EAN/UPC barcodes
- Article/product numbers (Art., Prod.nr, Item No.)
- Model numbers
- Serial numbers (for valuable items)
- Best-before dates (`bb:YYYY-MM-DD`)
- Batch/lot numbers (for recalls)

### 3. View photos to identify boxes and items

- Look for container labels, or ask the user. Labels are often in the format A-03, TB-42, etc.
- When some pictures are missing a label, the container is often the same as for the previous photos.
- Identify items with details: brand, model, specifications, part numbers.
- Use the barcode extraction output from step 2 for product identification.
- Note items that are unclear with `tag:TODO`.

### 3b. Ask about unclear items using structured questions

After viewing all photos, collect unclear items and ask the user using the AskUserQuestion tool with multiple-choice options. Group related questions together (up to 4 per call).

Examples:
- "Is the black square item in photo X a solar panel?" → "Yes, folding solar panel" / "No, something else"
- "Are photos X and Y showing the same bag or different bags?" → "Same bag" / "Two different bags"

### 4. Create/update photo-registry.md

Map each photo to visible items:

```markdown
## Session: YYYY-MM-DD

### CONTAINER-ID

| Photo | Item IDs |
|-------|----------|
| IMG_xxx.jpg | ID:item-name |
| IMG_yyy.jpg | ID:item-a, ID:item-b |
| IMG_zzz.jpg | (overview) |
```

**Special entries:** `(overview)`, `(box label)`, `(blurry)`, `(not in inventory)`, `(best-before: DATE)`

**IMPORTANT:** When you assign an `ID:xxx` in photo-registry.md, you MUST add that same ID to the corresponding item in inventory.md. The ID must exist in BOTH files for photo-to-item cross-referencing to work.

### 5. Copy photos to correct directories

```bash
mkdir -p $INVENTORY_DIR/photos/CONTAINER-ID/
cp SOURCE_PHOTOS $INVENTORY_DIR/photos/CONTAINER-ID/
```

### 6. Update inventory.md

Add items with categories, IDs, quantities, and measurements. See `docs/ADDING-ITEMS.md` for full field reference.

```markdown
* category:concept ID:item-id qty:N mass:Xg Item description (brand, model)
```

### 7. Commit changes

```bash
cd $INVENTORY_DIR
git add inventory.md photo-registry.md
git commit -m "Add CONTAINER-ID items from photo session DATE"
```

## Barcode Lookup

If you can see an EAN in a photo that was not automatically extracted:

```bash
~/inventory-md/scripts/extract_barcodes.py --lookup EAN_CODE
```

## Photo Registry JSON Generation

When running `inventory-md parse`, the system automatically:
1. Parses `photo-registry.md` if it exists
2. Generates `photo-registry.json` with:
   - `photos`: filename → {items, container, session, notes}
   - `items`: item ID → [filenames]
   - `containers`: container ID → [filenames]

This enables the search.html web interface to show 📷 icons and item-specific photo galleries.

## Notes

- Photos are NOT stored in git (listed in .gitignore)
- Use sync-photos.sh to rsync photos to server
- Items needing clarification get `tag:TODO`
- Storage locations are not limited to boxes — can be shelves, cupboards, drawers, boat compartments, any named area
