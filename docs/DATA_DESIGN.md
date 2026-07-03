# Data design

## Hierarchical location design

The location of objects is organized as a strict hierarchy.  Taken to the extreme, one may have 32 chess pieces as "items", the chess game may be a "container", this game may be in a box containing multiple games, this box may be on a shelf, the shelf may be in a bookshelf, the bookshelf may be in a room, the room in a house, the house at an address, the address in a city, the city on an island ... all of those may be considered to be "containers". In practice I would recommend to stop with the "room" being the top level container, and "chess game" being the leaf node (item).

The system supports both nested lists and headers with subheaders, subsubheaders, etc.  However, it gets really ugly (and difficult to edit) when the hierarchy becomes deep, so my recommendation is to flatten the document.  A storage full of containers may just list up what containers is found in what location in the storage, and then a different top section may be used for listing up the content of each container.

## Tagging and classification

The original design suggested by Claude was to have a "type" field for each item.  Often such "types" are organized strictly hierarchically, like domestic/kitchen-applicance/electric/food-processor/batch-bowl/KitchenAid/9

It sometimes makes sense - a "food processor" is certainly a kitchen applicance, there are different kinds of food processors and then there are different models - but consider "electric".   What is the parent and what is the child?  Should it be `electric/kitchen` or should it be `kitchen/electric`?  One may say that "electric" and "kitchen" are two different "dimensions".  So rather than hierarchical classification, we're doing hierarchical tagging, and a product may have multiple tags.  One tag may be `electric/AC`, the other tag may be `kitchen/food-processor`.

The tagging system is by now also used for the shopping list generation.  I do care that I always have potatoes available, but I don't care what kind of potatoes - so the matching is by tag.  The potatoes in the storage may be tagged as `food/vegetable/potatoes/asterix`. if the list of wanted storage state lists `food/vegetable/potatoes` then that's sufficient.  It's not so the other way around, if the "wanted storage state" says that I should have potatoes of the type "Asterix" then it should appear on the shopping list even if we already have a ton of other potatoes in storage.

The complexity never ends.  With the multi-tag philosophy the potatoes should be tagged both `food/vegetables` and `food/staples`, that's trivial, but what if I want to include `potatoes/asterix` in the tag?  Should it be `food/potatoes/asterix`, `potatoes/asterix`, `food/vegetable/potatoes/asterix` or `food/staples/potatoes/asterix`?  This is a multiple-path problem, both pathes to the Asterix potato is correct.

I think the solution is like this:

1) A search for either food/vegetables/potatoes or food/staple/potatoes in the tag selector should match all potatoes.
2) To reduce the noise level in the markdown file, this information should be stored in a different file.  It should hence suffice to tag the potatoes with `tag:potatoes/asterix` and the parser script will expand this to `food/vegetables/potatoes/asterix,food/staples/potatoes/asterix`.

TODO: formalize this and make the scripts support it.

As for now the implementation is wide open, every instance may have a completely independent set of tags.  However, it would make sense to have some good standards on the tagging.  TODO, think more about this.  Research should be done to see what kind of standards there is on this.  The openfoodfacts does have a category list.


## Other data fields

It's important not to pollute the namespace too much.  Always consider if the tagging system should be used instead of adding a new data field.  For instance, if one wants to add `quality:bad`, then consider if it's a better idea to add `tag:quality/bad`

TODO: we need to formalize a nice way to add data to a list of items - like having the timestamps included in a header

This is an open-ended system, so any data can be added to the inventory lines.  Anything on the format `foo:bar` is considered to be metadata.  However, some common guidelines should exist, and some things are already used in scripts (like the shopping list generator):

### Best before: bb:1998-05-04

Food typically have a "best before"-date.  I think this is regulated in the EU - even things that lasts "forever" comes stamped with a "best before"-date nowadays.  The concept is not limited to food - gold and diamonds are probably almost the only things that truly last "forever".

The "best before" can be printed, or it may be estimated, like one may assume that fresh vegetables from the shop lasts for five days.  Currently estimated dates should have the ":EST" suffix.  (This may be reconsidered - after all, the printed dates are also just estimates, the real expiry date is only known after the food/product is spoiled).

In reality the real expiry date is very much dependent on storage conditions - and the whole concept is kind of weird, quite many of the items does not expire binary, it just loses consistency or flavor over time.

There is a script to list out (food) items sorted/filtered by the best before date to aid one in deciding what things should be eaten first (or possibly thrown).

### Quantity, mass, volume

Those are used by the shopping list generator to see if the stocks are sufficient or if it's needed to restock.

This may be a bit tricky.  `mass:500g qty:3` should be read as "three packages, totally 1.5 kg", it makes perfect sense when stocking a pile of 500g-packages of oats from the shop.  It's more difficult when it comes to fruits and vegetables, one would typically buy a bag of ten tomatoes, totally one kilogram.  It's OK when adding new vegetables - the shopping receipt will tell that I bought 1kg of tomatoes - but it gets difficult when I spent 6 tomatoes and have 3 left.  How many grams are left?  So the way to handle this is to do `mass:1.36kg/9 qty:9` to indicate that we have nine tomatoes weighting approximately 151 grams each, or 9 tomates weighting exactly 1.36 kg.  When spending tomatoes it's just to adjust, `mass:1.36kg/9 qty:3`.  Adding more tomatoes, and it may be done at a separate line (and stacked up so that the old tomatoes will be spent before the new ones).

If different items of the same type have different expiry date, then it should be split up into two inventory lines.

### Price and value

Those variables are not used anywhere yet, but the idea is to be able i.e. to calculate costs for a dinner or for a repair job that involves consumables.

The price is what was paid in the shop, the value is the estimated "current" value of the thing.

A single value is OK for unique single products, but for food products a qualifier should be added.

Examples:

* `price:EUR:15`
* `price:NOK:55/piece`
* `value:EUR:5.6/kg`

Now what with packs of packs, or packs with an exact count?  Like a 12-pack of eggs?  Perhaps it may be done like this (but may not be supported by all the scripts as of today):
1
* Carton of 12 eggs qty:2 EAN:xxx price:EUR:2.5/piece
  * eggs qty:24

### Timestamps: verification, added, updated

Those are neither used yet, nor formally included in any of my data sets yet.  As for now the verification timestamp  and added timestamps are often in freetext in the document.  It should be formalized.

**Verification**: For any inventory line, it means the item has been observed, has the right parent container set, and all attributes seems to be correct.  If a value is given, then it may be needed to reestimate the value.  For a container, all the items in the container should be present (but it's not needed to verify all the attributes of all the children, nor to verify the presence of all the grandchildren).

**Added**: Timestamp some item is added - like, physically added.  If the item is observed and added to the list, then the verification timestamp should rather be updated.

**Updated**: Timestamp when some attributes were updated.  Particularly useful if items are consumed.  Consumed or discarded items may either be deleted or one may mark it up by setting i.e. `qty:0`.  The latter indicates that this is the correct position for the item, and whenever we buy a new such item we should try to find space for it in the same spot.

### EAN - European Article Number

Most articles sold in regular shops in the EU comes with barcodes - typically used for registering the sale and presenting the customer with a price in the cash register, but also useful for identifying and classifying items.

There is a script to find barcodes in photos and look up the EAN from a database.  The EAN can also be used for adding things at the correct place in the inventory when resupplying.

**Shop-local codes are namespaced.** Many shops sell items with a shop-local identifier and no global barcode. The `EAN:` field also holds these, prefixed with the (lowercase) shop name as `EAN:<shop>-<code>`. Two common patterns, both applying to *any* shop (the shops named are only examples): shop catalogue/article numbers (e.g. Biltema `Art. 46-3491` → `EAN:biltema-463491`) and in-store barcodes in the GS1 restricted range (first digit `2`, e.g. a Lidl weighed-goods code `20241988` → `EAN:lidl-20241988`). Such codes are not globally unique — different chains reuse the same number — so the shop prefix disambiguates. A real GTIN never contains a hyphen, so a hyphenated value is by definition a shop-prefixed local code (this is also how tingbok keys them). `check_quality.py` flags any un-prefixed shop-local code.

### ID - internal ID field

Use internally for tracking purposes.  It may be almost anything - in my Solveig and Furuset instances they are often descriptive, and quite often I label boxes using a similar ID.

Some experiences:

* Incremental numbers is an easy way - but the numbers may become quite long after a while, and they may be hard to remember.
* Combinations of letters and numbers is often more compact and often easier to remember than just numbers.  For boxes I tend to use series like A-01, A-02, A-03, B-01 etc, with the letter (or combination of lettes) giving some hints on either what kind of box it is, where to find it, or what it contains.  The dash reduces ambigiouosity a bit (A03 or AO3?), avoid one-digit numbering (searching for "A-3" in the markdown, and one will find A-31, A-32, A-33, etc)

### QR - alternative ID field

Not used yet.

I'm considering to print out stacks of QR-codes with somehow sequential letter-number combinations and apply to items and containers, including items and containers that already have existing IDs.  Slapping on a QR-code and the item/container has basically gotten a new ID.  However it may be a wish to keep the old ID, particularly if the box is already labelled "A-01" on all sides.  The QR-tag will then indicate that the box has a different QR-code than the ID.

To avoid too much noise in the markdown file, the QR code should not be applied if the QR equals the ID.

### Parent - alternative way of specifying child/parent location relationship

There are now four ways to indicate a parent/child relationship:

* Nested lists
* Subsections
* Lists of containers with IDs - and then listing the contents of the container somewhere else in the document
* Adding `parent:id-of-parent-container`.  This should maybe be reconsidered, I don't think it should be needed, and it adds noise to the file IMHO.  (Unless we want to allow an item to have multiple parents?  What to do if an item is temporarily moved from one container to another?)

### Photo directory

The tag `photos:E-12` indicates that there exists photos in a folder E-12.

I think that this can probably go away.  It's already so that the parse script will check that the folder E-12 is present if the container has the ID E-12.  The feature was needed earlier, when we had data inconsistencies.  I think most of those have been cleaned up now.

We also have a separate file photo-registry.md linking photo filenames with inventory items.  This is not formalized yet, it's only present in the Solveig inventory, but it could be possible to utilize the data in the web UI.

## Files and directories

### Raw data

* Photo directories: contains photos.  Not included in the git repo, files needs to be synchronized i.e. with rsync.  In the solveig data directory there is a script for syncing photos.  TODO: think more about this and move it to the inventory-md itself.  TODO: we need some kind of retention of obsoleted photos

### Git-controlled data
* inventory.md - the authorative database file
* Photo registry - not a formal part of the system yet.
* `aliases.json` - search aliases, may be generated by Claude or manually
* `ean_cache.json` - whenever we do lookups of external databases, the result is stored here.  Generated and used by the bar code scanning script.  Also stores data on what's in the receipts from LIDL.bg.  (this needs to be a list or a dict rather than a single value, as I will be shopping also on other lidls)
* recipes/ - not a formal part of the system yet.
* scripts/ - per-instance-local scripts.  Should be formalized and moved to the inventory-md itself.  For Solveig there are scripts for handling data from https://www.lidl.bg

### Generated

* Thumbnail directories: contains thumbnails (TODO: rename - the directory is named `resized` today, it's not very descriptive).  Auto-generated by the script.
* Shopping-list.md - generated shopping list
* inventory.json - data extracted from inventory.md
