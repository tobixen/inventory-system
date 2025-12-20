#!/usr/bin/env python3
"""
FastAPI server for inventory chatbot with Claude integration.

Provides conversational interface for querying inventory.
"""
import os
import json
from pathlib import Path
from typing import Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import shutil


# Global inventory data
inventory_data: Optional[dict] = None
inventory_path: Optional[Path] = None
aliases: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load inventory and aliases on startup."""
    global inventory_data, inventory_path, aliases

    # Look for inventory.json in current directory
    inventory_path = Path.cwd() / "inventory.json"
    if not inventory_path.exists():
        print(f"⚠️  Warning: inventory.json not found at {inventory_path}")
        print("   Server will start but chatbot won't work until inventory.json is available")
    else:
        with open(inventory_path, 'r', encoding='utf-8') as f:
            inventory_data = json.load(f)
        print(f"✅ Loaded inventory: {len(inventory_data.get('containers', []))} containers")

    # Load aliases
    aliases_path = Path.cwd() / "aliases.json"
    if aliases_path.exists():
        with open(aliases_path, 'r', encoding='utf-8') as f:
            aliases = json.load(f)
        print(f"✅ Loaded {len(aliases)} search aliases")
    else:
        print(f"⚠️  aliases.json not found, search aliases disabled")
        aliases = {}

    yield

    # Cleanup
    inventory_data = None


app = FastAPI(title="Inventory Chatbot Server", lifespan=lifespan)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    """Chat message from user."""
    message: str
    conversation_id: Optional[str] = None
    model: str = "claude-3-haiku-20240307"  # Default to cheapest model


class ChatResponse(BaseModel):
    """Chat response from Claude."""
    response: str
    conversation_id: str


# Tool definitions for Claude
INVENTORY_TOOLS = [
    {
        "name": "search_inventory",
        "description": "Search the inventory for items, containers, or content matching a query. Returns relevant containers and items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - can be item name, container ID, tag, or description text"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_container",
        "description": "Get detailed information about a specific container by its ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "The container ID (e.g., 'A23', 'H11', 'Box5')"
                }
            },
            "required": ["container_id"]
        }
    },
    {
        "name": "list_containers",
        "description": "List all containers, optionally filtered by location/parent, tags, or prefix",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent": {
                    "type": "string",
                    "description": "Filter by parent location (e.g., 'Garasje', 'Loft')"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (e.g., ['winter', 'sport'])"
                },
                "prefix": {
                    "type": "string",
                    "description": "Filter by container ID prefix (e.g., 'A', 'H', 'C')"
                }
            }
        }
    },
    {
        "name": "add_item",
        "description": "Add a new item to a specific container. This modifies the inventory permanently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "The container ID to add the item to (e.g., 'A23', 'H11')"
                },
                "item_description": {
                    "type": "string",
                    "description": "Description of the item to add"
                },
                "tags": {
                    "type": "string",
                    "description": "Optional comma-separated tags (e.g., 'elektronikk,hjem')"
                }
            },
            "required": ["container_id", "item_description"]
        }
    },
    {
        "name": "remove_item",
        "description": "Remove an item from a container. This modifies the inventory permanently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "The container ID to remove the item from"
                },
                "item_description": {
                    "type": "string",
                    "description": "Description of the item to remove (or part of it)"
                }
            },
            "required": ["container_id", "item_description"]
        }
    },
    {
        "name": "add_todo",
        "description": "Add a change request or task to TODO.md. Use this when a request is too complex to handle directly or requires manual intervention (e.g., moving photos, reorganizing containers, complex metadata changes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Detailed description of the task or change request"
                },
                "priority": {
                    "type": "string",
                    "description": "Priority level: low, medium, or high",
                    "enum": ["low", "medium", "high"]
                }
            },
            "required": ["task_description"]
        }
    }
]


def expand_query_with_aliases(query: str) -> list[str]:
    """Expand query with aliases. Returns list of search terms including query and all aliases."""
    if not aliases:
        return [query]

    query_lower = query.lower()
    search_terms = [query_lower]

    # Check if query matches any alias key
    if query_lower in aliases:
        search_terms.extend([a.lower() for a in aliases[query_lower]])

    return list(set(search_terms))  # Remove duplicates


def search_inventory(query: str) -> dict:
    """Search inventory for matching containers and items."""
    if not inventory_data:
        return {"error": "Inventory not loaded"}

    # Expand query with aliases
    search_terms = expand_query_with_aliases(query)

    results = {
        "matching_containers": [],
        "matching_items": []
    }

    for container in inventory_data.get('containers', []):
        container_match = False

        # Check container ID, heading, description with all search terms
        for term in search_terms:
            if (term in container.get('id', '').lower() or
                term in container.get('heading', '').lower() or
                term in container.get('description', '').lower()):
                container_match = True
                break

        # Check tags
        if not container_match and container.get('metadata', {}).get('tags'):
            for tag in container['metadata']['tags']:
                for term in search_terms:
                    if term in tag.lower():
                        container_match = True
                        break
                if container_match:
                    break

        # Check items
        matching_items_in_container = []
        for item in container.get('items', []):
            item_text = item.get('name', '') or item.get('raw_text', '')
            for term in search_terms:
                if term in item_text.lower():
                    matching_items_in_container.append(item_text)
                    container_match = True
                    break  # Don't add same item multiple times

        if container_match:
            results['matching_containers'].append({
                'id': container.get('id'),
                'heading': container.get('heading'),
                'parent': container.get('parent'),
                'description': container.get('description'),
                'tags': container.get('metadata', {}).get('tags', []),
                'item_count': len(container.get('items', [])),
                'image_count': len(container.get('images', [])),
                'matching_items': matching_items_in_container[:5]  # Limit to 5
            })

    return results


def get_container(container_id: str) -> dict:
    """Get detailed information about a container."""
    if not inventory_data:
        return {"error": "Inventory not loaded"}

    for container in inventory_data.get('containers', []):
        if container.get('id', '').lower() == container_id.lower():
            # Return full container info
            return {
                'id': container.get('id'),
                'heading': container.get('heading'),
                'parent': container.get('parent'),
                'description': container.get('description'),
                'metadata': container.get('metadata', {}),
                'items': [item.get('name') or item.get('raw_text') for item in container.get('items', [])],
                'image_count': len(container.get('images', [])),
                'images': container.get('images', [])[:3]  # First 3 images
            }

    return {"error": f"Container '{container_id}' not found"}


def list_containers(parent: Optional[str] = None, tags: Optional[list] = None, prefix: Optional[str] = None) -> dict:
    """List containers with optional filters."""
    if not inventory_data:
        return {"error": "Inventory not loaded"}

    containers = []

    for container in inventory_data.get('containers', []):
        # Apply filters
        if parent:
            container_parent = container.get('parent') or ''
            if container_parent.lower() != parent.lower():
                continue

        if prefix and not (container.get('id') or '').startswith(prefix):
            continue

        if tags:
            container_tags = container.get('metadata', {}).get('tags', [])
            if not any(tag.lower() in [t.lower() for t in container_tags] for tag in tags):
                continue

        containers.append({
            'id': container.get('id'),
            'heading': container.get('heading'),
            'parent': container.get('parent'),
            'tags': container.get('metadata', {}).get('tags', []),
            'item_count': len(container.get('items', [])),
            'image_count': len(container.get('images', []))
        })

    return {
        'count': len(containers),
        'containers': containers[:50]  # Limit to 50
    }


def reload_inventory() -> bool:
    """Reload inventory.json after markdown changes."""
    global inventory_data

    if not inventory_path or not inventory_path.exists():
        return False

    try:
        with open(inventory_path, 'r', encoding='utf-8') as f:
            inventory_data = json.load(f)
        return True
    except Exception as e:
        print(f"❌ Error reloading inventory: {e}")
        return False


def git_commit(message: str) -> bool:
    """Create a git commit for inventory changes."""
    if not inventory_path:
        return False

    import subprocess
    import pwd

    try:
        inventory_dir = inventory_path.parent
        current_uid = os.getuid()
        current_user = pwd.getpwuid(current_uid).pw_name

        # Get the owner of the inventory directory
        stat_info = os.stat(inventory_dir)
        owner_uid = stat_info.st_uid
        owner_name = pwd.getpwuid(owner_uid).pw_name

        # Check if we're running as a different user than the directory owner
        if current_uid != owner_uid:
            # Configure git safe.directory for this directory
            try:
                subprocess.run(
                    ['git', 'config', '--global', '--add', 'safe.directory', str(inventory_dir)],
                    check=True,
                    capture_output=True
                )
                print(f"ℹ️  Added {inventory_dir} to git safe.directory for {current_user}")
            except:
                pass  # May already be added

        # Add all changes (inventory.md, inventory.json, photo-listings/, photos/)
        subprocess.run(
            ['git', 'add', 'inventory.md', 'inventory.json', 'photo-listings/', 'photos/'],
            cwd=inventory_dir,
            check=True,
            capture_output=True
        )

        # Commit with message
        subprocess.run(
            ['git', 'commit', '-m', message],
            cwd=inventory_dir,
            check=True,
            capture_output=True
        )

        print(f"✅ Git commit: {message}")
        return True

    except subprocess.CalledProcessError as e:
        # Ignore errors (e.g., no changes to commit)
        stderr = e.stderr.decode() if e.stderr else 'no changes'
        if 'nothing to commit' not in stderr and 'dubious ownership' not in stderr:
            print(f"ℹ️  Git commit skipped: {stderr}")
        return False
    except Exception as e:
        print(f"⚠️  Git commit failed: {e}")
        return False


def add_child_to_item(container_id: str, parent_item: str, child_description: str) -> dict:
    """Add a child item to a parent item, promoting the parent to a container if needed."""
    if not inventory_path:
        return {"error": "Inventory path not set"}

    markdown_path = inventory_path.parent / "inventory.md"
    if not markdown_path.exists():
        return {"error": "inventory.md not found"}

    try:
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Find the parent container
        container_line_idx = None
        container_level = None
        for i, line in enumerate(lines):
            if (line.startswith('# ') or line.startswith('## ')) and f'ID:{container_id}' in line:
                container_line_idx = i
                container_level = '#' if line.startswith('# ') else '##'
                break

        if container_line_idx is None:
            return {"error": f"Container ID:{container_id} not found"}

        # Check if parent item already exists as a container (heading)
        parent_id = None
        parent_container_idx = None

        # Look for parent as a heading first
        for i in range(container_line_idx + 1, len(lines)):
            # Stop at next heading of same or higher level
            if container_level == '#' and lines[i].startswith('# '):
                break
            elif container_level == '##' and (lines[i].startswith('# ') or lines[i].startswith('## ')):
                break

            # Check if this heading matches the parent item
            if lines[i].startswith('## ') and parent_item.lower() in lines[i].lower():
                parent_container_idx = i
                # Extract ID from heading
                if 'ID:' in lines[i]:
                    parent_id = lines[i].split('ID:')[1].split()[0]
                break

        # If parent not found as heading, look for it as a bullet item
        parent_bullet_idx = None
        if parent_container_idx is None:
            for i in range(container_line_idx + 1, len(lines)):
                # Stop at next heading
                if container_level == '#' and lines[i].startswith('# '):
                    break
                elif container_level == '##' and (lines[i].startswith('# ') or lines[i].startswith('## ')):
                    break

                if lines[i].startswith('* ') and parent_item.lower() in lines[i].lower():
                    parent_bullet_idx = i
                    break

        # Case 1: Parent is already a container (has heading)
        if parent_container_idx is not None:
            # Simply add child to this container
            result = add_item_to_container(parent_id, child_description, None)
            if "error" in result:
                return result
            return {
                "success": True,
                "message": f"Added child '{child_description}' to {parent_id}",
                "promoted": False
            }

        # Case 2: Parent is a bullet item - need to promote it
        if parent_bullet_idx is not None:
            # Extract or generate ID from parent item
            parent_text = lines[parent_bullet_idx].strip()[2:]  # Remove "* "

            # Try to extract ID from the item text (e.g., "ID:D01 - description")
            if 'ID:' in parent_text or 'id:' in parent_text.lower():
                # Extract ID
                import re
                match = re.search(r'[Ii][Dd]:(\S+)', parent_text)
                if match:
                    parent_id = match.group(1)
                    # Remove ID: prefix from description
                    parent_desc = re.sub(r'[Ii][Dd]:\S+\s*-?\s*', '', parent_text).strip()
                else:
                    # Generate ID from first word
                    parent_id = parent_text.split()[0] if parent_text else 'Item'
                    parent_desc = parent_text
            else:
                # Generate ID from first word or first few characters
                parent_id = parent_text.split()[0][:10] if parent_text else 'Item'
                parent_desc = parent_text

            # Create new heading for promoted parent
            new_heading = f"## ID:{parent_id} {parent_desc}\n"
            new_child_item = f"* {child_description}\n"

            # Insert new heading and child at the bullet position
            lines[parent_bullet_idx] = new_heading
            lines.insert(parent_bullet_idx + 1, "\n")
            lines.insert(parent_bullet_idx + 2, new_child_item)
            lines.insert(parent_bullet_idx + 3, "\n")

            # Write back
            with open(markdown_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            # Regenerate JSON and photo listings
            from inventory_system import parser
            data = parser.parse_inventory(markdown_path)
            parser.save_json(data, inventory_path)
            parser.generate_photo_listings(markdown_path.parent)

            # Reload
            reload_inventory()

            # Git commit
            git_commit(f"Promote {parent_id} and add child: {child_description}")

            return {
                "success": True,
                "message": f"Promoted '{parent_item}' to container {parent_id} and added child",
                "promoted": True,
                "container_id": parent_id
            }

        return {"error": f"Parent item '{parent_item}' not found in container {container_id}"}

    except Exception as e:
        return {"error": f"Failed to add child item: {str(e)}"}


def add_item_to_container(container_id: str, item_description: str, tags: Optional[str] = None) -> dict:
    """Add an item to a container by modifying the markdown file."""
    if not inventory_path:
        return {"error": "Inventory path not set"}

    markdown_path = inventory_path.parent / "inventory.md"
    if not markdown_path.exists():
        return {"error": "inventory.md not found"}

    try:
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Find the container (can be # or ## heading)
        container_line_idx = None
        for i, line in enumerate(lines):
            if (line.startswith('# ') or line.startswith('## ')) and f'ID:{container_id}' in line:
                container_line_idx = i
                break

        if container_line_idx is None:
            return {"error": f"Container ID:{container_id} not found in markdown"}

        # Find where to insert the item (after the header, before next ## or end)
        insert_idx = container_line_idx + 1

        # Skip blank lines and description
        while insert_idx < len(lines) and (lines[insert_idx].strip() == '' or
                                           not lines[insert_idx].startswith(('*', '#'))):
            insert_idx += 1

        # Create the item line
        if tags:
            item_line = f"* tag:{tags} {item_description}\n"
        else:
            item_line = f"* {item_description}\n"

        # Insert the item
        lines.insert(insert_idx, item_line)

        # Write back to file
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # Regenerate JSON and photo listings
        from inventory_system import parser
        data = parser.parse_inventory(markdown_path)
        parser.save_json(data, inventory_path)
        parser.generate_photo_listings(markdown_path.parent)

        # Reload inventory data
        reload_inventory()

        # Git commit
        git_commit(f"Add item to {container_id}: {item_description}")

        return {
            "success": True,
            "message": f"Added '{item_description}' to container {container_id}",
            "container_id": container_id,
            "item": item_description
        }

    except Exception as e:
        return {"error": f"Failed to add item: {str(e)}"}


def remove_container(container_id: str) -> dict:
    """Remove a container from the inventory by removing its section from the markdown file."""
    if not inventory_path:
        return {"error": "Inventory path not set"}

    markdown_path = inventory_path.parent / "inventory.md"
    if not markdown_path.exists():
        return {"error": "inventory.md not found"}

    try:
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Find the container section (can be # or ## heading)
        container_start_idx = None
        container_level = None
        for i, line in enumerate(lines):
            if (line.startswith('# ') or line.startswith('## ')) and f'ID:{container_id}' in line:
                container_start_idx = i
                container_level = '#' if line.startswith('# ') else '##'
                break

        if container_start_idx is None:
            return {"error": f"Container ID:{container_id} not found"}

        # Find the end of this container (next heading of same or higher level, or end of file)
        container_end_idx = len(lines)
        for i in range(container_start_idx + 1, len(lines)):
            if container_level == '#' and lines[i].startswith('# '):
                container_end_idx = i
                break
            elif container_level == '##' and (lines[i].startswith('# ') or lines[i].startswith('## ')):
                container_end_idx = i
                break

        # Remove the container section
        del lines[container_start_idx:container_end_idx]

        # Write back
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # Regenerate JSON and photo listings
        from inventory_system import parser
        data = parser.parse_inventory(markdown_path)
        parser.save_json(data, inventory_path)
        parser.generate_photo_listings(markdown_path.parent)

        # Reload
        reload_inventory()

        # Git commit
        git_commit(f"Remove container {container_id}")

        return {
            "success": True,
            "message": f"Removed container {container_id}",
            "container_id": container_id
        }

    except Exception as e:
        return {"error": f"Failed to remove container: {str(e)}"}


def remove_item_from_container(container_id: str, item_description: str) -> dict:
    """Remove an item from a container by modifying the markdown file."""
    if not inventory_path:
        return {"error": "Inventory path not set"}

    markdown_path = inventory_path.parent / "inventory.md"
    if not markdown_path.exists():
        return {"error": "inventory.md not found"}

    try:
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Find the container section (can be # or ## heading)
        container_line_idx = None
        container_level = None
        for i, line in enumerate(lines):
            if (line.startswith('# ') or line.startswith('## ')) and f'ID:{container_id}' in line:
                container_line_idx = i
                container_level = '#' if line.startswith('# ') else '##'
                break

        if container_line_idx is None:
            return {"error": f"Container ID:{container_id} not found"}

        # Find and remove the item
        item_removed = False
        i = container_line_idx + 1
        while i < len(lines):
            # Stop at next heading of same or higher level
            if container_level == '#' and lines[i].startswith('# '):
                break
            elif container_level == '##' and (lines[i].startswith('# ') or lines[i].startswith('## ')):
                break

            if lines[i].startswith('* ') and item_description.lower() in lines[i].lower():
                del lines[i]
                item_removed = True
                break
            i += 1

        if not item_removed:
            return {"error": f"Item '{item_description}' not found in container {container_id}"}

        # Write back
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        # Regenerate JSON and photo listings
        from inventory_system import parser
        data = parser.parse_inventory(markdown_path)
        parser.save_json(data, inventory_path)
        parser.generate_photo_listings(markdown_path.parent)

        # Reload
        reload_inventory()

        # Git commit
        git_commit(f"Remove item from {container_id}: {item_description}")

        return {
            "success": True,
            "message": f"Removed '{item_description}' from container {container_id}",
            "container_id": container_id
        }

    except Exception as e:
        return {"error": f"Failed to remove item: {str(e)}"}


def add_todo(task_description: str, priority: str = "medium") -> dict:
    """Add a task or change request to TODO.md."""
    if not inventory_path:
        return {"error": "Inventory path not set"}

    todo_path = inventory_path.parent / "TODO.md"

    try:
        # Read existing TODO.md or create new one
        if todo_path.exists():
            with open(todo_path, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            content = "# TODO\n\nInventory change requests and tasks.\n\n"

        # Add timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Format priority marker
        priority_marker = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🟢"
        }.get(priority, "🟡")

        # Append new task
        new_task = f"\n## {priority_marker} {timestamp}\n\n{task_description}\n"
        content += new_task

        # Write back
        with open(todo_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            "success": True,
            "message": f"Added task to TODO.md with priority: {priority}",
            "task": task_description
        }

    except Exception as e:
        return {"error": f"Failed to add TODO: {str(e)}"}


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool and return results."""
    if tool_name == "search_inventory":
        return search_inventory(tool_input['query'])
    elif tool_name == "get_container":
        return get_container(tool_input['container_id'])
    elif tool_name == "list_containers":
        return list_containers(
            parent=tool_input.get('parent'),
            tags=tool_input.get('tags'),
            prefix=tool_input.get('prefix')
        )
    elif tool_name == "add_item":
        return add_item_to_container(
            container_id=tool_input['container_id'],
            item_description=tool_input['item_description'],
            tags=tool_input.get('tags')
        )
    elif tool_name == "remove_item":
        return remove_item_from_container(
            container_id=tool_input['container_id'],
            item_description=tool_input['item_description']
        )
    elif tool_name == "add_todo":
        return add_todo(
            task_description=tool_input['task_description'],
            priority=tool_input.get('priority', 'medium')
        )
    else:
        return {"error": f"Unknown tool: {tool_name}"}


@app.post("/chat", response_model=ChatResponse)
async def chat(message: ChatMessage) -> ChatResponse:
    """Handle chat messages and return Claude's response."""

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY environment variable not set"
        )

    if not inventory_data:
        raise HTTPException(
            status_code=500,
            detail="Inventory data not loaded. Ensure inventory.json exists in the current directory."
        )

    # Initialize Claude client
    client = anthropic.Anthropic(api_key=api_key)

    # System prompt with inventory context
    system_prompt = f"""You are a helpful assistant for managing a personal inventory system.

The inventory contains {len(inventory_data.get('containers', []))} containers with various items stored in them.

You have access to tools to:
- Search and query the inventory
- Get container details
- List containers
- **Add items** to containers
- **Remove items** from containers
- **Add tasks to TODO.md** for complex changes you cannot handle directly

When users ask about their inventory:
1. Use the appropriate tools to find information
2. Provide clear, concise answers
3. Reference specific container IDs when relevant
4. If items are in multiple containers, list them all
5. Be conversational and helpful
6. Match the user's language (respond in the same language they use)

When users want to modify the inventory:
1. For simple changes (add/remove items): Use add_item or remove_item tools directly
2. For complex changes you CANNOT handle (moving photos between containers, reorganizing structure, changing container metadata, moving physical items): Use add_todo to create a task
3. Always confirm what was done

IMPORTANT: If a user asks you to do something that requires:
- Moving photo directories between containers
- Reorganizing container structure
- Changing container headings or metadata
- Moving physical items between containers
- System or design changes

Use the add_todo tool to record the request in TODO.md. Explain to the user that this requires manual intervention and you've added it to the TODO list.

Important notes:
- Container IDs like A23, H11, C04 refer to physical boxes/containers
- Tags help categorize items (e.g., tag:winter, tag:sport)
- Some containers have parent locations (e.g., Garasje=garage, Loft=attic)
"""

    # Create messages array
    messages = [{"role": "user", "content": message.message}]

    # Initial API call (use model from request)
    response = client.messages.create(
        model=message.model,
        max_tokens=4096,
        tools=INVENTORY_TOOLS,
        system=system_prompt,
        messages=messages
    )

    # Handle tool use loop
    while response.stop_reason == "tool_use":
        # Extract tool calls
        tool_results = []

        for block in response.content:
            if block.type == "tool_use":
                tool_result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(tool_result)
                })

        # Add assistant response and tool results to messages
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        # Continue conversation
        response = client.messages.create(
            model=message.model,
            max_tokens=4096,
            tools=INVENTORY_TOOLS,
            system=system_prompt,
            messages=messages
        )

    # Extract final text response
    final_response = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_response += block.text

    return ChatResponse(
        response=final_response,
        conversation_id=message.conversation_id or "default"
    )


@app.get("/api/containers")
async def list_containers_api() -> dict:
    """List all containers for dropdown selection."""
    if not inventory_data:
        raise HTTPException(status_code=500, detail="Inventory not loaded")

    containers = [{
        'id': c['id'],
        'heading': c.get('heading', ''),
        'parent': c.get('parent', '')
    } for c in inventory_data.get('containers', [])]

    return {"containers": sorted(containers, key=lambda x: x['id'])}


@app.post("/api/items")
async def add_item_api(container_id: str = Form(...), item_description: str = Form(...), tags: str = Form("")) -> dict:
    """Add an item to a container (mobile-friendly endpoint)."""
    result = add_item_to_container(container_id, item_description, tags if tags else None)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/items/add-child")
async def add_child_item_api(container_id: str = Form(...), parent_item: str = Form(...), child_description: str = Form(...)) -> dict:
    """Add a child item to a parent item (promotes parent to container if needed)."""
    result = add_child_to_item(container_id, parent_item, child_description)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.delete("/api/items")
async def remove_item_api(container_id: str, item_description: str) -> dict:
    """Remove an item from a container (mobile-friendly endpoint)."""
    result = remove_item_from_container(container_id, item_description)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.delete("/api/containers")
async def remove_container_api(container_id: str) -> dict:
    """Remove an entire container from the inventory."""
    result = remove_container(container_id)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/api/photos")
async def upload_photo(container_id: str = Form(...), photo: UploadFile = File(...)) -> dict:
    """Upload a photo to a container."""
    if not inventory_path:
        raise HTTPException(status_code=500, detail="Inventory path not set")

    # Validate file type
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.JPG', '.JPEG', '.PNG', '.GIF'}
    file_ext = Path(photo.filename).suffix
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Invalid file type. Only images allowed.")

    # Create photos directory if it doesn't exist
    photos_dir = inventory_path.parent / "photos" / container_id
    photos_dir.mkdir(parents=True, exist_ok=True)

    # Save photo
    photo_path = photos_dir / photo.filename
    try:
        with open(photo_path, 'wb') as f:
            shutil.copyfileobj(photo.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save photo: {str(e)}")

    # Regenerate inventory to discover new photo
    from inventory_system import parser
    markdown_path = inventory_path.parent / "inventory.md"
    data = parser.parse_inventory(markdown_path)
    parser.save_json(data, inventory_path)
    parser.generate_photo_listings(markdown_path.parent)

    # Reload inventory
    reload_inventory()

    # Git commit
    git_commit(f"Add photo to {container_id}: {photo.filename}")

    return {
        "success": True,
        "message": f"Photo {photo.filename} uploaded to {container_id}",
        "photo_path": f"photos/{container_id}/{photo.filename}"
    }


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "inventory_loaded": inventory_data is not None,
        "container_count": len(inventory_data.get('containers', [])) if inventory_data else 0,
        "chat_available": bool(os.environ.get("ANTHROPIC_API_KEY"))
    }


if __name__ == "__main__":
    import uvicorn

    print("🤖 Starting Inventory Chatbot Server...")
    print("📍 Server will run at: http://localhost:8765")
    print("💬 Chat endpoint: http://localhost:8765/chat")
    print("❤️  Health check: http://localhost:8765/health")
    print()
    print("Make sure ANTHROPIC_API_KEY is set in your environment!")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8765)
