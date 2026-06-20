# SKOS-Based Category System

## Design thoughts

Disclaimer: Most of the "design thoughts" here was written by a human.  Starting from "overview" further below, most was written by AI.   I will look through and merge together the information properly at some point in the future ... when/if I get time.

### SKOS

I generally think "don't reinvent the wheel" is a good idea - as well as "follow the standards", even when the standards are too complex or designed by people seeing the world with very different eyes than my own.

According to Wikipedia, "Simple Knowledge Organization System (SKOS) is a W3C recommendation designed for representation of thesauri, classification schemes, taxonomies, subject-heading systems, or any other type of structured controlled vocabulary" - so it sounded just perfect.  The AI warned me that it would be too complex, I was possibly wrong to ignore that warning.

### Categories vs tags vs ...

SKOS is currently used for categories - while most things that does not fit into a category system should be put into tags.  Consider two worn out red cotton T-shirt owned by dad.  T-shirt is a category, while ownership, size, condition, quantity, color etc are other "dimensions".  For quantity etc the inventory-md supports qty, mass, volume ... the rest should go into tags.

### Public databases

Perhaps I started in the wrong end here - because usage of SKOS in itself is sort of just establishing the database schema - what is more important here is actually to get access a global public category database.   Two SKOS-based databases was found - AGROVOC is a public SKOS database for food products and agricultural purposes, and DBpedia is a Wikipedia-based database.  We're also accessing some few databases to look up EANs - one of them is the OpenFoodFacts database, it has it's own category system (not SKOS-based), so it was decided to use the OFF category system as a third source.

TODO: We're using some other EAN source as well - and it does spit out some categories.  We should try to utilize that, too.

### Scope

The scope of inventory-md is to be a general domestic inventory database, used both for food products, clothes, kitchen equipment, electronics, household items, hobby items, tools, sports equipment, more specialized equipment, and in general just everything.  I'm not only using it in a house, I'm using it on my yacht too.  The system should work universally - but the design is not very scalable, so it's not designed for industrial usage.

AGROVOC has an agricultural focus.  This does not only limit its scope, but it also puts some color to the vocabulary.  For instance, in a domestic setting the category "bedding" may include various douvets, pillows, matresses and bedclothes, but according to AGROVOC "beddings" are products optimized for absorbing animal pee.

DBpedia has a more general focus, but for different reasons it's not very well-suited for inventory-md as it's currently (2026-02) designed.

OFF has a food/kitchen focus.  The big advantage of OFF is that by scanning EANs, it's at least theoretically possible to get the correct category directly into the inventory list without manually slapping categories on stuff and without using AI.

### Hiearchical categories

The idea of using "hierarchical categories" came before I started investigating SKOS.  Hierarchical categories seems intuitive for users, though particularly DBpedia does not play very well with this design.  Perhaps some other navigation system should be made.

When only leaning on DBpedia, OFF and AGROVOC, I got thousands of root-nodes in the hierarchy.  For the hierarhical navigation to work out, we need relatively few root nodes (10 is probably a good number, 100 is too much), and every root node should have relatively few children (5-10 is probably a good number, 100 is way too much).  I see no problem with having multiple paths to the same category (though it may be a bit silly when some of the paths are just irrelevant for the item in the category).

As for now we've ended up with a package-global vocabulary.  The purpose of this vocabulary is mostly to bring down the number of root nodes in the category system.  The vocabulary is not intended to be a stand-alone vocabulary, it serves mostly as a **linking layer** - mapping concepts from external databases (OFF, AGROVOC, DBpedia) into a clean hierarchy optimized for domestic inventory use.

### Advantages of public databases

Perhaps it would be easier to just have a simple package-local category list and drop all the complexity with SKOS and external databases, but they do give us some benefits:

* Translation into many languages
* Particularly the OFF-database (and our other EAN sources) offers automatical catgorization - no need to add this by hand or by AI
* Descriptions (even translated descriptions) (TODO: I'd like to present those in the web ui)
* Richness - we may actually need access to thousands of categories.  Particularly for the shopping list generator - we do not want a product (i.e. with a specific EAN) on the shopping list, we want a category (like "nuts" or "peanuts", "jam" or "strawberry jam", "milk" or "full-fat fresh milk" dependent on how detailed one wants the shopping list.  Ok, perhaps none of the exernal databases have "full-fat fresh milk", but that's beside the point)
* Some kind of standard adherence, in case the user wants to use the inventory database in other contexts.

### Vocabulary Loading

The vocabulary is now loaded from multiple locations with merge precedence:

1. **Package default** (`inventory_md/data/vocabulary.yaml`) - lowest priority
2. **System config** (`/etc/inventory-md/vocabulary.yaml`)
3. **User config** (`~/.config/inventory-md/vocabulary.yaml`)
4. **Instance-specific** (`./vocabulary.yaml` or `./local-vocabulary.yaml`) - highest priority

Later files override earlier ones, allowing users to customize or extend the default vocabulary without modifying the package.

In addition, concepts are loaded from OpenFoodFacts, AGROVOC and DBpedia.

### Language Fallback Chains

For translations, the system supports language fallback chains. When a label isn't found in the preferred language, it tries related languages before falling back to English, examples:

- **"Bokmål" → Scandinavian**: `nb` → `no` → `da` → `nn` → `sv` → `en`
- **German → Germanic**: `de` → `de-AT` → `de-CH` → `nl` → `en`
- **Spanish → Romance**: `es` → `pt` → `it` → `fr` → `en`

This leverages mutual intelligibility between related languages.  (This is particularly important for languages like Norwegian, where some sources may use the no tag while others may use the nb tag.  It's not only important for the understanding, but also for estethical reasons - though, when it comes to estethics, it may be my subjective point of view.

Fallbacks are integrated into both AGROVOC and OFF translation lookups. When fetching labels for multiple languages, the system automatically queries fallback languages and fills in missing translations. This can be disabled with `use_fallbacks=False` in the API.

## Overview

The category system provides hierarchical classification for inventory items using SKOS (Simple Knowledge Organization System) vocabularies. Items can be classified using semantic categories that enable "find all food items" or "show all tools" searches.

## Current Status

### Implemented

- **Parser support** - `category:path/to/concept` syntax in inventory.md
- **Vocabulary module** - `src/inventory_md/vocabulary.py` for building category trees
- **Tingbok lookups** - cross-language label/concept resolution and SKOS source
  enrichment (AGROVOC/DBpedia/Wikidata/OFF) are delegated to the
  [tingbok](https://tingbok.plann.no) service. inventory-md no longer ships its own
  local SKOS client or AGROVOC/Oxigraph database; the historical `skos` subcommand
  and `parse --skos`/`--hierarchy` flags are gone.
- **CLI commands**:
  - `inventory-md parse` - Parses inventory and enriches categories via tingbok
    automatically when a `tingbok.url` is configured
  - `inventory-md vocabulary lookup <term>` - Look up a concept by label (local
    `vocabulary.json`, falling back to a tingbok query; supports `--lang`)
  - `inventory-md vocabulary list/tree/search` - Inspect the local vocabulary
- **Configuration** - `tingbok.url` in the config file (see also `lang`)
- **Category mappings** - `vocabulary.json` includes `categoryMappings` for search expansion
- **search.html category browser** - Collapsible tree UI with expand/collapse, counts, search
- **Conditional category UI** - Category browser hidden when vocabulary.json missing or empty
- **SKOS path expansion in UI** - Category badges and filters use expanded SKOS paths
- **Plural normalization** - "books" → "book", "potatoes" → "potato"
- **Source priority** - DBpedia for non-food terms, AGROVOC for food terms

- **Global vocabulary** - shipped with package, loaded from multiple locations with merge precedence
- **Open Food Facts** - OFF taxonomy client for food categorization
- **Path normalization** - Collapse duplicate path components (e.g., `food/foods` → `food`)
- **Root category control** - Local vocabulary mappings reduce orphan root categories

## Two Category Modes

### 1. Path Mode (Current Default)

User defines explicit category paths in inventory.md:

```markdown
* category:food/vegetables/potato ID:P1 Potatoes from garden
* category:tool/garden/shovel ID:T1 Garden shovel
```

Categories are stored as-is. The hierarchy is inferred from path separators.
SKOS enriches with prefLabel/altLabels but doesn't change paths.

**Use when**: You want full control over your category structure.

### 2. SKOS Hierarchy Mode (Planned)

User writes simple labels, system expands to full AGROVOC hierarchy:

```markdown
* category:potato ID:P1 Potatoes from garden
```

System expands to: `food/plant_products/vegetables/root_vegetables/potato`

All food items end up under a unified "food" root, enabling "show all food" queries.

**Use when**: You want automatic organization based on AGROVOC's agricultural vocabulary.

## Usage

### Basic Category Syntax

```markdown
* category:food/vegetables ID:VEG1 Mixed vegetables
* category:book tag:condition:good ID:B1 Cookbook
* category:tool/power/drill tag:brand:makita ID:T1 Makita drill
```

- `category:` - Product classification (what is this)
- `tag:` - Attributes (what state is it in)

### Configuration

Create `inventory-md.yaml` in your inventory directory:

```yaml
lang: nb                 # Inventory language; used as the tingbok lookup language

tingbok:
  url: https://tingbok.plann.no  # Category/EAN lookup service (set to "" to disable)
```

### CLI Commands

```bash
# Parse inventory (categories enriched via tingbok when tingbok.url is configured)
inventory-md parse inventory.md

# Auto-detect files and use config
inventory-md parse --auto

# Look up a concept by label (shows its broader/hierarchy)
inventory-md vocabulary lookup potato

# --lang sets the language for the tingbok query (matters for non-English terms)
inventory-md vocabulary lookup potet --lang nb

# Show category tree
inventory-md vocabulary tree
```

## Implementation Details

### Files

| File | Purpose |
|------|---------|
| `src/inventory_md/vocabulary.py` | Category tree building, path normalization, multi-location loading, tingbok lookups |
| `src/inventory_md/parser.py` | Parse `category:` syntax from markdown |
| `src/inventory_md/cli.py` | CLI commands for parse, vocabulary, etc. |
| `src/inventory_md/config.py` | Configuration (`tingbok.url`, `lang`, ...) |
| `src/inventory_md/data/vocabulary.yaml` | Package default vocabulary (shipped) |
| `~/.config/inventory-md/vocabulary.yaml` | User vocabulary overrides |
| `./vocabulary.yaml` or `./local-vocabulary.yaml` | Instance-specific vocabulary |

### Generated Files

| File | Purpose |
|------|---------|
| `inventory.json` | Parsed inventory with categories in metadata |
| `vocabulary.json` | Category tree for search.html UI |

### Data Sources

External taxonomy sources are no longer queried directly by inventory-md. The
[tingbok](https://tingbok.plann.no) service is the single authority for resolving a
category label to a concept and for enriching it from the public SKOS sources it
aggregates — currently **Open Food Facts**, **AGROVOC**, **DBpedia** and **Wikidata**.
inventory-md sends labels (with the inventory's `lang`) to tingbok and caches the
results in the generated `vocabulary.json`. See the tingbok project for how each
source is queried, merged and filtered.

inventory-md still owns the **local/global vocabulary** layer:

- **Global Vocabulary** - Merged from multiple locations
  - Package default + system + user + instance-specific
  - Takes precedence over tingbok-resolved concepts
  - Maps orphan categories to proper parents

### Priority Logic

When resolving a category label:

1. **Local/global vocabulary** - If the label matches a local concept (by ID,
   path alias or altLabel), it wins — letting users override anything from tingbok.
2. **Tingbok** - Otherwise the label is resolved via the tingbok service (which
   merges OFF/AGROVOC/DBpedia/Wikidata and applies its own language fallbacks).
3. **Raw string** - If nothing resolves, the raw category string is kept as-is.

## Global Vocabulary

The vocabulary is loaded from multiple locations, merged with precedence:

1. **Package default** (`inventory_md/data/vocabulary.yaml`) - shipped with inventory-md
2. **System config** (`/etc/inventory-md/vocabulary.yaml`) - for system-wide customization
3. **User config** (`~/.config/inventory-md/vocabulary.yaml`) - for user preferences
4. **Instance-specific** (`./vocabulary.yaml` or `./local-vocabulary.yaml`) - for this inventory

Each file provides:
- Custom category definitions with prefLabel, altLabel, broader, narrower
- Mappings from orphan categories to parent categories (reducing root nodes)
- Override for external sources (OFF, AGROVOC, DBpedia)

Example:
```yaml
concepts:
  food:
    prefLabel: "Food"
    altLabel: ["groceries", "provisions"]
    narrower:
      - food/beverages
      - food/dairy
      - food/grains

  american_fashion:
    prefLabel: "American fashion"
    broader: clothing/fashion

  instant-foods:
    prefLabel: "Instant foods"
    broader: food/preserved
```

Local vocabulary entries take precedence over external source lookups.

## Testing

```bash
# Run vocabulary tests
pytest tests/test_vocabulary.py -v

# Resolve some labels via tingbok
inventory-md vocabulary lookup potato
inventory-md vocabulary lookup potet --lang nb

# Full parse (enriches categories via tingbok when tingbok.url is configured)
inventory-md parse inventory.md

# View generated vocabulary
cat vocabulary.json | jq '.roots'
```

## Known Issues

1. **AGROVOC agricultural bias** - Terms like "bedding" return "litter for animals" instead of household bedding. Mitigated by preferring DBpedia for non-food terms.

2. **DBpedia lacks Norwegian** - Only AGROVOC has Norwegian labels. DBpedia concepts show English only.

3. **Lookup latency** - The first tingbok lookup for an unknown label hits upstream SKOS sources and can be slow; results are cached (locally in `vocabulary.json` and server-side in tingbok), so subsequent lookups are fast.

4. **Path explosion** - AGROVOC can return many paths for one concept. Currently limited to first path found.
