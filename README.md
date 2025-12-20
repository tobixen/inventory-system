# Inventory System - Natural Stupidity notes

This is a flexible "vibe-coded" Markdown-based inventory management system with web UI and Claude-backed AI chat-bot.  My "roadmap" is to ensure it works well for two actual inventories, then make a demo and release a v1.0.

## Background and thoughts

The database is in Markdown format, because that's what I started with.  I didn't have any inventory system, I just wrote lists in my editor, eventually adding markdown headers, and using regular search to find things in it.  And then I (with a lot of help from the AI) code up a parser to convert the database to json.  And while doing so, we added tags and IDs and whatnot ... and I allowed the AI to edit the markdown file, and even allowed the markdown file to be edited through the Web-UI.

The advantage of the MD-format is that it's human-readable.  The end-result, after all those machine-edits is that it's not much human readable anymore.  So probably it would be an idea to scrap the markdown file and let the JSON-file be the "single source of truth".  I guess a lot of complexity would be removed by scrapping the markdown.

When I asked the AI how I could improve on my Markdown-based system, it suggested to have it all done through javascript in the browser.  That was a very lazy start, just push out the files to my web server and it was already working without any configuration or server management.  But most likely my family members would not bother to amend the database when moving things around - so I needed a web interface for that.  Considering that I asked Claude to edit the Markdown rather than editing it myself, my first idea was to add a Chatbot for doing this - so that's the rationale behind the chatbot extension.

The AI chatbot extension does not do a fraction of the work I had hoped it could do.  I've had Claude help me going through the inventory, adding tags, aliases and doing lots of other "hard lifting".  It even ensured that a search for "voltmeter" would find my multimeters, or that a search for "saw" would find all instances of "Sag" in my Norwegian inventory.  The chatbot failed on such simple tasks.  Now the chatbot has been made aware of the aliases.json file ... but this file is AI-generated, I think an AI chatbot automatically should consider all possible aliases for the search term rather than looking up in a pre-generated aliases.json file.

Considering that I want to use the system on my boat, which sometimes is completely offline, a chatbot communicating with some "cloud AI" wouldn't work out, and I'm not going to install GPUs and more solar panels locally just to power this stupid chatbot.  So it's back to the drawing board ... and the chatbot will maybe disappear completely, or be an opt-in/opt-out feature.

# Inventory System - Artificial Intelligence documentation

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
