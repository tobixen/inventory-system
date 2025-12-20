# Inventory System

A flexible markdown-based inventory management system with web UI.

Disclaimer: This is "vibe coded", more or less.  I will ensure it works well for two actual inventories, then make a demo and release it.

## Features

- **Markdown-based**: Edit your inventory in plain text markdown files
- **Hierarchical organization**: Support for parent-child relationships between containers
- **Metadata tags**: Add searchable tags to items
- **Image support**: Include photos with automatic thumbnail generation
- **Web interface**: Searchable, filterable web UI with lightbox image viewer
- **Multi-tag filtering**: Filter by multiple tags with AND logic
- **Alias search**: Define search aliases for better discoverability
- **Gallery view**: Browse all images across containers

## Installation

```bash
# Install in development mode
cd inventory-system
pip install -e .
```

## Quick Start

```bash
# Initialize a new inventory
inventory-system init ~/my-inventory --name "Home Storage"

# Edit the inventory.md file
cd ~/my-inventory
editor inventory.md

# Parse and generate JSON
inventory-system parse inventory.md

# Start local web server
inventory-system serve
```

Then open http://localhost:8000/search.html in your browser.

## Markdown Format

### Basic Structure

```markdown
# Intro

Description of your inventory...

## About

More information...

# Nummereringsregime

Explanation of your numbering/naming scheme...

# Oversikt

## ID:Box1 (parent:Garage) Storage Box 1

Items in this box:

* tag:tools,workshop Screwdriver set
* tag:tools Hammer
* ID:SubBox1 Small parts container

![Thumbnail description](resized/box1.jpg)

[Fotos i full oppløsning](photos/box1/)
```

### Metadata Syntax

Items and containers can have metadata:

- `ID:unique-id` - Unique identifier
- `parent:parent-id` - Parent container reference
- `tag:tag1,tag2,tag3` - Comma-separated tags
- `type:category` - Item type/category

Metadata can be placed anywhere in the line:
- `ID:A1 My Container`
- `My Container ID:A1`
- `ID:A1 (parent:Garage) My Container`

## CLI Commands

### `init` - Initialize a new inventory

```bash
inventory-system init <directory> [--name <name>]
```

Creates a new inventory with template files.

### `parse` - Parse inventory markdown

```bash
inventory-system parse <file.md> [--output <output.json>] [--validate]
```

Parses the markdown file and generates JSON. Use `--validate` to check for errors without generating output.

### `serve` - Start web server

```bash
inventory-system serve [directory] [--port <port>]
```

Starts a local web server to view the inventory. Default port is 8000.

## License

MIT
