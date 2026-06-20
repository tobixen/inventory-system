# Inventory Maintenance Guide

Regular maintenance helps keep your inventory searchable, organized, and useful. This guide outlines recommended tasks and their frequency.

## Quick Reference

| Task | Frequency | Command/Action |
|------|-----------|----------------|
| Run quality check | Weekly | `python scripts/check_quality.py` |
| Full analysis | Monthly | `python scripts/analyze_inventory.py` |
| Sync EANs from photos | Monthly | `scripts/sync_eans_to_inventory.py` |
| Process TODO items | As needed | Review items tagged `TODO` |
| Add missing categories | Monthly | See [ADDING-ITEMS.md](ADDING-ITEMS.md) |
| Review category coverage | Quarterly | Check unresolved labels in quality report |
| Manual photo check | Quarterly | See [Photo Guidelines](#photo-guidelines) |
| AI photo verification | As needed | See [AI-Assisted Photo Verification](#ai-assisted-photo-verification) |
| Backup photos | Monthly | Ensure photos are backed up |

---

## Analysis Scripts

The `scripts/` directory contains tools for analyzing inventory data quality.

### Quality Check (Weekly)

```bash
cd ~/your-inventory
python ~/inventory-md/scripts/check_quality.py
```

This identifies:
- **ERRORS**: Duplicate IDs, missing parent references (fix immediately)
- **WARNINGS**: Items tagged `TODO` (review and resolve)
- **INFO**: Untagged items, empty containers, missing descriptions, non-canonical categories

To automatically fix non-canonical categories in `inventory.json`:
```bash
python ~/inventory-md/scripts/check_quality.py --fix-categories
```
Note: this only fixes `inventory.json` (the generated file). The source `inventory.md`
must be fixed manually — edit categories directly, then re-run `inventory-md parse`.

### Full Analysis (Monthly)

```bash
python ~/inventory-md/scripts/analyze_inventory.py
```

Provides comprehensive statistics:
- Container and item counts
- Tag coverage percentage
- Top tags by frequency
- Hierarchy analysis
- Image coverage

Use this to track progress over time. Consider saving reports:
```bash
python ~/inventory-md/scripts/analyze_inventory.py > reports/$(date +%Y-%m).txt
```

### Tag Export

```bash
# View all tags sorted by frequency
python ~/inventory-md/scripts/export_tags.py

# Export to CSV for spreadsheet analysis
python ~/inventory-md/scripts/export_tags.py --format csv > tags.csv
```

---

## Item Format and Tagging

For the full reference on item fields, categories, tags, quantities, and best-before dates, see **[ADDING-ITEMS.md](ADDING-ITEMS.md)**.

During maintenance, ensure every item has at least a `category:` and an `ID:`. Items missing these should be the top priority when reviewing.

---

## Barcode Sync

Photos may contain product barcodes (EAN/UPC/ISBN) that aren't yet recorded in inventory.md. The sync script scans all photo directories, extracts barcodes, and identifies missing EANs:

```bash
cd $INVENTORY_DIR

# Dry-run: see what would be added
~/inventory-md/scripts/sync_eans_to_inventory.py

# Actually update inventory.md
~/inventory-md/scripts/sync_eans_to_inventory.py --apply

# Process only a specific container
~/inventory-md/scripts/sync_eans_to_inventory.py --container F-01
```

The script:
- Scans `photos/{container}/` directories for barcodes
- Checks if each EAN exists in the corresponding container in inventory.json
- Looks up unknown products in Open Food Facts
- Adds missing items to inventory.md (with `--apply`)

After running with `--apply`, regenerate the JSON:
```bash
inventory-md parse inventory.md
```

Probably it's only needed to do this once - though it may be an idea to run the script on all the photos every now and then, to catch situations where the photos wasn't scanned during insertion, or perhaps improvements in the scanning algorithms.

---

## Photo Guidelines

The content of every box/container/location should have a photo directory `photos/$ID`.  (Downscaled photos are made available by the scripts, mirrored under `resized/`.

Photo directories may be tagged in the markdown file with `photos:$DIRNAME`.  Those taggings are reserved for cases where the photo directory deviates from the ID - typically because one folder contains a mix of photos of different boxes.  The markdown file should not be cluttered with taggings when it's not needed.

### Regular maintenance

For each photo directory:

* Check if the photo directory matches something in the inventory.  Photo directories that does not match the inventory files either means something is missing in the inventory or that the photo directory should be renamed.  Other times things have simply been removed from the inventory.  Obvious things should be fixed on the go, difficult things should go through the `TODO.md` first
* Check every photo
  * Is it likely that the photo is in the wrong directory?  Obvious things should be fixed on the fly, difficult things noted in TODO.md
  * Does the photo show anything that is not explicitly listed in the inventory list?  If so, add it to the inventory list.
  * Does the photo show additional details (specifications, colors, brands, etc) in additon to those already listed in inventory.md?  Search the web for specifications if some article number etc is found.  Add to the inventory list.
  * Are there things that exists in the inventory, but not in the photos?  Add an item to the TODO-list to take more photographs or verify the content.

### AI-Assisted Photo Verification

Claude Code can help with photo verification by viewing photos and comparing them against inventory entries. See `~/inventory-md/claude-skills/process-inventory-photos.md` for detailed instructions.

**Basic workflow:**

1. **Check photo timestamps**: `ls -la photos/{BOX_ID}/` to see when photos were taken
2. **Check git history for removed items**: Photos may show items that have since been removed from inventory
   ```bash
   git log -p --all -S "ID:{BOX_ID}" -- inventory.md | head -100
   ```
3. **View photos and compare**: Claude reads photos and compares visible items against current inventory
4. **Update inventory.md**: Add missing items, enhance descriptions with brand names/specifications
5. **Update photo-registry.md**: Map each photo to the items visible in it
6. **Commit changes**: Document what was verified

**Important considerations:**

* If photos are older than recent inventory changes, items may have been removed - check git history before adding "missing" items back
* Mark removed items in photo-registry.md with a note like "(removed)" rather than re-adding them to inventory
* Add brand names, model numbers, colors, and other details visible in photos
* Match the language style used elsewhere in the inventory (some instances use Norwegian, others English)
* Run the barcode extractor on photos to find EAN/UPC codes (see [Barcode Sync](#barcode-sync-monthly))
* Look up barcodes, product numbers, and article numbers on the internet to find full specifications
* Search for visible text like article numbers, model numbers, or brand names to identify items precisely

---

## Managing TODO Items

Items tagged `TODO` need review - they're typically:
- Unidentified items
- Items needing categorization
- Duplicates to verify
- Items to relocate

### Reviewing TODOs

1. Run quality check to list all TODOs:
   ```bash
   python scripts/check_quality.py 2>&1 | grep "TODO item"
   ```

2. For each TODO item, either:
   - **Identify it**: Remove `TODO` tag, add proper tags
   - **Relocate it**: Move to correct container
   - **Dispose of it**: Remove from inventory if discarded
   - **Keep as TODO**: If still uncertain, leave for next review

### Example TODO Resolution

Before:
```markdown
* tag:TODO Noe skinngreier
```

After investigation:
```markdown
* tag:klær,personlig Skinnhansker og skinnbelte
```

---

## Aliases

There used to be an `aliases.json` file - TODO: search through all code, scripts and documentation - any references to this should be removed.

Alias searching is now done through the category system.  All categories have AltLabels and a PrefLabel, in different languages.

--

## Container Descriptions

Descriptions help users understand what's in a container without reading every item.

### Adding Descriptions

In `inventory.md`, add text between the heading and items:

```markdown
## ID:A5 Box with holiday items

Easter and Christmas decorations, mostly ornaments and lights.

* tag:påske Easter eggs
* tag:jul Christmas ornaments
```

### Good Descriptions Include

- General category of contents
- Size range (for clothes)
- Condition notes
- Location hints

### Examples

```markdown
## ID:D04 - vacuum bag

Vacuum-packed winter clothes for children, sizes 8-10 years.

* tag:klær,barn Winter jacket
```

```markdown
## ID:E01 - tools and screws

Basic tools for daily use. Kept in hallway for easy access.

* tag:verktøy Hammer
* tag:verktøy Screwdriver set
```

---

## Photo Maintenance

### Checking Photo Coverage

```bash
# Containers without photos
python ~/inventory-md/scripts/analyze_inventory.py | grep "Without images"

# List specific containers missing photos
python -c "
import json
with open('inventory.json') as f:
    data = json.load(f)
for c in data['containers']:
    if not c.get('images'):
        print(c['id'])
"
```

### Photo Registry

The `photo-registry.md` file maps individual photos to specific items, enabling:
- Photo icons (📷) next to items in search results
- Clicking to view only photos of that specific item
- Filtered photo galleries based on search/tag filters

**IMPORTANT:** When assigning an `ID:xxx` in photo-registry.md, that same ID must also be added to the corresponding item in inventory.md. The ID must exist in BOTH files:
- In inventory.md: `* tag:category ID:item-name Item description`
- In photo-registry.md: `| IMG_xxx.jpg | ID:item-name |`

Without this, the photo-to-item cross-referencing will not work.

**Format:**
```markdown
## Session: 2026-01-03

### TB-03

| Photo | Item IDs |
|-------|----------|
| IMG_001.jpg | ID:drill-bosch |
| IMG_002.jpg | ID:wrench-force17, ID:drill-bosch |
| IMG_003.jpg | (overview) |
```

When you run `inventory-md parse`, it automatically generates `photo-registry.json` containing:
- `photos`: Map of filename → {items, container, session, notes}
- `items`: Reverse index of item ID → list of photo filenames
- `containers`: Map of container ID → list of photo filenames

See `claude-skills/process-inventory-photos.md` for detailed instructions on maintaining the photo registry.

### Photo Organization

Photos are stored in `photos/{container_id}/`:
```
photos/
├── A1/
│   ├── IMG_001.jpg
│   └── IMG_002.jpg
├── A2/
│   └── photo.jpg
```

---

## Troubleshooting

### "Duplicate container ID" Error

Two containers have the same ID. Search for duplicates:
```bash
grep -n "^## ID:" inventory.md | sort -t: -k3 | uniq -d -f2
```

### Items Not Appearing in Search

1. Check if item is tagged
2. Check category spelling — use `inventory-md vocabulary lookup LABEL` to verify resolution
3. Regenerate JSON: `inventory-md parse inventory.md`

### Photos Not Showing

1. Check photo exists in `photos/{container_id}/`
2. Check file extension (must be .jpg, .jpeg, .png, or .gif)
3. Regenerate: `inventory-md parse inventory.md`

---

## Maintenance Checklist

### Weekly
- [ ] Run `check_quality.py`
- [ ] Address any ERRORS immediately
- [ ] Review new TODO items

### Monthly
- [ ] Run `analyze_inventory.py`
- [ ] Add tags to untagged items (target: 10-20 items)
- [ ] Add descriptions to containers without them
- [ ] Review and resolve TODO items
- [ ] Verify backups are current

### Quarterly
- [ ] Review category coverage (check unresolved labels in quality report)
- [ ] Check photo coverage for important containers
- [ ] Archive old reports
- [ ] Review empty containers (consolidate or remove)
