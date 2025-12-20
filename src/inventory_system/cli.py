#!/usr/bin/env python3
"""
Command-line interface for Inventory System
"""
import sys
import argparse
import shutil
from pathlib import Path
from . import parser


def init_inventory(directory: Path, name: str = "My Inventory") -> int:
    """Initialize a new inventory in the specified directory."""
    directory = Path(directory).resolve()

    if not directory.exists():
        directory.mkdir(parents=True)
        print(f"✅ Created directory: {directory}")
    elif any(directory.iterdir()):
        print(f"⚠️  Directory {directory} is not empty")
        response = input("Continue anyway? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            return 1

    # Copy template files
    templates_dir = Path(__file__).parent / 'templates'

    # Copy search.html
    search_html = templates_dir / 'search.html'
    if search_html.exists():
        shutil.copy(search_html, directory / 'search.html')
        print(f"✅ Created search.html")

    # Copy aliases.json template (if it exists)
    aliases_template = templates_dir / 'aliases.json.template'
    if aliases_template.exists():
        shutil.copy(aliases_template, directory / 'aliases.json')
        print(f"✅ Created aliases.json")

    # Create inventory.md from template or create basic one
    inventory_md = directory / 'inventory.md'
    if not inventory_md.exists():
        inventory_template = templates_dir / 'inventory.md.template'
        if inventory_template.exists():
            shutil.copy(inventory_template, inventory_md)
        else:
            # Create basic inventory.md
            with open(inventory_md, 'w', encoding='utf-8') as f:
                f.write(f"""# Intro

{name}

## Om inventarlisten

Dette er en søkbar inventarliste basert på markdown.

# Nummereringsregime

Bokser/containere kan navngis etter eget ønske. Eksempler:
* Box1, Box2, ... (numerisk)
* A1, A2, B1, B2, ... (alfabetisk)
* Garasje, Loft, Kjeller (stedsnavn)

# Oversikt

## ID:Eksempel1 (parent:RootLocation) Eksempel container

Beskrivelse av container...

* tag:eksempel,demo Dette er et eksempel på en item
* tag:demo Et annet item

![Beskrivelse](resized/bilde.jpg)

[Fotos i full oppløsning](photos/)
""")
        print(f"✅ Created inventory.md")

    # Create directories for images
    (directory / 'photos').mkdir(exist_ok=True)
    (directory / 'resized').mkdir(exist_ok=True)
    print(f"✅ Created image directories (photos/, resized/)")

    print(f"\n🎉 Inventory initialized in {directory}")
    print(f"\nNext steps:")
    print(f"1. Edit {directory / 'inventory.md'} to add your items")
    print(f"2. Run: inventory-system parse {directory / 'inventory.md'}")
    print(f"3. Open {directory / 'search.html'} in your browser")

    return 0


def parse_command(md_file: Path, output: Path = None, validate_only: bool = False) -> int:
    """Parse inventory markdown file and generate JSON."""
    md_file = Path(md_file).resolve()

    if not md_file.exists():
        print(f"❌ Error: {md_file} not found!")
        return 1

    if output is None:
        output = md_file.parent / 'inventory.json'

    try:
        # Add ID: prefixes to container headers if not validating
        if not validate_only:
            print(f"🔍 Checking for duplicate container IDs...")
            changes, duplicates = parser.add_container_id_prefixes(md_file)

            if duplicates:
                print(f"⚠️  Found duplicate container IDs:")
                for orig_id, new_ids in duplicates.items():
                    print(f"   {orig_id} → {', '.join(new_ids)}")

            if changes > 0:
                print(f"✏️  Added ID: prefix to {changes} container headers")
            else:
                print(f"✅ All container headers already have ID: prefix")

        print(f"\n🔄 Parsing {md_file}...")
        data = parser.parse_inventory(md_file)

        print(f"✅ Found {len(data['containers'])} containers")

        # Count total images and items
        total_images = sum(len(container['images']) for container in data['containers'])
        total_items = sum(len(container['items']) for container in data['containers'])
        items_with_id = sum(1 for container in data['containers'] for item in container['items'] if item.get('id'))
        items_with_parent = sum(1 for container in data['containers'] for item in container['items'] if item.get('parent'))

        print(f"✅ Found {total_images} images and {total_items} items")
        print(f"   - {items_with_id} items with explicit IDs")
        print(f"   - {items_with_parent} items with parent references")

        # Validate and print issues
        print(f"\n🔍 Validating inventory...")
        issues = parser.validate_inventory(data)

        if issues:
            print(f"\n⚠️  Found {len(issues)} issue(s):")
            for issue in issues[:20]:  # Limit to first 20
                print(f"   {issue}")
            if len(issues) > 20:
                print(f"   ... and {len(issues) - 20} more")
        else:
            print(f"✅ No validation issues found!")

        # Save to JSON if not validating
        if not validate_only:
            parser.save_json(data, output)
            print(f"\n✅ Success! {output} has been updated.")

            # Generate photo directory listings for backup
            print(f"\n📸 Generating photo directory listings...")
            containers_processed, files_created = parser.generate_photo_listings(md_file.parent)
            if files_created > 0:
                print(f"✅ Created {files_created} photo listing(s) in photo-listings/")
            else:
                print(f"   No photos found (photo-listings/ not updated)")

            search_html = md_file.parent / 'search.html'
            print(f"\n📱 To view the searchable inventory, open search.html in your browser:")
            print(f"   xdg-open {search_html}")

        return 0

    except Exception as e:
        import traceback
        print(f"\n❌ Error parsing inventory: {e}")
        traceback.print_exc()
        return 1


def serve_command(directory: Path = None, port: int = 8000) -> int:
    """Start a local web server to view the inventory."""
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory).resolve()

    if not directory.exists():
        print(f"❌ Directory {directory} does not exist")
        return 1

    search_html = directory / 'search.html'
    if not search_html.exists():
        print(f"❌ search.html not found in {directory}")
        print(f"Run 'inventory-system init {directory}' first")
        return 1

    print(f"🌐 Starting web server at http://localhost:{port}")
    print(f"📂 Serving directory: {directory}")
    print(f"Press Ctrl+C to stop\n")

    import http.server
    import socketserver
    import os

    os.chdir(directory)

    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n👋 Server stopped")
            return 0


def api_command(directory: Path = None, port: int = 8765) -> int:
    """Start the inventory API server (chat, photo upload, item management)."""
    import os

    # Check for API key (optional - chat feature will be disabled if not set)
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_api_key:
        print("ℹ️  ANTHROPIC_API_KEY not set - chat feature will be disabled")
        print("   Photo upload and item management will still work")
        print("\n   To enable chat, get an API key from: https://console.anthropic.com/")
        print("   Then set it: export ANTHROPIC_API_KEY='your-key-here'\n")

    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory).resolve()

    if not directory.exists():
        print(f"❌ Directory {directory} does not exist")
        return 1

    inventory_json = directory / 'inventory.json'
    if not inventory_json.exists():
        print(f"❌ inventory.json not found in {directory}")
        print(f"Run 'inventory-system parse inventory.md' first")
        return 1

    # Change to directory so API server can find inventory.json
    os.chdir(directory)

    print(f"🚀 Starting Inventory API Server...")
    print(f"📂 Using inventory: {inventory_json}")
    print(f"🌐 Server will run at: http://localhost:{port}")
    print(f"💬 Chat endpoint: http://localhost:{port}/chat")
    print(f"📸 Photo upload: http://localhost:{port}/api/photos")
    print(f"➕ Add/remove items: http://localhost:{port}/api/items")
    print(f"❤️  Health check: http://localhost:{port}/health")
    print(f"\nOpen search.html in your browser to use the interface")
    print(f"Press Ctrl+C to stop\n")

    # Import and run the API server
    try:
        import uvicorn
        from .chat_server import app
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("\nInstall API server dependencies:")
        print("  pip install fastapi uvicorn anthropic python-multipart")
        return 1

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\n\n👋 Chat server stopped")
        return 0


def main() -> int:
    """Main entry point for the CLI."""
    parser_cli = argparse.ArgumentParser(
        description="Inventory System - Manage markdown-based inventories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize a new inventory
  inventory-system init ~/my-inventory --name "Home Storage"

  # Parse inventory and generate JSON
  inventory-system parse ~/my-inventory/inventory.md

  # Validate inventory without generating JSON
  inventory-system parse ~/my-inventory/inventory.md --validate

  # Start a local web server
  inventory-system serve ~/my-inventory

  # Start API server for chat, photos, and item management (requires ANTHROPIC_API_KEY)
  inventory-system api ~/my-inventory
        """
    )

    subparsers = parser_cli.add_subparsers(dest='command', help='Command to run')

    # Init command
    init_parser = subparsers.add_parser('init', help='Initialize a new inventory')
    init_parser.add_argument('directory', type=Path, help='Directory to initialize')
    init_parser.add_argument('--name', type=str, default='My Inventory', help='Name of the inventory')

    # Parse command
    parse_parser = subparsers.add_parser('parse', help='Parse inventory markdown file')
    parse_parser.add_argument('file', type=Path, help='Inventory markdown file to parse')
    parse_parser.add_argument('--output', '-o', type=Path, help='Output JSON file (default: inventory.json)')
    parse_parser.add_argument('--validate', action='store_true', help='Validate only, do not generate JSON')

    # Serve command
    serve_parser = subparsers.add_parser('serve', help='Start local web server')
    serve_parser.add_argument('directory', type=Path, nargs='?', help='Directory to serve (default: current directory)')
    serve_parser.add_argument('--port', '-p', type=int, default=8000, help='Port number (default: 8000)')

    # API command
    api_parser = subparsers.add_parser('api', help='Start API server (chat, photos, item management)')
    api_parser.add_argument('directory', type=Path, nargs='?', help='Directory with inventory.json (default: current directory)')
    api_parser.add_argument('--port', '-p', type=int, default=8765, help='Port number (default: 8765)')

    # Chat command (backwards compatibility alias for 'api')
    chat_parser = subparsers.add_parser('chat', help='[Deprecated] Use "api" instead')
    chat_parser.add_argument('directory', type=Path, nargs='?', help='Directory with inventory.json (default: current directory)')
    chat_parser.add_argument('--port', '-p', type=int, default=8765, help='Port number (default: 8765)')

    args = parser_cli.parse_args()

    if args.command == 'init':
        return init_inventory(args.directory, args.name)
    elif args.command == 'parse':
        return parse_command(args.file, args.output, args.validate)
    elif args.command == 'serve':
        return serve_command(args.directory, args.port)
    elif args.command == 'api' or args.command == 'chat':
        return api_command(args.directory, args.port)
    else:
        parser_cli.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
