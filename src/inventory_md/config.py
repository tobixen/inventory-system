"""
Configuration file system for inventory-md.

Supports loading configuration from multiple locations, merged with precedence:
1. /etc/inventory-md/config.yaml or config.json (lowest priority)
2. ~/.config/inventory-md/config.yaml or config.json
3. ./inventory-md.yaml or ./inventory-md.json (highest priority)

All found config files are merged, with later files overriding earlier ones.
YAML is checked before JSON at each location. Environment variables
(INVENTORY_MD_*) have the highest priority.

Note: the CWD search uses only ``inventory-md.yaml``/``inventory-md.json`` to
avoid accidentally picking up an unrelated ``config.yaml`` from the project
root.  System/user config directories (already namespaced as
``/etc/inventory-md/`` etc.) use ``config.yaml``/``config.json``.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

# Config filenames for current working directory (project-local config).
# Uses namespaced names only to avoid colliding with unrelated config.yaml files.
CONFIG_FILENAMES = ["inventory-md.yaml", "inventory-md.json"]
# Config filenames for system/user config directories (already namespaced by directory)
CONFIG_USER_FILENAMES = ["config.yaml", "config.json"]

DEFAULTS: dict[str, Any] = {
    "lang": "en",  # Default language for the inventory
    "sections": {
        # Heading text of the intro section (captured into JSON as "intro")
        "intro": "Intro",
        # Heading text of the numbering scheme section (captured into JSON as "numbering_scheme")
        "numbering_scheme": "Nummereringsregime",
    },
    "api": {"host": "127.0.0.1", "port": 8765},
    "serve": {"host": "127.0.0.1", "port": 8000},
    "labels": {
        "sheet_format": "48x25-40",
        "base_url": "https://inventory.example.com/search.html",
        "style": "standard",
        "duplicate_qr": False,
    },
}


def _get_config_dirs() -> list[Path]:
    """Get list of config directories to search, in merge order (lowest priority first)."""
    return [
        Path("/etc/inventory-md"),
        Path.home() / ".config" / "inventory-md",
        Path.cwd(),
    ]


def find_config_files() -> list[Path]:
    """Find all existing config files, in merge order (lowest priority first).

    Searches in order:
    1. /etc/inventory-md/config.yaml or config.json (lowest priority)
    2. ~/.config/inventory-md/config.yaml or config.json
    3. ./inventory-md.yaml or ./inventory-md.json (highest priority)

    Returns list of found files. At each location, only the first found
    file (YAML before JSON) is included.
    """
    config_dirs = _get_config_dirs()
    found_files = []

    for dir_path in config_dirs:
        # Use different filenames for cwd vs standard config dirs
        filenames = CONFIG_FILENAMES if dir_path == Path.cwd() else CONFIG_USER_FILENAMES
        for filename in filenames:
            path = dir_path / filename
            if path.exists():
                found_files.append(path)
                break  # Only use first found file at each location
    return found_files


def find_config_file() -> Path | None:
    """Find the highest-priority existing config file.

    Returns the config file that would take precedence (from current directory
    if present, otherwise ~/.config, otherwise /etc), or None if no config
    file exists.
    """
    files = find_config_files()
    return files[-1] if files else None


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base dict, modifying base in place."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_config_file(path: Path) -> dict[str, Any]:
    """Load a single config file and return its contents.

    Args:
        path: Path to config file (YAML or JSON).

    Returns:
        Parsed configuration dictionary.

    Raises:
        ImportError: If YAML config is found but PyYAML is not installed.
        json.JSONDecodeError: If JSON config file is malformed.
    """
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ImportError(
                "PyYAML required for .yaml config files. Install with: pip install inventory-md[yaml]"
            ) from e
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    else:
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from file(s), merging with defaults.

    If path is provided, only that file is loaded. Otherwise, all config
    files from standard locations are merged with precedence:
    1. Built-in defaults (lowest priority)
    2. /etc/inventory-md/config.yaml or config.json
    3. ~/.config/inventory-md/config.yaml or config.json
    4. ./inventory-md.yaml or ./inventory-md.json
    5. Environment variables INVENTORY_MD_* (highest priority)

    Args:
        path: Optional explicit path to config file. If provided, only this
              file is loaded (plus defaults and env vars). If None, all
              standard locations are searched and merged.

    Returns:
        Merged configuration dictionary with defaults applied.

    Raises:
        ImportError: If YAML config is found but PyYAML is not installed.
        json.JSONDecodeError: If JSON config file is malformed.
    """
    # Start with a deep copy of defaults
    config = copy.deepcopy(DEFAULTS)

    if path is not None:
        # Explicit path provided - load only that file
        if path.exists():
            file_config = _load_config_file(path)
            _deep_merge(config, file_config)
    else:
        # Load and merge all config files from standard locations
        for config_path in find_config_files():
            file_config = _load_config_file(config_path)
            _deep_merge(config, file_config)

    # Apply environment variable overrides (INVENTORY_MD_*)
    _apply_env_overrides(config)

    return config


def _apply_env_overrides(config: dict[str, Any]) -> None:
    """Apply environment variable overrides to config.

    Environment variables are named INVENTORY_MD_<KEY> where nested
    keys use double underscore, e.g., INVENTORY_MD_API__PORT=9000
    """
    prefix = "INVENTORY_MD_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix) :].lower()
            _set_nested_value(config, config_key, value)


def _set_nested_value(config: dict, key: str, value: str) -> None:
    """Set a nested config value using double-underscore notation.

    e.g., "api__port" sets config["api"]["port"]
    """
    parts = key.split("__")
    target = config
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]

    final_key = parts[-1]
    # Try to convert to int/bool if possible
    target[final_key] = _convert_value(value)


def _convert_value(value: str) -> Any:
    """Convert string value to appropriate type."""
    # Boolean
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # Integer
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # String
    return value


def get_config_value(config: dict[str, Any], key: str, default: Any = None) -> Any:
    """Get a config value using dot notation.

    Args:
        config: Configuration dictionary.
        key: Dot-separated key, e.g., "api.port" or "inventory_file".
        default: Default value if key not found.

    Returns:
        The config value, or default if not found.
    """
    parts = key.split(".")
    target = config
    for part in parts:
        if isinstance(target, dict) and part in target:
            target = target[part]
        else:
            return default
    return target


class Config:
    """Configuration holder with convenient access methods."""

    def __init__(self, path: Path | None = None):
        """Initialize config, loading from file(s).

        Args:
            path: Optional explicit path to config file. If provided, only
                  this file is loaded. Otherwise, all standard locations
                  are searched and merged.
        """
        self._explicit_path = path
        if path is not None:
            self._paths = [path] if path.exists() else []
        else:
            self._paths = find_config_files()
        self._data = load_config(path)

    @property
    def path(self) -> Path | None:
        """Return the highest-priority loaded config file, or None."""
        return self._paths[-1] if self._paths else None

    @property
    def paths(self) -> list[Path]:
        """Return all loaded config file paths, in merge order."""
        return self._paths.copy()

    @property
    def data(self) -> dict[str, Any]:
        """Return the raw config dictionary."""
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot notation.

        Args:
            key: Dot-separated key, e.g., "api.port".
            default: Default value if key not found.

        Returns:
            The config value, or default if not found.
        """
        return get_config_value(self._data, key, default)

    # Convenience properties for common settings
    @property
    def inventory_file(self) -> Path | None:
        """Return inventory_file path if configured."""
        val = self.get("inventory_file")
        return Path(val) if val else None

    @property
    def wanted_file(self) -> Path | None:
        """Return wanted_file path if configured."""
        val = self.get("wanted_file")
        return Path(val) if val else None

    @property
    def base_url(self) -> str | None:
        """Return base_url if configured."""
        return self.get("base_url")

    @property
    def api_host(self) -> str:
        """Return API server host."""
        return self.get("api.host", "127.0.0.1")

    @property
    def api_port(self) -> int:
        """Return API server port."""
        return self.get("api.port", 8765)

    @property
    def serve_host(self) -> str:
        """Return web server host."""
        return self.get("serve.host", "127.0.0.1")

    @property
    def serve_port(self) -> int:
        """Return web server port."""
        return self.get("serve.port", 8000)

    @property
    def tingbok_url(self) -> str | None:
        """Return tingbok service URL.

        Defaults to 'https://tingbok.plann.no'. Override via config key
        ``tingbok.url`` or env var ``INVENTORY_MD_TINGBOK__URL``. Set to
        empty string or 'false' to disable.
        """
        value = self.get("tingbok.url", "https://tingbok.plann.no")
        if not value or value in ("false", "none", "disabled"):
            return None
        return value

    @property
    def labels_base_url(self) -> str:
        """Return labels base URL."""
        return self.get("labels.base_url", "https://inventory.example.com/search.html")

    @property
    def labels_sheet_format(self) -> str:
        """Return default label sheet format."""
        return self.get("labels.sheet_format", "48x25-40")

    @property
    def labels_style(self) -> str:
        """Return default label style."""
        return self.get("labels.style", "standard")

    @property
    def labels_duplicate_qr(self) -> bool:
        """Return whether to duplicate QR codes on labels."""
        return self.get("labels.duplicate_qr", False)

    @property
    def labels_custom_formats(self) -> dict:
        """Return custom label sheet formats from config."""
        return self.get("labels.custom_formats", {})

    @property
    def lang(self) -> str:
        """Return default language for the inventory."""
        value = self.get("lang", "en")
        # YAML parses bare 'no' as boolean False — map it back to Norwegian
        if value is False:
            return "no"
        return str(value) if value else "en"
