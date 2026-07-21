## Shopping pipeline — streamlining (from staging/notes 2026-06-13)

* ~~**`inventory-md` command to add an item line to a section.**~~ DONE 2026-06-14:
  `inventory-md add CONTAINER --category … [--id … --ean … --bb … …] NAME`
  appends a validated line under a container `ID:`, folding the QA work (dup-ID,
  food-bb, category resolution) into the write step; `--id` auto-generates a
  readable id (category leaf + date for food). `scripts/inventory_import.py`
  applies it across a whole reviewed staging file in one pass (import
  `inventory_md.additem`, no CLI shell-out), so process-shopping Stage 3 no
  longer hand-edits `inventory.md`. See `docs/ADDING-ITEMS.md`.
* ~~**`inventory-md` command to change a field on an existing item line.**~~ DONE
  2026-07-22: `inventory-md edit ITEM_ID [--ean … --bb …[:EST] --est/--no-est
  --mass … --qty … --price … --category … --name … --tag …]` rewrites one
  unambiguous `ID:` bullet in place (field order and sub-bullets preserved, empty
  value removes a field), with the same QA as `add` plus `--dry-run`. Together
  with `add` and `move` this removes the last reason to hand-edit the markdown.
* **Make manual photo inspection unnecessary in the shopping flow.** Goal: the
  agent never opens a product photo. `extract_barcodes.py`/`shop_import.py` should
  reliably (a) decode every barcode and (b) extract each best-before and attach it
  to the right item by pairing a barcode photo with the expiry in *that* photo or
  the *immediately following* photo. Today expiry OCR is hit-or-miss and the
  agent falls back to reading photos. Improve OCR robustness (orientation, dotted
  printer fonts, curved/foil surfaces) and the photo→item association so the
  staging file arrives with `ean` + `bb` already populated; only unresolved items
  get flagged for the user.

## Old stuff

This needs to be cleaned up and organized, it's a mess

* ~~Consider TODO-CATEGORIES.md - is there any tasks there that hasn't been processed?  Delete everything that is completed.~~ DONE 2026-05-26
* ~~I'd like to be able to search for, look up, and browse categories and the category hiearchies from the CLI~~ DONE 2026-05-26: `vocabulary list/lookup/tree/search` all work offline from vocabulary.json; `lookup` falls back to tingbok for unknown categories.  `vocabulary search` now shows container location next to each item.
* Getting the categories correct is quite high.  See TODO-CATEGORIES.md.
* ~~I'd like a Makefile in the inventory repository for parsing the inventory, refreshing search.html if needed, and refreshing the Makefile as well if needed~~ DONE 2026-05-27: `inventory-md init` installs a Makefile; `inventory-md update-makefile` refreshes it.  `make` parses when inputs change, refreshes search.html and Makefile if package was updated.
* System is currently used for "Solveig" (boat) and "Furuset" (home).  I don't want to go public with the database here, but it would be nice with a third demo site with demo data.  (Partly DONE - but it should be improved to "show off" all the features)
* There are some things now that should be included in the inventory-md:
  * ~~at Solveig we have a shopping list generator script~~ DONE: integrated as `inventory-md parse --wanted-items`
  * ~~Skills files~~ DONE 2026-05-27: `claude-skills/` contains process-inventory-photos.md, process-shopping.md, suggest-recipe.md
  * The integration with the Lidl+ shopping history downloader should also be scripted better and included in the inventory system.
  * ~~Make a public puppet-module for rolling out things, too~~ DONE: https://github.com/tobixen/puppet-inventory-md
* QR label printing: Generate printable QR code labels with unique IDs for containers and items (this feature is available in the CLI now, but needs testing with physical labels)
  - Pre-print sheets of labels (like Avery 5260) with sequential IDs
  - QR codes should link to the web UI (e.g., https://inventory.example.com/item/ID)
  - Consider support for dedicated label printers (Brother QL-700, Dymo)
  - See how Homebox does it: https://hay-kot.github.io/homebox/tips-tricks/
  - Some thoughts: IDs consisting of two letters and one digit.  First letter differs for different variants of the labels - I will need some very small labels with only QR-code for smaller items, bigger labels with QR-code and visible ID-text and possibly print date for bigger items (and possibly two stickers for each big item), similar labels but like 6 copies of each for labelling containers from all sides.  The second letter and digit should increase incrementally.
* I'd like the inventory git repo to include the filenames of all the photos (backup of the photos are done separately, but we need the file listings to roll out the photos to the correct places) - done?
* Immich integration?
* Consider age ranges for children's items (e.g., age:6-8)
* ~~**SKOS Category System**~~ This one has grown very complex, and despite the task list being completed it did not end up as I had intended it to be.  Work continued in separate file.
  - [x] Parser support for `category:` syntax
  - [x] SKOS module with AGROVOC/DBpedia integration
  - [x] Oxigraph local database for fast queries
  - [x] CLI commands: `skos expand/lookup`, `vocabulary list/lookup/tree`
  - [x] Plural normalization (books→book)
  - [x] DBpedia priority for non-food terms
  - [x] SKOS hierarchy mode in `parse --auto` and `parse --hierarchy`
  - [x] Category mappings stored in vocabulary.json
  - [x] search.html category browser UI (tree with expand/collapse)
  - [x] Conditional category UI (hidden when vocabulary.json missing/empty)
  - [x] SKOS path expansion in UI (badges and filters use expanded paths)
  - [x] Global vocabulary shipped with package, multi-location loading with merge precedence
  - [x] Language fallback chains for translations (Scandinavian, Germanic, Romance, Slavic)
