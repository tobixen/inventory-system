"""
Inventory System - A flexible markdown-based inventory management system

Features:
- Parse hierarchical markdown inventory files
- Generate searchable web interfaces
- Support for images, metadata tags, and parent-child relationships
- CLI tools for initialization, parsing, and serving
"""

from ._version import __version__
from .parser import (
    AmbiguousContainerError,
    add_container_id_prefixes,
    extract_metadata,
    find_container_section,
    load_json,
    parse_inventory,
    save_json,
    validate_inventory,
)

__all__ = [
    "parse_inventory",
    "extract_metadata",
    "validate_inventory",
    "find_container_section",
    "AmbiguousContainerError",
    "add_container_id_prefixes",
    "save_json",
    "load_json",
]
