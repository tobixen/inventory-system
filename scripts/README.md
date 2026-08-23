# Inventory Analysis Scripts

Standalone Python scripts for analyzing inventory data. These scripts work directly with `inventory.json` files and have no dependencies beyond Python 3.10+.

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

### check_quality.py

Focused data quality checker that identifies issues requiring attention.

```bash
# Check inventory in current directory
python scripts/check_quality.py

# Check specific inventory
python scripts/check_quality.py ~/furusetalle9-inventory/inventory.json

# Verbose output
python scripts/check_quality.py -v inventory.json
```

**Checks performed:**
- Duplicate container IDs (ERROR)
- Missing parent references (ERROR)
- Items tagged TODO (WARNING)
- Untagged items (INFO)
- Empty containers (INFO)
- Missing descriptions (INFO)
- Containers without images (INFO)

**Exit codes:**
- `0` - No errors found
- `1` - Errors found
- `2` - File not found or other error

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
python ~/inventory-md/scripts/check_quality.py
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

## Integration with inventory-md

These scripts complement the main `inventory-md` CLI:

1. Run `inventory-md parse` to update JSON from markdown
2. Run analysis scripts to review the data
3. Use the insights to improve the inventory

## Adding to PATH

For convenience, add the scripts directory to your PATH:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$PATH:$HOME/inventory-md/scripts"

# Then use directly
analyze_inventory.py ~/furusetalle9-inventory/inventory.json
check_quality.py
```
