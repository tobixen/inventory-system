#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
Command-line interface for Inventory System
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import argcomplete

from . import additem, barcodes, edititem, moveitem, parser, queries, shopping_list, vocabulary
from ._version import __version__
from .config import Config, load_config


def _parse_inventory_price(price_str: str | None, shop: str | None = None) -> dict | None:
    """Parse an inventory ``price:`` tag value into a PriceObservation dict.

    Handles format ``CURRENCY:VALUE/UNIT`` (e.g. ``EUR:0.78/piece``).
    Returns ``None`` if the string cannot be parsed.
    """
    if not price_str:
        return None
    try:
        currency, rest = price_str.split(":", 1)
        if "/" in rest:
            value_str, unit = rest.rsplit("/", 1)
        else:
            value_str, unit = rest, "pcs"
        return {
            "currency": currency.upper(),
            "price": float(value_str),
            "unit": unit,
            "shop": shop or None,
        }
    except (ValueError, AttributeError):
        return None


def init_inventory(directory: Path, name: str = "My Inventory") -> int:
    """Initialize a new inventory in the specified directory."""
    directory = Path(directory).resolve()

    if not directory.exists():
        directory.mkdir(parents=True)
        print(f"✅ Created directory: {directory}")
    elif any(directory.iterdir()):
        print(f"⚠️  Directory {directory} is not empty")
        response = input("Continue anyway? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

    # Copy template files
    templates_dir = Path(__file__).parent / "templates"

    # Copy search.html
    search_html = templates_dir / "search.html"
    if search_html.exists():
        shutil.copy(search_html, directory / "search.html")
        print("✅ Created search.html")

    # Copy Makefile template
    makefile_template = templates_dir / "Makefile"
    if makefile_template.exists():
        shutil.copy(makefile_template, directory / "Makefile")
        print("✅ Created Makefile")

    # Copy aliases.json template (if it exists)
    aliases_template = templates_dir / "aliases.json.template"
    if aliases_template.exists():
        shutil.copy(aliases_template, directory / "aliases.json")
        print("✅ Created aliases.json")

    # Create inventory.md from template or create basic one
    inventory_md = directory / "inventory.md"
    if not inventory_md.exists():
        inventory_template = templates_dir / "inventory.md.template"
        if inventory_template.exists():
            shutil.copy(inventory_template, inventory_md)
        else:
            # Create basic inventory.md
            with open(inventory_md, "w", encoding="utf-8") as f:
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
        print("✅ Created inventory.md")

    # Create directories for images
    (directory / "photos").mkdir(exist_ok=True)
    (directory / "resized").mkdir(exist_ok=True)
    print("✅ Created image directories (photos/, resized/)")

    print(f"\n🎉 Inventory initialized in {directory}")
    print("\nNext steps:")
    print(f"1. Edit {directory / 'inventory.md'} to add your items")
    print(f"2. Run: inventory-md parse {directory / 'inventory.md'}")
    print(f"3. Open {directory / 'search.html'} in your browser")

    return 0


def _update_from_template(source: Path, target: Path) -> int:
    """Copy source to target when content differs; silent no-op when already current.

    These files carry a 'do not edit' header — no prompts are needed.
    """
    if not source.exists():
        print(f"❌ Template not found: {source}")
        return 1

    if not target.parent.exists():
        print(f"❌ Directory not found: {target.parent}")
        return 1

    if target.exists() and target.read_bytes() == source.read_bytes():
        return 0

    shutil.copy(source, target)
    print(f"✅ Updated {target}")
    return 0


def update_template(directory: Path = None) -> int:
    """Update search.html to the latest version from the package."""
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory).resolve()
    source = Path(__file__).parent / "templates" / "search.html"
    return _update_from_template(source, directory / "search.html")


def update_makefile(directory: Path = None) -> int:
    """Update inventory Makefile to the latest version from the package."""
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory).resolve()
    source = Path(__file__).parent / "templates" / "Makefile"
    return _update_from_template(source, directory / "Makefile")


def parse_command(
    md_file: Path,
    output: Path = None,
    validate_only: bool = False,
    wanted_items: Path = None,
    include_dated: bool = True,
    lang: str = None,
    tingbok_url: str | None = None,
    no_push: bool = False,
    verbose: bool = False,
) -> int:
    """Parse inventory markdown file and generate JSON."""
    md_file = Path(md_file).resolve()

    if not md_file.exists():
        print(f"❌ Error: {md_file} not found!")
        return 1

    if output is None:
        output = md_file.parent / "inventory.json"

    tingbok_session = None
    try:
        # Add ID: prefixes to container headers if not validating
        if not validate_only:
            print("🔍 Checking for duplicate container IDs...")
            _cfg = load_config()
            _sections_cfg = _cfg.get("sections", {})
            _skip = [_sections_cfg.get("intro", "Intro"), _sections_cfg.get("numbering_scheme", "Nummereringsregime")]
            changes, duplicates = parser.add_container_id_prefixes(md_file, skip_sections=_skip)

            if duplicates:
                print("⚠️  Found duplicate container IDs:")
                for orig_id, new_ids in duplicates.items():
                    print(f"   {orig_id} → {', '.join(new_ids)}")

            if changes > 0:
                print(f"✏️  Added ID: prefix to {changes} container headers")
            else:
                print("✅ All container headers already have ID: prefix")

        print(f"\n🔄 Parsing {md_file}...")
        data = parser.parse_inventory(md_file)

        print(f"✅ Found {len(data['containers'])} containers")

        # Count total images and items
        total_images = sum(len(container["images"]) for container in data["containers"])
        total_items = sum(len(container["items"]) for container in data["containers"])
        items_with_id = sum(1 for container in data["containers"] for item in container["items"] if item.get("id"))
        items_with_parent = sum(
            1 for container in data["containers"] for item in container["items"] if item.get("parent")
        )

        print(f"✅ Found {total_images} images and {total_items} items")
        print(f"   - {items_with_id} items with explicit IDs")
        print(f"   - {items_with_parent} items with parent references")

        # Validate and print issues
        print("\n🔍 Validating inventory...")
        issues = parser.validate_inventory(data)

        if issues:
            print(f"\n⚠️  Found {len(issues)} issue(s):")
            for issue in issues[:20]:  # Limit to first 20
                print(f"   {issue}")
            if len(issues) > 20:
                print(f"   ... and {len(issues) - 20} more")
        else:
            print("✅ No validation issues found!")

        # Save to JSON if not validating
        if not validate_only:
            if lang and lang != "en":
                data["lang"] = lang
            parser.save_json(data, output)
            print(f"\n✅ Success! {output} has been updated.")

            # Generate photo directory listings for backup
            print("\n📸 Generating photo directory listings...")
            containers_processed, files_created = parser.generate_photo_listings(md_file.parent)
            if files_created > 0:
                print(f"✅ Created {files_created} photo listing(s) in photo-listings/")
            else:
                print("   No photos found (photo-listings/ not updated)")

            # Parse photo registry if it exists
            photo_registry_md = md_file.parent / "photo-registry.md"
            if photo_registry_md.exists():
                import json as json_module

                from . import photo_registry

                print("\n📷 Parsing photo registry...")
                registry_data = photo_registry.parse_photo_registry(photo_registry_md)
                registry_output = md_file.parent / "photo-registry.json"
                registry_output.write_text(
                    json_module.dumps(registry_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"✅ Found {len(registry_data['photos'])} photos mapped to {len(registry_data['items'])} items")
                print(f"   Saved to {registry_output}")

            # Generate vocabulary.json for category browser
            print("\n🏷️  Generating category vocabulary...")

            # Single multiplexed session for all tingbok HTTP calls this run.
            import niquests

            tingbok_session = niquests.Session(multiplexed=True) if tingbok_url else None

            # Client-side cache for EAN and category lookups (one-week TTL).
            from pathlib import Path as _Path

            _tingbok_cache = _Path.home() / ".cache" / "inventory-md" / "tingbok" if tingbok_url else None

            # Collect all category labels used in this inventory (for batch resolve below).
            inventory_labels: list[str] = list(
                {
                    cat
                    for container in data.get("containers", [])
                    for item in container.get("items", [])
                    for cat in item.get("metadata", {}).get("categories", [])
                }
            )

            # Also include wanted-items category labels so the resolve endpoint can
            # express relationships between inventory items and desired categories
            # (e.g. "olive-oil" broader "cooking-oil" when both are in the request).
            wanted_labels: list[str] = []
            if wanted_items:
                wanted_path_for_labels = Path(wanted_items).resolve()
                if wanted_path_for_labels.exists():
                    from . import shopping_list as _sl_mod

                    _wanted_sections = _sl_mod.parse_wanted_items(wanted_path_for_labels.read_text(encoding="utf-8"))
                    wanted_labels = list({item.tag for section in _wanted_sections for item in section.items})

            resolve_labels: list[str] = list({*inventory_labels, *wanted_labels})

            # Load global vocabulary.
            # Prefer the tailored batch-resolve endpoint (one round-trip, ancestors included).
            # Fall back to the full vocabulary download when the endpoint is unavailable.
            global_vocab: dict = {}
            if tingbok_url and resolve_labels:
                try:
                    global_vocab = vocabulary.resolve_vocabulary_from_tingbok(
                        resolve_labels, tingbok_url, lang=lang or "en", session=tingbok_session
                    )
                    tingbok_concepts = sum(1 for c in global_vocab.values() if c.source == "tingbok")
                    print(f"   Resolved {len(resolve_labels)} label(s) → {len(global_vocab)} concepts from tingbok")
                    if tingbok_concepts < len(global_vocab):
                        print(f"   ({len(global_vocab) - tingbok_concepts} local stubs for unrecognised labels)")
                except vocabulary.TingbokUnavailableError:
                    # Fall back to full vocabulary download
                    global_vocab = vocabulary.load_global_vocabulary(
                        tingbok_url=tingbok_url,
                        skip_cwd=True,
                        session=tingbok_session,
                    )
                    if global_vocab:
                        print(f"   Loaded {len(global_vocab)} concepts from global vocabulary (fallback)")
            elif tingbok_url:
                global_vocab = vocabulary.load_global_vocabulary(
                    tingbok_url=tingbok_url,
                    skip_cwd=True,
                    session=tingbok_session,
                )
                if global_vocab:
                    print(f"   Loaded {len(global_vocab)} concepts from global vocabulary")

            # Load local vocabulary if present (highest priority - overrides global)
            local_vocab_yaml = md_file.parent / "local-vocabulary.yaml"
            local_vocab_json = md_file.parent / "local-vocabulary.json"
            local_vocab = {}
            if local_vocab_yaml.exists():
                local_vocab = vocabulary.load_local_vocabulary(local_vocab_yaml)
                print(f"   Loaded {len(local_vocab)} concepts from local-vocabulary.yaml")
            elif local_vocab_json.exists():
                local_vocab = vocabulary.load_local_vocabulary(local_vocab_json)
                print(f"   Loaded {len(local_vocab)} concepts from local-vocabulary.json")

            # Merge global and local (local overrides global)
            local_vocab = vocabulary.merge_vocabularies(global_vocab, local_vocab)

            # Build vocabulary from inventory categories
            vocab = vocabulary.build_vocabulary_from_inventory(data, local_vocab=local_vocab, lang=lang or "en")
            category_counts = vocabulary.count_items_per_category(data)

            # EAN lookup: query tingbok for each item with an EAN barcode
            ean_category_labels: list[str] = []
            if tingbok_url:
                eans_found = {
                    item["metadata"]["ean"]: item
                    for container in data["containers"]
                    for item in container["items"]
                    if item.get("metadata", {}).get("ean")
                }
                if eans_found:
                    print(f"\n🔖 Looking up {len(eans_found)} EAN barcode(s) via tingbok...")
                    ean_misses = 0
                    for ean, item in eans_found.items():
                        product = vocabulary.lookup_ean_via_tingbok(
                            ean, tingbok_url, session=tingbok_session, cache_dir=_tingbok_cache
                        )
                        item["_product"] = product  # stash for observation-needed check below
                        if product:
                            name = product.get("name") or "(unknown name)"
                            brand = product.get("brand") or ""
                            cats = product.get("categories") or []
                            desc = f"{brand} {name}".strip() if brand else name
                            if cats:
                                # Queue the most specific category for hierarchy resolution
                                ean_category_labels.append(cats[-1])
                                if verbose:
                                    print(f"   EAN:{ean} → {desc} (category: {cats[-1]})")
                            elif verbose:
                                print(f"   EAN:{ean} → {desc} (no category)")
                        else:
                            ean_misses += 1
                            if verbose:
                                print(f"   EAN:{ean} → not found in tingbok")
                    print(f"   {len(eans_found) - ean_misses} resolved, {ean_misses} not in tingbok")

                    if no_push:
                        print("\n📤 Skipping EAN observation push (--no-push)")
                    else:
                        # Report inventory observations back to tingbok for EANs that need it.
                        # Skip EANs whose GET response already contains our observations
                        # (meaning a previous run pushed successfully).
                        print(f"\n📤 Checking {len(eans_found)} EAN observation(s) ...")
                        reported = skipped = 0
                        for ean, item in eans_found.items():
                            meta = item.get("metadata", {})
                            cats: list[str] = meta.get("categories") or []
                            name: str | None = item.get("name") or None
                            quantity: str | None = meta.get("mass") or meta.get("volume") or None
                            price_dict = _parse_inventory_price(meta.get("price"))
                            prices = [price_dict] if price_dict else []
                            product = item.get("_product")  # stashed during the GET loop above
                            if not vocabulary.ean_observation_needed(product, cats, name, quantity, prices):
                                skipped += 1
                                continue
                            vocabulary.report_ean_to_tingbok(
                                ean,
                                cats,
                                name,
                                tingbok_url,
                                session=tingbok_session,
                                quantity=quantity,
                                prices=prices,
                                cache_dir=_tingbok_cache,
                            )
                            reported += 1
                        print(f"   Pushed {reported} observation(s), {skipped} already up-to-date")

            # Enrich EAN-derived category labels not yet in vocab (via /api/lookup).
            # Inventory categories were already resolved in the batch call above;
            # only EAN-sourced labels that weren't in the inventory at parse time need this.
            category_mappings = None
            if tingbok_url and ean_category_labels:
                to_enrich: list[str] = [
                    label for label in ean_category_labels if label not in vocab or vocab[label].source == "inventory"
                ]
                if to_enrich:
                    resolved, category_mappings = vocabulary.enrich_categories_via_lookup(
                        to_enrich, tingbok_url, session=tingbok_session, cache_dir=_tingbok_cache, verbose=verbose
                    )
                    if resolved:
                        vocab.update(resolved)
                        for cid, c in global_vocab.items():
                            existing = vocab.get(cid)
                            if existing is not None and existing.source == "inventory":
                                vocab[cid] = c
                        print(f"   Enriched {len(resolved)} EAN-derived categories via tingbok lookup")

            if vocab:
                vocab_output = md_file.parent / "vocabulary.json"
                vocabulary.save_vocabulary_json(vocab, vocab_output, category_mappings)
                mode_info = " (hierarchy mode)" if category_mappings else ""
                print(f"✅ Generated {vocab_output} with {len(vocab)} categories{mode_info}")
                if category_mappings:
                    # Show sample mappings
                    sample = list(category_mappings.items())[:3]
                    for label, paths in sample:
                        print(f"   {label} → {paths[0] if paths else '?'}")
                    if len(category_mappings) > 3:
                        print(f"   ... and {len(category_mappings) - 3} more mappings")
                elif category_counts:
                    top_categories = sorted(category_counts.items(), key=lambda x: -x[1])[:5]
                    print(f"   Top categories: {', '.join(f'{c}({n})' for c, n in top_categories)}")
            else:
                print("   No categories found in inventory")

            # Generate shopping list if wanted-items file specified
            if wanted_items:
                wanted_path = Path(wanted_items).resolve()
                if not wanted_path.exists():
                    print(f"\n⚠️  wanted-items file not found: {wanted_path}")
                else:
                    output_shopping = md_file.parent / "shopping-list.md"
                    result = shopping_list.generate_shopping_list(
                        wanted_path, output, include_dated=include_dated, lang=lang or "en"
                    )
                    output_shopping.write_text(result, encoding="utf-8")
                    dated_note = " (including dated files)" if include_dated else ""
                    print(f"\n🛒 Generated {output_shopping}{dated_note}")

            search_html = md_file.parent / "search.html"
            print("\n📱 To view the searchable inventory, open search.html in your browser:")
            print(f"   xdg-open {search_html}")

        return 0

    except Exception as e:
        import traceback

        print(f"\n❌ Error parsing inventory: {e}")
        traceback.print_exc()
        return 1
    finally:
        if tingbok_session is not None:
            tingbok_session.close()


def serve_command(directory: Path = None, port: int = 8000, host: str = "127.0.0.1", api_proxy: str = None) -> int:
    """Start a local web server to view the inventory.

    If api_proxy is specified (e.g., 'localhost:8765'), requests to /api/ and /chat
    will be proxied to that backend.
    """
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory).resolve()

    if not directory.exists():
        print(f"❌ Directory {directory} does not exist")
        return 1

    search_html = directory / "search.html"
    if not search_html.exists():
        print(f"❌ search.html not found in {directory}")
        print(f"Run 'inventory-md init {directory}' first")
        return 1

    # Display the address - show 0.0.0.0 as "all interfaces"
    display_host = "0.0.0.0 (all interfaces)" if host == "0.0.0.0" else host
    print(f"🌐 Starting web server at http://{display_host}:{port}")
    print(f"📂 Serving directory: {directory}")
    if api_proxy:
        print(f"🔄 Proxying /api/* and /chat to http://{api_proxy}")
    print("Press Ctrl+C to stop\n")

    import http.server
    import os
    import socketserver

    try:
        import niquests as _requests
    except ImportError:
        import requests as _requests

    os.chdir(directory)

    class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        """HTTP handler that can proxy API requests to a backend server."""

        def do_proxy(self, method: str):
            """Proxy request to the API backend."""
            if not api_proxy:
                self.send_error(404, "API proxy not configured")
                return

            backend_url = f"http://{api_proxy}{self.path}"

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            fwd_headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}

            try:
                resp = _requests.request(method, backend_url, data=body, headers=fwd_headers, timeout=90)
                self.send_response(resp.status_code)
                for header, value in resp.headers.items():
                    if header.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(header, value)
                self.end_headers()
                self.wfile.write(resp.content)
            except _requests.exceptions.ConnectionError as e:
                self.send_error(502, f"Backend unavailable: {e}")
            except Exception as e:
                self.send_error(500, f"Proxy error: {e}")

        def should_proxy(self) -> bool:
            """Check if this request should be proxied."""
            return api_proxy and (
                self.path.startswith("/api/") or self.path.startswith("/chat") or self.path.startswith("/health")
            )

        def do_GET(self):
            if self.should_proxy():
                self.do_proxy("GET")
            else:
                super().do_GET()

        def do_POST(self):
            if self.should_proxy():
                self.do_proxy("POST")
            else:
                self.send_error(405, "Method Not Allowed")

        def do_PUT(self):
            if self.should_proxy():
                self.do_proxy("PUT")
            else:
                self.send_error(405, "Method Not Allowed")

        def do_DELETE(self):
            if self.should_proxy():
                self.do_proxy("DELETE")
            else:
                self.send_error(405, "Method Not Allowed")

        def do_OPTIONS(self):
            if self.should_proxy():
                self.do_proxy("OPTIONS")
            else:
                # Handle CORS preflight for non-proxied requests
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

    Handler = ProxyHTTPRequestHandler
    try:
        with socketserver.TCPServer((host, port), Handler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n\n👋 Server stopped")
                return 0
    except Exception as e:
        import traceback

        print(f"\n❌ Server failed to start: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        return 1


def api_command(directory: Path = None, port: int = 8765, host: str = "127.0.0.1") -> int:
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

    inventory_json = directory / "inventory.json"
    if not inventory_json.exists():
        print(f"❌ inventory.json not found in {directory}")
        print("Run 'inventory-md parse inventory.md' first")
        return 1

    # Change to directory so API server can find inventory.json
    os.chdir(directory)

    print("🚀 Starting Inventory API Server...")
    print(f"📂 Using inventory: {inventory_json}")
    print(f"🌐 Server will run at: http://{host}:{port}")
    print(f"💬 Chat endpoint: http://localhost:{port}/chat")
    print(f"📸 Photo upload: http://localhost:{port}/api/photos")
    print(f"➕ Add/remove items: http://localhost:{port}/api/items")
    print(f"❤️  Health check: http://localhost:{port}/health")
    print("\nOpen search.html in your browser to use the interface")
    print("Press Ctrl+C to stop\n")

    # Import and run the API server
    try:
        import uvicorn

        from .api_server import app
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("\nInstall API server dependencies:")
        print("  pip install fastapi uvicorn anthropic python-multipart")
        return 1

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        print("\n\n👋 Chat server stopped")
        return 0
    except Exception as e:
        import traceback

        print(f"\n❌ Server failed to start: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        return 1


def labels_generate(
    series: str | None = None,
    start: str | None = None,
    ids: str | None = None,
    count: int = 1,
    style: str = "standard",
    sheet_format: str = "48x25-40",
    output: Path | None = None,
    output_format: str = "pdf",
    base_url: str = "https://inventory.example.com/search.html",
    custom_formats: dict | None = None,
    dupes: int | None = None,
) -> int:
    """Generate label sheet or PNG images."""
    try:
        from . import labels
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("\nInstall labels dependencies:")
        print('  pip install "inventory-md[labels]"')
        return 1

    # Determine label IDs (unique)
    try:
        if ids:
            unique_ids = [id.strip().upper() for id in ids.split(",")]
            # Validate all IDs
            for lid in unique_ids:
                if not labels.validate_label_id(lid):
                    print(f"Invalid label ID: {lid}")
                    print("Format must be: [A-Z][A-Z][0-9] (e.g., AA0, BC5)")
                    return 1
        else:
            unique_ids = labels.generate_id_sequence(series=series, start=start, count=count)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Determine number of duplicates per label
    if dupes is None:
        # Default: 5 for standard (label each side of container), 1 for compact/duplicate
        dupes = 5 if style == "standard" else 1

    # Expand IDs with duplicates
    label_ids = []
    for lid in unique_ids:
        label_ids.extend([lid] * dupes)

    # Default output path: labels/labels-{start}-{end}.pdf
    if output is None:
        labels_dir = Path("labels")
        labels_dir.mkdir(exist_ok=True)
        if output_format == "png":
            output = labels_dir
        else:
            output = labels_dir / f"labels-{unique_ids[0]}-{unique_ids[-1]}.pdf"

    # Generate
    try:
        if output_format == "png":
            fmt = labels.get_sheet_format(sheet_format, custom_formats)
            created_files = labels.save_labels_as_png(
                label_ids,
                base_url,
                str(output),
                style=style,
                width_mm=fmt["label_width_mm"],
                height_mm=fmt["label_height_mm"],
            )
            print(f"Created {len(created_files)} PNG files in {output}/")
            for f in created_files[:5]:
                print(f"  {f}")
            if len(created_files) > 5:
                print(f"  ... and {len(created_files) - 5} more")
        else:
            pdf_bytes = labels.create_label_sheet(
                label_ids,
                base_url,
                sheet_format=sheet_format,
                style=style,
                custom_formats=custom_formats,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(pdf_bytes)
            print(f"Created {output} with {len(label_ids)} labels ({len(unique_ids)} unique x {dupes} dupes)")
            print(f"  IDs: {unique_ids[0]} - {unique_ids[-1]}")

        return 0
    except Exception as e:
        import traceback

        print(f"Error generating labels: {e}")
        traceback.print_exc()
        return 1


def labels_formats(custom_formats: dict | None = None) -> int:
    """List available label sheet formats."""
    try:
        from . import labels
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("\nInstall labels dependencies:")
        print('  pip install "inventory-md[labels]"')
        return 1

    print("Available label sheet formats:\n")
    formats = labels.list_formats(custom_formats)
    for name, description in formats:
        print(f"  {name:15} {description}")

    print("\nUse with: inventory-md labels generate --sheet-format FORMAT")
    return 0


def labels_preview(
    series: str | None = None,
    start: str | None = None,
    count: int = 1,
) -> int:
    """Preview label IDs without generating."""
    try:
        from . import labels
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("\nInstall labels dependencies:")
        print('  pip install "inventory-md[labels]"')
        return 1

    try:
        label_ids = labels.generate_id_sequence(series=series, start=start, count=count)
        print(" ".join(label_ids))
        return 0
    except ValueError as e:
        print(f"Error: {e}")
        return 1


def config_command(show: bool = False, show_path: bool = False) -> int:
    """Show configuration information."""
    config = Config()

    if show_path:
        if config.path:
            print(config.path)
        else:
            print("No configuration file found")
        return 0

    if show or (not show_path):
        # Show merged config
        if config.path:
            print(f"# Configuration loaded from: {config.path}")
        else:
            print("# No configuration file found, showing defaults")
        print()
        print(json.dumps(config.data, indent=2))
        return 0

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    # Load configuration (used for defaults)
    config = Config()

    parser_cli = argparse.ArgumentParser(
        description="Inventory System - Manage markdown-based inventories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize a new inventory
  inventory-md init ~/my-inventory --name "Home Storage"

  # Parse inventory and generate JSON
  inventory-md parse ~/my-inventory/inventory.md

  # Validate inventory without generating JSON
  inventory-md parse ~/my-inventory/inventory.md --validate

  # Start a local web server
  inventory-md serve ~/my-inventory

  # Start API server for chat, photos, and item management (requires ANTHROPIC_API_KEY)
  inventory-md api ~/my-inventory

  # Show current configuration
  inventory-md config --show
        """,
    )
    parser_cli.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser_cli.add_subparsers(dest="command", help="Command to run")

    # Config command
    config_parser = subparsers.add_parser("config", help="Show configuration")
    config_parser.add_argument("--show", action="store_true", help="Show merged configuration")
    config_parser.add_argument("--path", action="store_true", help="Show config file path")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new inventory")
    init_parser.add_argument("directory", type=Path, help="Directory to initialize")
    init_parser.add_argument("--name", type=str, default="My Inventory", help="Name of the inventory")

    # Parse command
    parse_parser = subparsers.add_parser("parse", help="Parse inventory markdown file")
    parse_parser.add_argument(
        "file",
        type=Path,
        nargs="?",
        help="Inventory markdown file to parse (default: from config or inventory.md with --auto)",
    )
    parse_parser.add_argument("--output", "-o", type=Path, help="Output JSON file (default: inventory.json)")
    parse_parser.add_argument("--validate", action="store_true", help="Validate only, do not generate JSON")
    parse_parser.add_argument("--wanted-items", "-w", type=Path, help="Wanted items file to generate shopping list")
    parse_parser.add_argument(
        "--no-dated",
        action="store_true",
        help="Exclude dated wanted-items files (wanted-items-YYYY-MM-DD[-recipe-name].md)",
    )
    parse_parser.add_argument(
        "--auto",
        "-a",
        action="store_true",
        help="Auto-detect files: inventory.md and wanted-items.md in current directory",
    )
    parse_parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip pushing EAN observations back to tingbok (parse and look up only)",
    )
    parse_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-EAN and per-category tingbok lookup lines (default: summaries only)",
    )
    # Shopping-list command
    sl_parser = subparsers.add_parser(
        "shopping-list", help="Regenerate shopping-list.md from wanted-items.md and inventory.json"
    )
    sl_parser.add_argument(
        "--wanted-items", "-w", type=Path, help="Wanted items file (default: auto-detect wanted-items.md)"
    )
    sl_parser.add_argument(
        "--no-dated",
        action="store_true",
        help="Exclude dated wanted-items files (wanted-items-YYYY-MM-DD[-recipe-name].md)",
    )
    sl_parser.add_argument(
        "--stdout", action="store_true", help="Print shopping list to stdout instead of writing file"
    )

    # Expiring command
    expiring_parser = subparsers.add_parser(
        "expiring",
        help="List inventory items by best-before date",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
By default (no options), shows only items that have already expired.

Examples:
  inventory-md expiring                    # already-expired items
  inventory-md expiring --food             # expired food only (needs vocabulary.json)
  inventory-md expiring --limit 10         # top 10 items by expiry date
  inventory-md expiring --all              # all items with a best-before date
  inventory-md expiring --before 2026-06   # items expiring before June 2026
  inventory-md expiring --category rice --all   # all rice packets, by expiry

Note: --category matches the item's category metadata (hierarchy-aware via
vocabulary.json), not its ID. Items not tagged with the category are not shown.
        """,
    )
    expiring_parser.add_argument(
        "file", type=Path, nargs="?", help="inventory.json to read (default: ./inventory.json)"
    )
    expiring_parser.add_argument("--food", action="store_true", help="Only show food items (uses vocabulary.json)")
    expiring_parser.add_argument(
        "--category",
        "-c",
        type=str,
        metavar="CATEGORY",
        help="Only show items in this category or a descendant of it (e.g. rice)",
    )
    expiring_parser.add_argument("--limit", type=int, help="Show top N items sorted by expiry (no date filtering)")
    expiring_parser.add_argument(
        "--all", action="store_true", help="Show all items with expiry dates, not just expired"
    )
    expiring_parser.add_argument(
        "--before", type=str, metavar="DATE", help="Show items expiring before DATE (YYYY-MM-DD or YYYY-MM)"
    )

    # Lookup command
    lookup_parser = subparsers.add_parser(
        "lookup",
        help="Look up items by ID or text (includes items without a best-before date)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Unlike 'expiring', this also reports items with no best-before date (e.g. fresh
produce), which is what you need when assembling a recipe ingredient list.

Examples:
  inventory-md lookup --id bacon-pikok --id asparagus-2026-06-06
  inventory-md lookup --match onion --match tomato   # substring on id+name
        """,
    )
    lookup_parser.add_argument("file", type=Path, nargs="?", help="inventory.json to read (default: ./inventory.json)")
    lookup_parser.add_argument("--id", action="append", default=[], dest="ids", help="Exact item ID (repeatable)")
    lookup_parser.add_argument(
        "--match",
        action="append",
        default=[],
        dest="matches",
        help="Case-insensitive substring on id+name (repeatable)",
    )

    # Container command
    container_parser = subparsers.add_parser(
        "container",
        help="List the items in a container (and its direct sub-containers)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Inspect a container's contents from the parsed inventory.json, rather than
grepping inventory.md. By default direct sub-containers are included, so e.g.
'container pantry' also lists what is in 'pantry-fridge'.

Examples:
  inventory-md container pantry
  inventory-md container pantry --no-children
        """,
    )
    container_parser.add_argument("container_id", help="Container ID to list (e.g. pantry, fridge, food1)")
    container_parser.add_argument(
        "file", type=Path, nargs="?", help="inventory.json to read (default: ./inventory.json)"
    )
    container_parser.add_argument(
        "--no-children", action="store_true", help="List only the named container, not its sub-containers"
    )

    # Add command — append an item line to a container in inventory.md
    add_parser = subparsers.add_parser(
        "add",
        help="Add an item line to a container in inventory.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Append a validated item line under a container's section in inventory.md.
Folds the quality checks into the write step: duplicate-ID detection, the
food-without-best-before check, and category resolution against the local
vocabulary.  If --id is omitted, a readable ID is generated (the category leaf,
plus the date for food items, e.g. milk-2026-06-14).

Examples:
  inventory-md add food1 --category milk --bb 2026-07 --volume 1l "Whole milk"
  inventory-md add food1 --category potatoes --bb 2026-09 --est --mass 1200g Potatoes
  inventory-md add A2 --category hammer --id bosch-hammer "Bosch hammer"
        """,
    )
    add_parser.add_argument("container_id", help="Container ID to add the item to (e.g. food1, A2)")
    add_parser.add_argument("name", nargs="*", help="Human-readable description (rest of the line)")
    add_parser.add_argument(
        "--category", "-c", required=True, help="Category, e.g. milk or food/dairy/milk (comma-separated for several)"
    )
    add_parser.add_argument("--id", dest="item_id", help="Item ID (unique); auto-generated if omitted")
    add_parser.add_argument("--ean", help="Product barcode")
    add_parser.add_argument("--isbn", help="ISBN (for books)")
    add_parser.add_argument("--bb", help="Best-before date: YYYY, YYYY-MM or YYYY-MM-DD")
    add_parser.add_argument("--est", action="store_true", help="Mark the best-before date as estimated (:EST)")
    add_parser.add_argument("--qty", help="Quantity of identical items")
    add_parser.add_argument("--mass", help="Net mass per unit, e.g. 500g or 1.2kg")
    add_parser.add_argument("--volume", help="Volume per unit, e.g. 1l or 400ml")
    add_parser.add_argument("--price", help="Price at purchase, e.g. EUR:2.49/pcs")
    add_parser.add_argument("--value", help="Subjective value estimate, e.g. NOK:200")
    add_parser.add_argument("--tag", action="append", dest="tags", help="Tag (repeatable), e.g. condition:new")
    add_parser.add_argument("--no-bb-check", action="store_true", help="Skip the food-without-best-before check")
    add_parser.add_argument("--strict", action="store_true", help="Treat unresolved categories as errors, not warnings")
    add_parser.add_argument(
        "--file", type=Path, dest="file", help="inventory.md to edit (default: configured or ./inventory.md)"
    )

    # Edit command — change fields on an existing item line in inventory.md
    edit_parser = subparsers.add_parser(
        "edit",
        help="Change fields on an existing item line in inventory.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Rewrite a single existing ID: bullet in place — the counterpart to the
append-only `add`, for correcting a line that is already in the file (a mistyped
EAN, a best-before that turned up on a late label photo, a shop-local barcode
that needs its chain prefix).  Fields already on the line are substituted where
they stand; new ones are inserted at their canonical position; an empty value
removes a field.  Indented sub-bullets and the rest of the file are untouched,
and the same QA as `add` applies (category resolution, food-without-bb).

--est / --no-est on their own flip the :EST marker on the date already present,
which is how an estimate recorded as a hard date is repaired.

Examples:
  inventory-md edit bacon-2026-07-09 --ean 4056489080510 --bb 2026-07-24
  inventory-md edit yogurt-2026-07-21 --est
  inventory-md edit pork-belly-2026-07-21 --ean lidl-20709167 --dry-run
  inventory-md edit drill-bosch --tag condition:used --price EUR:89/pcs
        """,
    )
    edit_parser.add_argument("item_id", help="ID of the item to edit (e.g. milk-2026-07-21)")
    edit_parser.add_argument("--category", "-c", help="Replace the category (comma-separated for several)")
    edit_parser.add_argument("--name", help="Replace the human-readable description")
    edit_parser.add_argument("--ean", help="Product barcode (empty string removes it)")
    edit_parser.add_argument("--isbn", help="ISBN (empty string removes it)")
    edit_parser.add_argument("--bb", help="Best-before date: YYYY, YYYY-MM or YYYY-MM-DD (empty string removes it)")
    est_group = edit_parser.add_mutually_exclusive_group()
    est_group.add_argument("--est", action="store_true", help="Mark the best-before date as estimated (:EST)")
    est_group.add_argument(
        "--no-est", action="store_true", help="Drop the :EST marker — the date is printed on the product"
    )
    edit_parser.add_argument("--qty", help="Quantity of identical items (empty string removes it)")
    edit_parser.add_argument("--mass", help="Net mass, e.g. 500g or 1.2kg (empty string removes it)")
    edit_parser.add_argument("--volume", help="Volume, e.g. 1l or 400ml (empty string removes it)")
    edit_parser.add_argument("--price", help="Price at purchase, e.g. EUR:2.49/pcs (empty string removes it)")
    edit_parser.add_argument("--value", help="Subjective value estimate, e.g. NOK:200 (empty string removes it)")
    edit_parser.add_argument(
        "--tag", action="append", dest="tags", help="Tag (repeatable); replaces the item's existing tags"
    )
    edit_parser.add_argument("--no-bb-check", action="store_true", help="Skip the food-without-best-before check")
    edit_parser.add_argument(
        "--strict", action="store_true", help="Treat unresolved categories as errors, not warnings"
    )
    edit_parser.add_argument(
        "--dry-run", action="store_true", help="Validate and report the new line without writing the file"
    )
    edit_parser.add_argument(
        "--file", type=Path, dest="file", help="inventory.md to edit (default: configured or ./inventory.md)"
    )

    # Move command
    move_parser = subparsers.add_parser(
        "move",
        help="Move an existing item to another container in inventory.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Relocate an existing ID:-tagged item bullet from wherever it currently sits into
another container's section, carrying any of its indented sub-bullets along.
Only items that exist as a single ID: bullet can be moved; free-text list entries
without an ID are not addressable.

Examples:
  inventory-md move wd40-200ml TB-23
  inventory-md move sealant-soudal TB-24 --dry-run
        """,
    )
    move_parser.add_argument("item_id", help="ID of the item to move (e.g. wd40-200ml)")
    move_parser.add_argument("container_id", help="Destination container ID (e.g. TB-23)")
    move_parser.add_argument(
        "--dry-run", action="store_true", help="Validate and report the move without writing the file"
    )
    move_parser.add_argument(
        "--file", type=Path, dest="file", help="inventory.md to edit (default: configured or ./inventory.md)"
    )

    # Ean command — ad-hoc barcode lookup
    ean_parser = subparsers.add_parser(
        "ean",
        help="Look up a product barcode in the inventory and in tingbok",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Answers "what is this barcode, and do I already have one?" without a raw HTTP
call — which is a permission prompt in an otherwise unattended shopping run,
and one more hostname to remember. Local inventory first, then tingbok.

Matching ignores separators and the shop-name prefix on shop-local article
numbers, so 40853712 also finds lidl-40853712.

Exit status is 1 when a barcode is known neither locally nor to tingbok.

Examples:
  inventory-md ean 5941132002140
  inventory-md ean 5941132002140 8680041405983 --json
  inventory-md ean 5941132002140 --no-tingbok      # offline, inventory only
        """,
    )
    ean_parser.add_argument("eans", nargs="+", metavar="EAN", help="Barcode(s) to look up")
    ean_parser.add_argument("--directory", "-d", type=Path, help="Inventory directory (default: current)")
    ean_parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    ean_parser.add_argument("--no-tingbok", action="store_true", help="Skip the tingbok lookup (inventory only)")

    # Update-template command
    update_parser = subparsers.add_parser("update-template", help="Update search.html to latest version")
    update_parser.add_argument("directory", type=Path, nargs="?", help="Target directory (default: current directory)")

    update_mk_parser = subparsers.add_parser("update-makefile", help="Update inventory Makefile to latest version")
    update_mk_parser.add_argument(
        "directory", type=Path, nargs="?", help="Target directory (default: current directory)"
    )

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Start local web server")
    serve_parser.add_argument("directory", type=Path, nargs="?", help="Directory to serve (default: current directory)")
    serve_parser.add_argument(
        "--port", "-p", type=int, default=None, help=f"Port number (default: {config.serve_port})"
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default=None,
        help=f"Host to bind to (default: {config.serve_host}, use 0.0.0.0 for all interfaces)",
    )
    serve_parser.add_argument(
        "--api-proxy",
        type=str,
        metavar="HOST:PORT",
        help="Proxy /api/* and /chat requests to backend (e.g., localhost:8765)",
    )

    # API command
    api_parser = subparsers.add_parser("api", help="Start API server (chat, photos, item management)")
    api_parser.add_argument(
        "directory", type=Path, nargs="?", help="Directory with inventory.json (default: current directory)"
    )
    api_parser.add_argument("--port", "-p", type=int, default=None, help=f"Port number (default: {config.api_port})")
    api_parser.add_argument("--host", type=str, default=None, help=f"Host to bind to (default: {config.api_host})")

    # Chat command (backwards compatibility alias for 'api')
    chat_parser = subparsers.add_parser("chat", help='[Deprecated] Use "api" instead')
    chat_parser.add_argument(
        "directory", type=Path, nargs="?", help="Directory with inventory.json (default: current directory)"
    )
    chat_parser.add_argument("--port", "-p", type=int, default=None, help=f"Port number (default: {config.api_port})")
    chat_parser.add_argument("--host", type=str, default=None, help=f"Host to bind to (default: {config.api_host})")

    # Labels command with subcommands
    labels_parser = subparsers.add_parser("labels", help="Generate QR code labels for printing")
    labels_subparsers = labels_parser.add_subparsers(dest="labels_command", help="Labels subcommand")

    # labels generate
    labels_gen = labels_subparsers.add_parser(
        "generate",
        help="Generate label sheet or PNG images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Label styles:
  standard   QR code + large ID + date (default for labeling containers)
  compact    QR code only (for small labels)
  duplicate  Two identical QR codes + ID + date (for wide labels, can cut/tear)

Examples:
  inventory-md labels generate --series A --count 10
  inventory-md labels generate --start AB5 --count 5 --style compact
  inventory-md labels generate --ids AA0,AB0,AC0 --dupes 3
        """,
    )
    labels_gen.add_argument("--series", "-s", type=str, help="Series letter (A-Z), starts at {series}A0")
    labels_gen.add_argument("--start", type=str, help="Starting ID (e.g., AB5)")
    labels_gen.add_argument("--ids", type=str, help="Comma-separated list of specific IDs")
    labels_gen.add_argument(
        "--count", "-n", type=int, default=30, help="Number of unique IDs to generate (default: 30)"
    )
    labels_gen.add_argument(
        "--dupes",
        "-d",
        type=int,
        default=None,
        help="Duplicates per label (default: 5 for standard, 1 for compact/duplicate)",
    )
    labels_gen.add_argument(
        "--style",
        type=str,
        choices=["standard", "compact", "duplicate"],
        default=None,
        help="Label style (default: from config or standard)",
    )
    labels_gen.add_argument(
        "--sheet-format", type=str, default=None, help="Sheet format (default: from config or 48x25-40)"
    )
    labels_gen.add_argument("--output", "-o", type=Path, help="Output file (default: labels/labels-{start}-{end}.pdf)")
    labels_gen.add_argument(
        "--format", "-f", type=str, choices=["pdf", "png"], default="pdf", help="Output format (default: pdf)"
    )
    labels_gen.add_argument("--base-url", type=str, default=None, help="Base URL for QR codes (default: from config)")

    # labels formats
    labels_subparsers.add_parser("formats", help="List available sheet formats")

    # labels preview
    labels_prev = labels_subparsers.add_parser("preview", help="Preview label IDs without generating")
    labels_prev.add_argument("--series", "-s", type=str, help="Series letter (A-Z)")
    labels_prev.add_argument("--start", type=str, help="Starting ID (e.g., AB5)")
    labels_prev.add_argument("--count", "-n", type=int, default=10, help="Number of IDs to show (default: 10)")

    # Vocabulary command with subcommands
    vocab_parser = subparsers.add_parser("vocabulary", help="Manage local category vocabulary")
    vocab_subparsers = vocab_parser.add_subparsers(dest="vocab_command", help="Vocabulary subcommand")

    # vocabulary list
    vocab_list = vocab_subparsers.add_parser(
        "list",
        help="List all concepts in vocabulary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Lists all concepts from the local vocabulary and inventory categories.

Examples:
  inventory-md vocabulary list
  inventory-md vocabulary list --directory ~/my-inventory
        """,
    )
    vocab_list.add_argument("--directory", "-d", type=Path, help="Inventory directory (default: current)")
    vocab_list.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    # vocabulary lookup
    vocab_lookup = vocab_subparsers.add_parser("lookup", help="Look up a concept by label")
    vocab_lookup.add_argument("label", help="Label to look up (prefLabel or altLabel)")
    vocab_lookup.add_argument("--directory", "-d", type=Path, help="Inventory directory (default: current)")
    vocab_lookup.add_argument(
        "--lang",
        "-l",
        help="Language code for the tingbok lookup (e.g. nb, en). Default: from config.",
    )

    # vocabulary tree
    vocab_tree = vocab_subparsers.add_parser("tree", help="Show category hierarchy as tree")
    vocab_tree.add_argument("--directory", "-d", type=Path, help="Inventory directory (default: current)")

    # vocabulary search
    vocab_search = vocab_subparsers.add_parser(
        "search",
        help="Find inventory items matching a category (including children)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Search for inventory items by category, including all child categories.

Examples:
  inventory-md vocabulary search spices
  inventory-md vocabulary search food/spices --directory ~/my-inventory
  inventory-md vocabulary search cooking-oil
        """,
    )
    vocab_search.add_argument("label", help="Category label or path to search for")
    vocab_search.add_argument("--directory", "-d", type=Path, help="Inventory directory (default: current)")
    vocab_search.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    # Enable shell tab completion
    argcomplete.autocomplete(parser_cli)

    args = parser_cli.parse_args(argv)

    if args.command == "config":
        return config_command(show=getattr(args, "show", False), show_path=getattr(args, "path", False))
    elif args.command == "init":
        return init_inventory(args.directory, args.name)
    elif args.command == "parse":
        include_dated = not getattr(args, "no_dated", False)
        auto_mode = getattr(args, "auto", False)

        # Handle --auto mode
        if auto_mode:
            cwd = Path.cwd()
            md_file = args.file or cwd / "inventory.md"
            wanted_items = getattr(args, "wanted_items", None)
            if wanted_items is None:
                # Auto-detect wanted-items.md
                wanted_path = cwd / "wanted-items.md"
                if wanted_path.exists():
                    wanted_items = wanted_path
        else:
            # Try config values, then CLI args
            md_file = args.file
            if md_file is None:
                md_file = config.inventory_file
            wanted_items = getattr(args, "wanted_items", None)
            if wanted_items is None:
                wanted_items = config.wanted_file
            if md_file is None:
                print(
                    "Error: inventory file required (or use --auto, or set inventory_file in config)", file=sys.stderr
                )
                return 1

        return parse_command(
            md_file,
            args.output,
            args.validate,
            wanted_items,
            include_dated,
            lang=config.lang,
            tingbok_url=config.tingbok_url,
            no_push=getattr(args, "no_push", False),
            verbose=getattr(args, "verbose", False),
        )
    elif args.command == "update-template":
        return update_template(args.directory)
    elif args.command == "update-makefile":
        return update_makefile(args.directory)
    elif args.command == "serve":
        port = args.port if args.port is not None else config.serve_port
        host = args.host if args.host is not None else config.serve_host
        return serve_command(args.directory, port, host, getattr(args, "api_proxy", None))
    elif args.command == "api" or args.command == "chat":
        port = args.port if args.port is not None else config.api_port
        host = args.host if args.host is not None else config.api_host
        return api_command(args.directory, port, host)
    elif args.command == "labels":
        if args.labels_command == "generate":
            style = args.style if args.style else config.labels_style
            sheet_format = args.sheet_format if args.sheet_format else config.labels_sheet_format
            base_url = args.base_url if args.base_url else config.labels_base_url
            return labels_generate(
                series=args.series,
                start=args.start,
                ids=args.ids,
                count=args.count,
                style=style,
                sheet_format=sheet_format,
                output=args.output,
                output_format=args.format,
                base_url=base_url,
                custom_formats=config.labels_custom_formats,
                dupes=args.dupes,
            )
        elif args.labels_command == "formats":
            return labels_formats(custom_formats=config.labels_custom_formats)
        elif args.labels_command == "preview":
            return labels_preview(
                series=args.series,
                start=args.start,
                count=args.count,
            )
        else:
            labels_parser.print_help()
            return 1
    elif args.command == "vocabulary":
        return vocabulary_command(args, config)
    elif args.command == "shopping-list":
        return shopping_list_command(args, config)
    elif args.command == "expiring":
        return queries.expiring_command(
            args.file or Path("inventory.json"),
            food_only=args.food,
            category=args.category,
            limit=args.limit,
            before=args.before,
            show_all=args.all,
            lang=config.lang or "en",
        )
    elif args.command == "lookup":
        return queries.lookup_command(args.file or Path("inventory.json"), args.ids, args.matches)
    elif args.command == "container":
        return queries.container_command(
            args.file or Path("inventory.json"),
            args.container_id,
            include_children=not args.no_children,
        )
    elif args.command == "ean":
        return ean_command(args, config)
    elif args.command == "add":
        return add_item_command(args, config)
    elif args.command == "edit":
        return edit_item_command(args, config)
    elif args.command == "move":
        return move_item_command(args, config)
    else:
        parser_cli.print_help()
        return 1


def _resolve_md_path(args, config: Config) -> Path:
    """The markdown source for a write command: --file, else config, else ./inventory.md."""
    if args.file is not None:
        return args.file
    if config.inventory_file:
        return Path(config.inventory_file)
    return Path("inventory.md")


def add_item_command(args, config: Config) -> int:
    """Handle the `add` subcommand: append an item line to inventory.md."""
    md_path = _resolve_md_path(args, config)

    if not md_path.exists():
        print(f"❌ Error: {md_path} not found.")
        return 1

    name = " ".join(args.name).strip() if args.name else None

    result = additem.add_item(
        md_path,
        container_id=args.container_id,
        category=args.category,
        item_id=args.item_id,
        ean=args.ean,
        isbn=args.isbn,
        bb=args.bb,
        # --est absent means "unspecified", so a --bb that carries its own :EST
        # suffix is honoured instead of colliding with an implicit False.
        bb_est=args.est or None,
        qty=args.qty,
        mass=args.mass,
        volume=args.volume,
        price=args.price,
        value=args.value,
        tags=args.tags,
        name=name,
        check_bb=not args.no_bb_check,
        strict=args.strict,
        lang=config.lang or "en",
        tingbok_url=config.tingbok_url,
    )

    for warning in result.warnings:
        print(f"⚠️  {warning}")

    if result.errors:
        for error in result.errors:
            print(f"❌ {error}")
        return 1

    print(f"✅ Added to {args.container_id}:\n   {result.item_line}")
    print(f"   in {md_path}")
    print("Run 'inventory-md parse' to refresh inventory.json.")
    return 0


def edit_item_command(args, config: Config) -> int:
    """Handle the `edit` subcommand: change fields on an existing item line."""
    md_path = _resolve_md_path(args, config)

    if not md_path.exists():
        print(f"❌ Error: {md_path} not found.")
        return 1

    # --est/--no-est absent means "leave the marker as it is"; a --bb carrying its
    # own :EST suffix then decides on its own.
    bb_est = True if args.est else (False if args.no_est else None)

    result = edititem.edit_item(
        md_path,
        item_id=args.item_id,
        category=args.category,
        ean=args.ean,
        isbn=args.isbn,
        bb=args.bb,
        bb_est=bb_est,
        qty=args.qty,
        mass=args.mass,
        volume=args.volume,
        price=args.price,
        value=args.value,
        tags=args.tags,
        name=args.name,
        check_bb=not args.no_bb_check,
        strict=args.strict,
        lang=config.lang or "en",
        dry_run=args.dry_run,
        tingbok_url=config.tingbok_url,
    )

    for warning in result.warnings:
        print(f"⚠️  {warning}")

    if result.errors:
        for error in result.errors:
            print(f"❌ {error}")
        return 1

    verb = "Would edit" if args.dry_run else "Edited"
    where = f" in {result.container}" if result.container else ""
    print(f"{'🔎' if args.dry_run else '✅'} {verb} {args.item_id}{where}:")
    print(f"   - {result.before}")
    print(f"   + {result.after}")
    if not args.dry_run:
        print(f"   in {md_path}")
        print("Run 'inventory-md parse' to refresh inventory.json.")
    return 0


def move_item_command(args, config: Config) -> int:
    """Handle the `move` subcommand: relocate an item line to another container."""
    md_path = _resolve_md_path(args, config)

    if not md_path.exists():
        print(f"❌ Error: {md_path} not found.")
        return 1

    result = moveitem.move_item(
        md_path,
        item_id=args.item_id,
        container_id=args.container_id,
        dry_run=args.dry_run,
    )

    for warning in result.warnings:
        print(f"⚠️  {warning}")

    if result.errors:
        for error in result.errors:
            print(f"❌ {error}")
        return 1

    src = result.from_container or "?"
    if args.dry_run:
        print(f"🔎 Would move {args.item_id} from {src} to {args.container_id}:\n   {result.item_line}")
        return 0

    print(f"✅ Moved {args.item_id} from {src} to {args.container_id}:\n   {result.item_line}")
    print(f"   in {md_path}")
    print("Run 'inventory-md parse' to refresh inventory.json.")
    return 0


def shopping_list_command(args, config: Config) -> int:
    """Handle the shopping-list subcommand."""
    # Resolve inventory directory from config or CWD
    inventory_dir = Path.cwd()
    if config.inventory_file:
        inventory_dir = Path(config.inventory_file).resolve().parent

    inventory_json = inventory_dir / "inventory.json"
    if not inventory_json.exists():
        print(f"❌ Error: {inventory_json} not found. Run 'inventory-md parse' first.")
        return 1

    wanted_path = getattr(args, "wanted_items", None)
    if wanted_path is None:
        wanted_path = config.wanted_file
    if wanted_path is None:
        wanted_path = inventory_dir / "wanted-items.md"

    if not wanted_path.exists():
        print(f"❌ Error: {wanted_path} not found.")
        return 1

    include_dated = not getattr(args, "no_dated", False)
    lang = config.lang or "en"

    result = shopping_list.generate_shopping_list(
        wanted_path,
        inventory_json,
        include_dated=include_dated,
        lang=lang,
    )

    if getattr(args, "stdout", False):
        print(result)
    else:
        output_path = inventory_dir / "shopping-list.md"
        output_path.write_text(result, encoding="utf-8")
        # Print summary line from the result
        for line in result.splitlines():
            if line.startswith("**Summary:**"):
                print(f"🛒 {output_path} — {line.strip('*').strip()}")
                break
        else:
            print(f"🛒 Shopping list written to {output_path}")

    return 0


def _vocabulary_search_command(args, config: Config, directory: Path) -> int:
    """Implement 'vocabulary search <label>': find inventory items by category.

    Uses vocabulary.json (generated by parse) for hierarchy-aware matching,
    applying the same logic as the shopping list generator.
    """
    label = args.label
    output_json = getattr(args, "json", False)

    vocab_json = directory / "vocabulary.json"
    inventory_json = directory / "inventory.json"

    if not vocab_json.exists():
        print("No vocabulary.json found. Run 'inventory-md parse' first.")
        return 1

    if not inventory_json.exists():
        print("No inventory.json found. Run 'inventory-md parse' first.")
        return 1

    concepts = vocabulary.load_local_vocabulary(vocab_json)

    # Resolve label → canonical concept ID (same as shopping list does for desired items)
    canonical = vocabulary.resolve_category(label, concepts, config.lang or "en")
    if canonical is None:
        print(f"Category '{label}' not found in vocabulary.")
        return 0

    # Load inventory data
    with open(inventory_json, encoding="utf-8") as f:
        inventory_data = json.load(f)

    # Reuse shopping_list logic for DRY item resolution and matching
    inv_items = shopping_list.parse_inventory_for_shopping(inventory_data, concepts=concepts, lang=config.lang or "en")
    desired = shopping_list.DesiredItem(tag=canonical, description=label, section="")
    matches = shopping_list.find_matches(desired, inv_items, concepts)

    concept = concepts.get(canonical)
    concept_label = concept.prefLabel if concept else canonical

    if output_json:
        result = {
            "category": canonical,
            "label": concept_label,
            "count": len(matches),
            "items": [
                {
                    "id": m.item_id,
                    "description": m.description,
                    "tag": m.tag,
                    "qty": m.qty,
                    "location": m.location,
                }
                for m in matches
            ],
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif not matches:
        print(f"No items found for category '{label}' [{canonical}].")
    else:
        print(f"Items matching '{label}' [{canonical}]: {len(matches)}\n")
        for m in matches:
            qty_str = f" (qty: {m.qty:.4g})" if m.qty != 1.0 else ""
            loc_str = f"  @ {m.location}" if m.location else ""
            print(f"  {m.item_id or '?':20} {m.description}{qty_str}{loc_str}")

    return 0


def _ean_lookup(
    ean: str,
    inventory_json: Path,
    config: Config,
    use_tingbok: bool,
) -> dict:
    """Resolve one barcode: local inventory items first, then the tingbok record."""
    # Shop-local article numbers are not GTINs and have no check digit; only
    # validate what claims to be one.
    if ean.isdigit() and not barcodes.validate_ean_checksum(ean):
        print(f"Warning: {ean} has an invalid EAN/UPC checksum — mistyped?", file=sys.stderr)

    items = queries.find_by_ean(inventory_json, ean) if inventory_json.exists() else []

    product = None
    if use_tingbok and config.tingbok_url:
        cache_dir = Path.home() / ".cache" / "inventory-md" / "tingbok"
        try:
            product = vocabulary.lookup_ean_via_tingbok(ean, config.tingbok_url, cache_dir=cache_dir)
        except Exception as e:  # network/DNS/service trouble must not lose the local answer
            print(f"Warning: tingbok lookup failed for {ean}: {e}", file=sys.stderr)

    return {"ean": ean, "items": items, "product": product}


def _render_ean_lookup(entry: dict) -> str:
    """Render one :func:`_ean_lookup` result."""
    lines = [f"EAN {entry['ean']}"]

    items = entry["items"]
    if items:
        lines.append(f"  Inventory: {len(items)} item(s)")
        for item in items:
            loc = f"  @ {item['location']}" if item["location"] else ""
            lines.append(f"    {item['id'] or '?':24} {item['name']}{loc}")
            lines.append(f"    {'':24} {queries.bb_status(item['bb'])}")
    else:
        lines.append("  Inventory: no match")

    product = entry["product"]
    if product:
        lines.append(f"  tingbok: {product.get('name') or '(unnamed)'}")
        for label, key in (("Brand", "brand"), ("Quantity", "quantity"), ("Categories", "categories")):
            value = product.get(key)
            if not value:
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            lines.append(f"    {label}: {value}")
    else:
        lines.append("  tingbok: not found")

    return "\n".join(lines)


def ean_command(args, config: Config) -> int:
    """Implement ``inventory-md ean``.

    Returns 1 if any requested barcode was known neither locally nor to
    tingbok — a miss the caller has to act on, e.g. by reading the digits off
    the label again.
    """
    directory = Path(args.directory).resolve() if getattr(args, "directory", None) else Path.cwd()
    inventory_json = directory / "inventory.json"
    use_tingbok = not getattr(args, "no_tingbok", False)

    entries = [_ean_lookup(ean, inventory_json, config, use_tingbok) for ean in args.eans]

    if getattr(args, "json", False):
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(_render_ean_lookup(e) for e in entries))

    return 1 if any(not e["items"] and not e["product"] for e in entries) else 0


def _load_local_vocab(directory: Path) -> dict:
    """Load vocabulary.json from the given directory, or local-vocabulary.yaml/json as fallback."""
    vocab_json = directory / "vocabulary.json"
    if vocab_json.exists():
        return vocabulary.load_local_vocabulary(vocab_json)
    local_yaml = directory / "local-vocabulary.yaml"
    if local_yaml.exists():
        return vocabulary.load_local_vocabulary(local_yaml)
    local_json = directory / "local-vocabulary.json"
    if local_json.exists():
        return vocabulary.load_local_vocabulary(local_json)
    return {}


def vocabulary_command(args, config: Config) -> int:
    """Handle vocabulary subcommands."""
    directory = getattr(args, "directory", None)
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory).resolve()

    if args.vocab_command == "search":
        return _vocabulary_search_command(args, config, directory)

    # list/tree/lookup all work from local vocabulary.json only — no tingbok needed.
    vocab = _load_local_vocab(directory)

    if args.vocab_command == "list":
        output_json = getattr(args, "json", False)

        if not vocab:
            print("No vocabulary found. Run 'inventory-md parse' first.")
            return 1

        if output_json:
            tree = vocabulary.build_category_tree(vocab)
            print(json.dumps(tree.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"Vocabulary: {len(vocab)} concepts\n")
            for concept_id in sorted(vocab.keys()):
                concept = vocab[concept_id]
                all_alts = concept.get_all_alt_labels_flat()
                alt_str = f" (aka: {', '.join(all_alts)})" if all_alts else ""
                print(f"  {concept_id}: {concept.prefLabel}{alt_str}")

        return 0

    elif args.vocab_command == "tree":
        if not vocab:
            print("No vocabulary found. Run 'inventory-md parse' first.")
            return 1

        tree = vocabulary.build_category_tree(vocab)

        def print_tree(concept_id: str, indent: int = 0) -> None:
            concept = tree.concepts[concept_id]
            prefix = "  " * indent
            print(f"{prefix}{'▼' if concept.narrower else '○'} {concept.prefLabel} [{concept_id}]")
            for child_id in sorted(concept.narrower):
                if child_id in tree.concepts:
                    print_tree(child_id, indent + 1)

        print("Category Tree:\n")
        for root_id in tree.roots:
            print_tree(root_id)

        return 0

    elif args.vocab_command == "lookup":
        label = args.label
        concept = vocabulary.lookup_concept(label, vocab) if vocab else None

        if concept:
            print(f"Found: {concept.id}")
            print(f"  prefLabel: {concept.prefLabel}")
            all_alts = concept.get_all_alt_labels_flat()
            if all_alts:
                print(f"  altLabels: {', '.join(all_alts)}")
            if concept.broader:
                print(f"  broader: {', '.join(concept.broader)}")
            if concept.narrower:
                print(f"  narrower: {', '.join(concept.narrower)}")
            print(f"  source: {concept.source}")
            return 0

        # Not in local vocabulary — warn, then try tingbok if configured.
        if vocab:
            print(f"⚠️  '{label}' not found in local vocabulary.json (run 'parse' to update).")
        else:
            print("⚠️  No local vocabulary found. Run 'inventory-md parse' first.")

        if not config.tingbok_url:
            return 1

        lang = getattr(args, "lang", None) or config.lang or "en"
        print(f"Querying tingbok for '{label}' (lang={lang}) ...")
        try:
            resolved, _ = vocabulary.enrich_categories_via_lookup(
                [label],
                tingbok_url=config.tingbok_url,
                lang=lang,
                verbose=True,  # interactive single-label lookup: show the progress line
            )
        except Exception as e:
            print(f"Tingbok lookup failed: {e}")
            return 1

        if not resolved:
            print("Not found in tingbok either.")
            return 1

        # Show the most specific concept returned (the one matching the label)
        concept = resolved.get(label.lower()) or next(iter(resolved.values()))
        print(f"\nTingbok result: {concept.id}")
        print(f"  prefLabel: {concept.prefLabel}")
        all_alts = concept.get_all_alt_labels_flat()
        if all_alts:
            print(f"  altLabels: {', '.join(all_alts)}")
        if concept.broader:
            print(f"  broader: {', '.join(concept.broader)}")
        if concept.narrower:
            print(f"  narrower: {', '.join(concept.narrower)}")
        return 1  # still not in local vocabulary; exit 1 signals incomplete data

    else:
        # No subcommand - show help
        print("Local vocabulary management")
        print("\nSubcommands:")
        print("  list    List all concepts in vocabulary")
        print("  lookup  Look up a concept by label")
        print("  tree    Show category hierarchy as tree")
        print("  search  Find inventory items by category (including children)")
        print("\nUse 'inventory-md vocabulary <command> --help' for more info")
        return 1


if __name__ == "__main__":
    sys.exit(main())
