#!/usr/bin/env python3
"""
Inventory System Parser

Parses markdown inventory files into structured JSON data.
Supports hierarchical organization, metadata tags, and automatic image discovery.
Automatically creates resized thumbnails when missing.
"""
import re
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
import os
import sys


def create_thumbnail(source_path: Path, dest_path: Path, max_size: int = 800) -> bool:
    """
    Create a resized thumbnail from a source image.

    Args:
        source_path: Path to source image
        dest_path: Path to save thumbnail
        max_size: Maximum width or height in pixels

    Returns:
        True if thumbnail was created, False otherwise
    """
    try:
        from PIL import Image
    except ImportError:
        print("⚠️  Pillow not installed. Run: pip install Pillow", file=sys.stderr)
        return False

    try:
        # Open and resize image
        with Image.open(source_path) as img:
            # Convert RGBA to RGB if needed (for JPEG)
            if img.mode == 'RGBA':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[3])
                img = rgb_img

            # Calculate new size maintaining aspect ratio
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # Ensure destination directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Save thumbnail
            img.save(dest_path, quality=85, optimize=True)
            return True
    except Exception as e:
        print(f"⚠️  Failed to resize {source_path.name}: {e}", file=sys.stderr)
        return False


def discover_images(container_id: str, base_path: Path) -> List[Dict[str, str]]:
    """
    Automatically discover images for a container from filesystem.

    Looks for images in:
    - photos/{container_id}/*.{jpg,jpeg,png,gif}
    - resized/{container_id}/*.{jpg,jpeg,png,gif}

    Automatically creates missing thumbnails from photos directory.

    Returns list of image dicts with 'alt', 'thumb', and 'full' keys.
    """
    images = []

    # Image extensions to look for
    extensions = ('.jpg', '.jpeg', '.png', '.gif', '.JPG', '.JPEG', '.PNG', '.GIF')

    # First, scan photos directory to find all source images
    photos_dir = base_path / 'photos' / container_id
    resized_dir = base_path / 'resized' / container_id

    if not photos_dir.exists() or not photos_dir.is_dir():
        # No photos directory - nothing to discover
        return images

    # Get all image files from photos directory, sorted by name
    photo_files = sorted([
        f for f in photos_dir.iterdir()
        if f.is_file() and f.name.endswith(extensions)
    ])

    # Track thumbnails created
    thumbnails_created = 0

    for photo_file in photo_files:
        # Check if thumbnail exists
        thumb_file = resized_dir / photo_file.name

        if not thumb_file.exists():
            # Create missing thumbnail
            if create_thumbnail(photo_file, thumb_file):
                thumbnails_created += 1

        # Add to images list
        thumb_path = f'resized/{container_id}/{photo_file.name}'
        full_path = f'photos/{container_id}/{photo_file.name}'
        alt_text = f'{container_id}/{photo_file.name}'

        images.append({
            'alt': alt_text,
            'thumb': thumb_path,
            'full': full_path
        })

    # Report thumbnail creation
    if thumbnails_created > 0:
        print(f"  ✓ Created {thumbnails_created} thumbnail(s) for {container_id}", file=sys.stderr)

    return images


def extract_metadata(text: str) -> Dict[str, Any]:
    """
    Extract all key:value pairs from text.

    Patterns:
    - key:value (space-separated)
    - (key:value) (parenthesized)
    - Special handling for tags: tag:value1,value2,value3 becomes ["value1", "value2", "value3"]

    Returns: {
        "metadata": {"id": "...", "parent": "...", "type": "...", "tags": [...]},
        "name": "remaining text after extraction"
    }
    """
    metadata = {}
    tags = []
    remaining = text

    # Match key:value patterns (with or without parentheses)
    # Pattern matches: key:value or (key:value)
    pattern = r'\(?(\w+):([^)\s]+)\)?'

    matches = []
    for match in re.finditer(pattern, text):
        key = match.group(1).lower()
        value = match.group(2).strip()

        # Special handling for tags: split by comma
        if key == 'tag':
            tags.extend([tag.strip() for tag in value.split(',') if tag.strip()])
        else:
            metadata[key] = value
        matches.append(match)

    # Add tags to metadata if any were found
    if tags:
        metadata['tags'] = tags

    # Remove matched patterns from text to get clean name
    # Go in reverse to maintain positions
    for match in reversed(matches):
        remaining = remaining[:match.start()] + remaining[match.end():]

    # Clean up extra spaces
    remaining = re.sub(r'\s+', ' ', remaining).strip()

    return {
        "metadata": metadata,
        "name": remaining
    }


def parse_inventory(md_file: Path) -> Dict[str, Any]:
    """
    Parse the markdown inventory file into structured data.

    Returns:
        {
            'intro': str,
            'numbering_scheme': str,
            'containers': [...]
        }
    """
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        'intro': '',
        'numbering_scheme': '',
        'containers': []
    }

    # Track inferred parent relationships from section listings
    inferred_parents = {}  # container_id -> parent_id

    lines = content.split('\n')
    i = 0
    current_section = None
    current_container = None
    current_section_id = None  # Track current section ID for parent inference
    current_top_level_id = None  # Track top-level section (e.g., ID:Garasje)

    # Track heading hierarchy for automatic parent inference
    # heading_stack[level] = container_id at that heading level
    heading_stack = {}  # level -> container_id

    while i < len(lines):
        line = lines[i]

        # Main sections
        if line.startswith('# Intro'):
            current_section = 'intro'
            i += 1
            intro_lines = []
            while i < len(lines) and not lines[i].startswith('# '):
                intro_lines.append(lines[i])
                i += 1
            result['intro'] = '\n'.join(intro_lines).strip()
            continue

        elif line.startswith('# Nummereringsregime'):
            current_section = 'numbering'
            i += 1
            num_lines = []
            while i < len(lines) and not lines[i].startswith('# '):
                num_lines.append(lines[i])
                i += 1
            result['numbering_scheme'] = '\n'.join(num_lines).strip()
            continue

        elif line.startswith('# ID:') or (line.startswith('# Oversikt over') and 'ID:' in line):
            # Top-level container section (e.g., ID:Garasje, ID:Loft)
            heading = line[2:].strip()  # Remove '# '
            parsed = extract_metadata(heading)

            if parsed['metadata'].get('id'):
                container_id = parsed['metadata']['id']
                current_top_level_id = container_id

                # Update heading stack for H1 level
                heading_stack = {1: container_id}

                # Create a top-level container
                current_container = {
                    'id': container_id,
                    'parent': None,  # Top-level containers have no parent
                    'heading': parsed['name'],  # Use cleaned name without metadata markers
                    'description': '',
                    'items': [],
                    'images': [],
                    'photos_link': '',
                    'metadata': parsed['metadata']
                }

                i += 1

                # Collect container contents (same as for ## headings)
                while i < len(lines) and not lines[i].startswith('#'):
                    line_content = lines[i]

                    # Skip image lines
                    if line_content.startswith('!['):
                        i += 1
                        continue
                    elif line_content.startswith('* '):
                        # Item
                        item_text = line_content[2:].strip()
                        parsed_item = extract_metadata(item_text)

                        # If this item has an ID, infer parent relationship
                        if parsed_item['metadata'].get('id'):
                            item_id = parsed_item['metadata']['id']
                            if container_id and item_id != container_id:
                                inferred_parents[item_id] = container_id

                        current_container['items'].append({
                            'name': parsed_item['name'],
                            'raw_text': item_text,
                            'metadata': parsed_item['metadata'],
                            'indented': False
                        })
                    elif line_content.strip() and not line_content.startswith('#'):
                        # Description line
                        if not current_container['description']:
                            current_container['description'] = line_content.strip()
                        else:
                            current_container['description'] += ' ' + line_content.strip()

                    i += 1

                result['containers'].append(current_container)
            else:
                i += 1
            continue

        elif line.startswith('# ') and not line.startswith('## '):
            # Generic H1 heading (not ID: or Intro/Nummereringsregime)
            # Use as top-level container if not special section
            if not (line.startswith('# Intro') or line.startswith('# Nummereringsregime')):
                heading = line[2:].strip()  # Remove '# '
                parsed = extract_metadata(heading)

                # Generate container ID from heading
                if parsed['metadata'].get('id'):
                    container_id = parsed['metadata']['id']
                else:
                    # Sanitize heading to create ID
                    clean_heading = parsed['name'] if parsed['name'] else heading
                    import re
                    sanitized = re.sub(r'[^\w\s-]', '', clean_heading)
                    sanitized = re.sub(r'\s+', '-', sanitized.strip())
                    container_id = sanitized[:50] if sanitized else 'Container-1'

                current_top_level_id = container_id

                # Update heading stack for H1 level
                heading_stack = {1: container_id}

                # Create a top-level container
                current_container = {
                    'id': container_id,
                    'parent': None,
                    'heading': parsed['name'],  # Use cleaned name without metadata markers
                    'description': '',
                    'items': [],
                    'images': [],
                    'photos_link': '',
                    'metadata': parsed['metadata']
                }

                i += 1

                # Collect container contents (same as for ## headings)
                while i < len(lines) and not lines[i].startswith('#'):
                    line_content = lines[i]

                    # Skip image lines
                    if line_content.startswith('!['):
                        i += 1
                        continue
                    elif line_content.startswith('* '):
                        # Item
                        item_text = line_content[2:].strip()
                        parsed_item = extract_metadata(item_text)

                        # If this item has an ID, infer parent relationship
                        if parsed_item['metadata'].get('id'):
                            item_id = parsed_item['metadata']['id']
                            if container_id and item_id != container_id:
                                inferred_parents[item_id] = container_id

                        current_container['items'].append({
                            'name': parsed_item['name'],
                            'raw_text': item_text,
                            'metadata': parsed_item['metadata'],
                            'indented': False
                        })
                    elif line_content.strip() and not line_content.startswith('#'):
                        # Description line
                        if not current_container['description']:
                            current_container['description'] = line_content.strip()
                        else:
                            current_container['description'] += ' ' + line_content.strip()

                    i += 1

                result['containers'].append(current_container)
                continue

        elif line.startswith('# Oversikt over'):
            # Section header without ID - just skip it
            i += 1
            continue

        # Container entries (##, ###, ####, etc. - could be towers, boxes, shelves, locations, etc.)
        elif line.startswith('##') and not line.startswith('#' * 7):  # Support up to H6 (######)
            # Determine heading level (## = 2, ### = 3, etc.)
            heading_level = len(line) - len(line.lstrip('#'))
            heading = line[heading_level:].strip()

            # Extract metadata (ID, parent, etc.) from heading
            parsed = extract_metadata(heading)

            # Get container ID - either from metadata or generate from heading text
            if parsed['metadata'].get('id'):
                container_id = parsed['metadata']['id']
            else:
                # Generate ID from heading text
                # Remove metadata markers and clean the text
                clean_heading = parsed['name'] if parsed['name'] else heading

                # Sanitize: remove special chars, replace spaces with hyphens
                import re
                sanitized = re.sub(r'[^\w\s-]', '', clean_heading)
                sanitized = re.sub(r'\s+', '-', sanitized.strip())

                # Limit length and ensure it's not empty
                container_id = sanitized[:50] if sanitized else f'Container-{heading_level}'

            # Track this section ID for parent inference
            current_section_id = container_id

            # Infer parent from heading hierarchy
            # BUT: Don't overwrite if already inferred from explicit item listing
            parent_id = parsed['metadata'].get('parent')
            if not parent_id:
                # Check if already inferred from explicit item listing (takes precedence)
                if container_id in inferred_parents:
                    parent_id = inferred_parents[container_id]
                else:
                    # Look for parent in heading stack (one level up)
                    parent_level = heading_level - 1
                    if parent_level in heading_stack:
                        parent_id = heading_stack[parent_level]
                        inferred_parents[container_id] = parent_id
                    elif parent_level == 1 and current_top_level_id and container_id != current_top_level_id:
                        # Fallback to top-level section for H2 headings
                        inferred_parents[container_id] = current_top_level_id
                        parent_id = current_top_level_id

            # Update heading stack - clear all deeper levels
            heading_stack = {k: v for k, v in heading_stack.items() if k < heading_level}
            heading_stack[heading_level] = container_id

            current_container = {
                'id': container_id,
                'parent': parent_id,
                'heading': parsed['name'],  # Use cleaned name without metadata markers
                'description': '',
                'items': [],
                'images': [],
                'photos_link': '',
                'metadata': parsed['metadata']
            }

            i += 1

            # Collect container contents
            while i < len(lines) and not lines[i].startswith('#'):
                line_content = lines[i]

                # Skip image lines - images will be discovered from filesystem
                if line_content.startswith('!['):
                    i += 1
                    continue
                elif line_content.startswith('* '):
                    # Item - can be nested
                    item_text = line_content[2:].strip()
                    parsed = extract_metadata(item_text)

                    # If this item has an ID and we're in a section, infer parent relationship
                    if parsed['metadata'].get('id') and current_section_id:
                        item_id = parsed['metadata']['id']
                        inferred_parents[item_id] = current_section_id

                    current_container['items'].append({
                        'id': parsed['metadata'].get('id'),
                        'parent': parsed['metadata'].get('parent'),
                        'name': parsed['name'],
                        'raw_text': item_text,
                        'metadata': parsed['metadata']
                    })
                elif line_content.startswith('  * '):
                    # Nested item
                    item_text = line_content[4:].strip()
                    parsed = extract_metadata(item_text)
                    current_container['items'].append({
                        'id': parsed['metadata'].get('id'),
                        'parent': parsed['metadata'].get('parent'),
                        'name': parsed['name'],
                        'raw_text': item_text,
                        'metadata': parsed['metadata'],
                        'indented': True
                    })
                elif line_content.strip() and not line_content.startswith('#'):
                    # Description line
                    if not current_container['description']:
                        current_container['description'] = line_content.strip()
                    else:
                        current_container['description'] += ' ' + line_content.strip()

                i += 1

                # Break if we hit the next section
                if i >= len(lines):
                    break

            result['containers'].append(current_container)
            current_container = None
            continue

        i += 1

    # Apply inferred parent relationships to containers that don't have explicit parents
    for container in result['containers']:
        if not container.get('parent') and container['id'] in inferred_parents:
            container['parent'] = inferred_parents[container['id']]

    # Discover images from filesystem for each container
    base_path = md_file.parent  # Directory containing the markdown file
    for container in result['containers']:
        container_id = container.get('id')
        if container_id:
            # Check for photo directory override in metadata or photos_link
            # Priority: 1) photos metadata, 2) photos_link, 3) container_id
            photo_dir = None

            # Check metadata for photos field
            if container.get('metadata') and container['metadata'].get('photos'):
                photo_dir = container['metadata']['photos']

            # Fall back to photos_link (legacy support)
            if not photo_dir:
                photos_link = container.get('photos_link', '')
                if photos_link:
                    # Extract directory name from photos_link (e.g., "photos/A89" -> "A89")
                    photo_dir = photos_link.replace('photos/', '').strip('/')

            # Fall back to container_id
            if not photo_dir:
                photo_dir = container_id

            # Auto-discover images from photos/resized directories
            discovered_images = discover_images(photo_dir, base_path)
            container['images'] = discovered_images

    return result


def add_container_id_prefixes(md_file: Path) -> Tuple[int, Dict[str, List[str]]]:
    """
    Add ID: prefix to all container headers and handle duplicates.

    Returns: (num_changes, duplicate_map)
    """
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # First pass: collect all container IDs and detect duplicates
    container_ids = defaultdict(list)
    container_lines = []
    in_intro_section = False

    for i, line in enumerate(lines):
        # Track if we're in the Intro or Nummereringsregime sections
        if line.startswith('# Intro') or line.startswith('# Nummereringsregime'):
            in_intro_section = True
            continue
        elif line.startswith('# ') and not line.startswith('## '):
            in_intro_section = False

        if line.startswith('## ') and not line.startswith('### '):
            # Skip subsections within intro/numbering sections
            if in_intro_section:
                continue

            # Skip location sections
            if 'Oversikt over ting lagret' in line or 'Oversikt over boksene' in line:
                continue

            heading = line[3:].strip()
            parsed = extract_metadata(heading)

            # If already has ID:, use that
            if parsed['metadata'].get('id'):
                container_id = parsed['metadata']['id']
            else:
                # Extract container ID from heading (first word usually)
                # Patterns: "Box 9", "A23", "C12", "H5", "Seb1", etc.
                match = re.match(r'^([A-Z]\d+|Box \d+|[A-Z]{1,3}\d+|Seb\d+|[A-Za-z]+\d*)', heading)
                if match:
                    container_id = match.group(1).replace(' ', '')  # "Box 9" -> "Box9"
                else:
                    container_id = None

            if container_id:
                container_ids[container_id].append(i)
                container_lines.append((i, container_id, heading))

    # Second pass: update lines with ID: prefix and handle duplicates
    changes = 0
    duplicate_map = {}

    for line_num, container_id, heading in container_lines:
        parsed = extract_metadata(heading)

        # Check if this container ID is duplicated
        if len(container_ids[container_id]) > 1:
            # Find which occurrence this is
            occurrence = container_ids[container_id].index(line_num) + 1
            unique_id = f"{container_id}-{occurrence}"
            duplicate_map[container_id] = duplicate_map.get(container_id, []) + [unique_id]
        else:
            unique_id = container_id

        # Add ID: prefix if not already present
        if not parsed['metadata'].get('id'):
            new_heading = f"## ID:{unique_id} {heading}\n"
            lines[line_num] = new_heading
            changes += 1

    # Write back if there were changes
    if changes > 0:
        with open(md_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    return changes, duplicate_map


def validate_inventory(data: Dict[str, Any]) -> List[str]:
    """
    Validate inventory data and return list of issues.
    """
    issues = []

    # Build ID map of containers only (items with IDs are just references to containers)
    id_map = {}
    containers_with_parents = defaultdict(list)  # container_id -> list of parents

    # Collect all containers
    for container in data.get('containers', []):
        if container.get('id'):
            if container['id'] in id_map:
                issues.append(f"⚠️  Duplicate container ID: {container['id']}")
            id_map[container['id']] = container

            # Track if this container has a parent
            if container.get('parent'):
                containers_with_parents[container['id']].append(container['parent'])

    # Check for containers with multiple parents
    for container_id, parents in containers_with_parents.items():
        if len(parents) > 1:
            unique_parents = list(set(parents))
            if len(unique_parents) > 1:
                issues.append(f"⚠️  {container_id} has multiple parents: {', '.join(unique_parents)}")

    # Check parent references exist
    for container in data.get('containers', []):
        if container.get('parent') and container['parent'] not in id_map:
            issues.append(f"❌ {container['id']}: parent '{container['parent']}' not found")

    # Note: Items with IDs that don't have container sections are fine - they're just references
    # We don't validate this as it's normal to reference containers before they're detailed

    return issues


def save_json(data: Dict[str, Any], output_file: Path) -> None:
    """Save inventory data to JSON file."""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(json_file: Path) -> Dict[str, Any]:
    """Load inventory data from JSON file."""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_photo_listings(base_path: Path) -> Tuple[int, int]:
    """
    Generate photo directory listings for backup purposes.

    Scans photos/* directories and creates photo-listings/{container_id}.txt
    files containing lists of photo filenames (not paths, just filenames).

    Args:
        base_path: Base directory containing photos/ folder

    Returns:
        Tuple of (containers_processed, files_created)
    """
    photos_dir = base_path / 'photos'
    listings_dir = base_path / 'photo-listings'

    if not photos_dir.exists():
        print(f"⚠️  No photos directory found at {photos_dir}")
        return 0, 0

    # Create listings directory if needed
    listings_dir.mkdir(exist_ok=True)

    containers_processed = 0
    files_created = 0

    # Image extensions to look for
    extensions = ('.jpg', '.jpeg', '.png', '.gif', '.JPG', '.JPEG', '.PNG', '.GIF')

    # Process each subdirectory in photos/
    for container_dir in sorted(photos_dir.iterdir()):
        if not container_dir.is_dir():
            continue

        container_id = container_dir.name

        # Get all image files, sorted by name
        photo_files = sorted([
            f.name for f in container_dir.iterdir()
            if f.is_file() and f.name.endswith(extensions)
        ])

        if not photo_files:
            # Skip empty directories
            continue

        # Write listing file
        listing_file = listings_dir / f"{container_id}.txt"
        with open(listing_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(photo_files) + '\n')

        containers_processed += 1
        files_created += 1

    return containers_processed, files_created
