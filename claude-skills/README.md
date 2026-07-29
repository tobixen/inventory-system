# Claude Skills for inventory-md

These skill files describe workflows for using an AI assistant to maintain an inventory managed by this system. They are generic — they use `$INVENTORY_DIR` and `$PHOTO_DIR` as placeholders for your actual paths.

Create personal skill files under `~/.claude/skills/` that reference these guides and add your instance-specific paths, tools, and conventions. See the [INSTALLATION guide](../docs/INSTALLATION.md) for setup instructions.

## Available skills

| File | Purpose |
|------|---------|
| `process-inventory-photos.md` | Process photos of containers/locations and update the inventory |
| `suggest-recipe.md` | Suggest recipes prioritising soon-to-expire inventory items |

`process-shopping.md` used to live here. It moved to
[purchase-pipeline](https://github.com/tobixen/purchase-pipeline), at
`claude-skills/process-shopping.md`: turning a receipt into a ledger, inventory
entries and published prices is that project's workflow, and all but three of
its commands are that project's. What an inventory *item* looks like once
written stays here — see `docs/ADDING-ITEMS.md` below.

## Item format reference

For categories, tags, quantities, best-before dates, and other field conventions, see [`docs/ADDING-ITEMS.md`](../docs/ADDING-ITEMS.md).

For general maintenance tasks, see [`docs/MAINTENANCE.md`](../docs/MAINTENANCE.md).
