#!/usr/bin/env python3
"""
Inventory System Parser

Parses markdown inventory files into structured JSON data.
Supports hierarchical organization, metadata tags, and image references.
"""
import re
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any


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

                # Create a top-level container
                result['containers'].append({
                    'id': container_id,
                    'parent': None,  # Top-level containers have no parent
                    'heading': heading,
                    'description': '',
                    'items': [],
                    'images': [],
                    'photos_link': ''
                })
            i += 1
            continue

        elif line.startswith('# Oversikt over'):
            # Section header without ID - just skip it
            i += 1
            continue

        # Container entries (## headings - could be towers, boxes, shelves, etc.)
        elif line.startswith('## '):
            # Parse container heading
            heading = line[3:].strip()

            # Extract metadata (ID, parent, etc.) from heading
            parsed = extract_metadata(heading)

            # Get container ID - either from metadata or first word
            container_id = parsed['metadata'].get('id') or (heading.split()[0] if heading else 'Unknown')

            # Track this section ID for parent inference
            current_section_id = container_id

            # Infer parent from top-level section if not explicit and not already inferred
            parent_id = parsed['metadata'].get('parent')
            if not parent_id and current_top_level_id and container_id != current_top_level_id:
                # Only infer if we don't already have a parent for this container
                if container_id not in inferred_parents:
                    inferred_parents[container_id] = current_top_level_id

            current_container = {
                'id': container_id,
                'parent': parent_id,
                'heading': heading,
                'description': '',
                'items': [],
                'images': [],
                'photos_link': ''
            }

            i += 1

            # Collect container contents
            while i < len(lines) and not lines[i].startswith('#'):
                line_content = lines[i]

                if line_content.startswith('!['):
                    # Image
                    match = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line_content)
                    if match:
                        thumb_src = match.group(2)
                        # Convert resized path to full resolution path
                        full_src = thumb_src.replace('resized/', 'photos/')
                        current_container['images'].append({
                            'alt': match.group(1),
                            'thumb': thumb_src,
                            'full': full_src
                        })
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
                elif line_content.startswith('[Fotos'):
                    # Link to full resolution photos
                    match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', line_content)
                    if match:
                        current_container['photos_link'] = match.group(2)
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
