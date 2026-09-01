# Inventory Scripts

Loose scripts that work directly on an inventory, alongside the `inventory-md`
CLI. Two kinds live here, and the difference matters when something breaks:

- **Standalone**: `analyze_inventory.py`, `export_tags.py`, `find-space-in-series.py`
  and `migrate-tags.py` read `inventory.json` (or `inventory.md`) with nothing
  but Python 3.10+.
- **Not standalone**: `extract_barcodes.py` and `sync_eans_to_inventory.py` need
  optional extras (pyzbar, Pillow, niquests; easyocr for OCR), and
  `find_expiring_items.py` / `lookup_items.py` are thin wrappers that import the
  installed `inventory_md` package.

`release.sh` is a maintainer tool (tag, push, update the AUR package), not an
inventory script. Anything that graduated into the package is documented under
[Graduated to the CLI](#graduated-to-the-cli) rather than here.

## Scripts

### analyze_inventory.py

Comprehensive analysis of an inventory file, printing statistics about containers, items, images, tags, and hierarchy.

```bash
# Analyze inventory in current directory
python scripts/analyze_inventory.py

# Analyze specific inventory
python scripts/analyze_inventory.py ~/furusetalle9-inventory/inventory.json
```

**Output includes:**
- Container counts (total, empty, with/without images)
- Item statistics (total, tagged, untagged)
- Top 15 tags by frequency
- Hierarchy analysis (parent/child relationships)
- Data quality summary

### find-space-in-series.py

Prints the unused IDs of a numbered container series, so a newly packed box can
be given a free ID without reading through the whole inventory.

```bash
# All free numbers in C-01..C-99
python scripts/find-space-in-series.py C

# Just the next free one
python scripts/find-space-in-series.py C -n 1

# A different series, a different inventory, a shorter range
python scripts/find-space-in-series.py TC ~/furusetalle9-inventory/inventory.json --max 20
```

Existing IDs are matched case-insensitively, with an optional `-`/`_`/space
separator and any amount of zero padding: zero padding *should* carry no
meaning, so `C-01`, `C1` and `c 001` are read as the same box. Where two
differently-spelled IDs turn out to be two real boxes (`A5` and `A05` both
exist in `~/furusetalle9-inventory`), the number counts as taken and a warning
goes to stderr — that is a labelling problem to fix on the physical boxes, not
in the data. The match is anchored: `TC-01` belongs to the `TC` series, not
to `C`.

What it prints is the *canonical* spelling — uppercase prefix, dash, two digits
— whatever the existing IDs look like. A series written `A38` in the markdown
will therefore be offered `A-38`; that is the intended form, but note that the
rest of the toolchain does not yet treat the two as one container (see
`docs/TODO.md`). `--max 100` or higher widens the padding to keep one series
sorting as text, and `--start 0` covers a series that numbers from zero, as
`FM-0` does.

**Exit codes:**
- `0` - at least one free ID found
- `1` - the series is full (raise `--max` or pick another prefix)
- `2` - bad arguments, or inventory file missing or unreadable

### extract_barcodes.py

Reads barcodes, QR codes and (optionally) best-before dates off product photos.

```bash
./extract_barcodes.py photos/F-01/*.jpg
./extract_barcodes.py --lookup 5701234567890      # one EAN/ISBN, no images
./extract_barcodes.py --best-before photos/*.jpg  # OCR the dates too
```

Needs `pyzbar` and `Pillow` (system `libzbar0`) plus `niquests`; `easyocr` for
the OCR paths. `./extract_barcodes.py --help` documents the rest.

### sync_eans_to_inventory.py

Scans the photo directories, extracts barcodes, and adds the EANs that are
missing from the matching container in `inventory.md`. Dry-run by default.

```bash
./sync_eans_to_inventory.py                   # show what would be added
./sync_eans_to_inventory.py --apply           # write it
./sync_eans_to_inventory.py --container F-01  # one container only
```

Same barcode dependencies as `extract_barcodes.py`, and it imports
`inventory_md`, so the package must be installed.

### migrate-tags.py

One-off migration from comma-separated tags to the hierarchical format, driven
by `tag-mapping.json` in the repository root.

```bash
./migrate-tags.py --dry-run inventory.md   # preview
./migrate-tags.py inventory.md             # apply
```

### export_tags.py

Export tag statistics in various formats for reporting or further analysis.

```bash
# Text output (default)
python scripts/export_tags.py inventory.json

# CSV output (for spreadsheets)
python scripts/export_tags.py inventory.json --format csv > tags.csv

# JSON output (for processing)
python scripts/export_tags.py inventory.json --format json > tags.json
```

**Available formats:**
- `text` - Human-readable table
- `csv` - Comma-separated values
- `json` - Structured JSON

## Usage Examples

### Quick Health Check

```bash
cd ~/furusetalle9-inventory
inventory-md-check-quality
```

### Generate Full Report

```bash
cd ~/furusetalle9-inventory
python ~/inventory-md/scripts/analyze_inventory.py > report.txt
```

### Compare Two Inventories

```bash
# Generate stats for both
python scripts/analyze_inventory.py ~/furusetalle9-inventory/inventory.json > furusetalle9-stats.txt
python scripts/analyze_inventory.py ~/solveig-inventory/inventory.json > solveig-stats.txt

# Compare
diff furusetalle9-stats.txt solveig-stats.txt
```

### Export Tags for Review

```bash
python scripts/export_tags.py inventory.json --format csv | sort -t',' -k2 -nr > tags-sorted.csv
```

## Graduated to the CLI

Three things that used to be scripts in this directory are now part of the
package, so that other projects can depend on them by name rather than by path:

| Was | Is now |
|---|---|
| `scripts/check_quality.py` | `inventory-md-check-quality` (module `inventory_md.check_quality`) |
| `scripts/find_expiring_items.py` | `inventory-md expiring` — the script survives as a thin wrapper |
| `scripts/lookup_items.py` | `inventory-md lookup` — likewise |

`inventory-md-check-quality` is the data-quality gate. It takes an
`inventory.json` path (default: `inventory.json` in the current directory) and
reports at three levels:

- **ERROR** — duplicate container IDs, parent references pointing at no
  container, and categories that are too broad (`--allow-broad-categories`, or
  a per-item `category-broad-ok` tag, waives the last one)
- **WARNING** — items tagged `TODO`, items with no category, categories the
  vocabulary cannot resolve, food with no best-before date, and shop-specific
  EANs that never got a chain prefix
- **INFO** — empty containers, missing descriptions, containers with no images,
  and category IDs that differ only in separator or plural form
  (`cling-film`/`clingfilm`, `lentil`/`lentils`) — reported rather than
  repaired, because which spelling is canonical is not yet settled

`-v` for detail, `--fix-categories` to apply the suggested category
replacements, `--no-tingbok` to keep it offline. Exit status is 1 if there were
errors, 0 otherwise.

## Integration with inventory-md

These scripts complement the main `inventory-md` CLI:

1. Run `inventory-md parse` to update JSON from markdown
2. Run the analysis scripts, or `inventory-md-check-quality`, to review the data
3. Use the insights to improve the inventory

## Adding to PATH

For convenience, add the scripts directory to your PATH:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$PATH:$HOME/inventory-md/scripts"

# Then use directly
analyze_inventory.py ~/furusetalle9-inventory/inventory.json
find-space-in-series.py C
```

The console scripts (`inventory-md`, `inventory-md-check-quality`) are installed
on the PATH by pip and need none of this.
