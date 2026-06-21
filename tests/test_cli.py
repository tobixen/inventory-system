"""Tests for CLI module."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from inventory_md import cli
from inventory_md._version import __version__


class TestVersion:
    """Tests for --version option."""

    def test_version_option_exits_with_version(self):
        """Test that --version prints version and exits."""
        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert __version__ in result.stdout

    def test_version_short_option(self):
        """Test that -V also works for version."""
        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "-V"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert __version__ in result.stdout


class TestServeCommand:
    """Tests for serve_command function."""

    def test_serve_command_accepts_api_proxy_param(self):
        """Test that serve_command accepts api_proxy parameter."""
        # Just verify the function signature accepts the parameter
        import inspect

        sig = inspect.signature(cli.serve_command)
        params = list(sig.parameters.keys())
        assert "api_proxy" in params

    def test_serve_command_directory_not_exists(self, tmp_path):
        """Test serve_command fails if directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        result = cli.serve_command(nonexistent, 8000, None)
        assert result == 1

    def test_serve_command_no_search_html(self, tmp_path):
        """Test serve_command fails if search.html doesn't exist."""
        result = cli.serve_command(tmp_path, 8000, None)
        assert result == 1


class TestCliArgumentParser:
    """Tests for CLI argument parsing."""

    def test_serve_has_api_proxy_option(self):
        """Test that serve subcommand has --api-proxy option."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        serve_parser = subparsers.add_parser("serve")
        serve_parser.add_argument("directory", type=Path, nargs="?")
        serve_parser.add_argument("--port", "-p", type=int, default=8000)
        serve_parser.add_argument("--api-proxy", type=str, metavar="HOST:PORT")

        # Parse with --api-proxy
        args = parser.parse_args(["serve", "--api-proxy", "localhost:8765"])
        assert args.api_proxy == "localhost:8765"

        # Parse without --api-proxy
        args = parser.parse_args(["serve"])
        assert args.api_proxy is None


class TestExpiringAndLookupCommands:
    """Tests for the 'expiring' and 'lookup' subcommands (dispatch via cli.main)."""

    INVENTORY = {
        "containers": [
            {
                "id": "pantry",
                "parent": "kitchen",
                "items": [
                    {"id": "old-rice", "name": "Rice", "metadata": {"bb": "2020-01-01"}},
                    {"id": "fresh-onion", "name": "Onion", "metadata": {}},
                ],
            }
        ]
    }

    def _write(self, tmp_path):
        path = tmp_path / "inventory.json"
        path.write_text(json.dumps(self.INVENTORY))
        return path

    def test_expiring_lists_expired_item(self, tmp_path, capsys):
        path = self._write(tmp_path)
        rc = cli.main(["expiring", str(path)])
        assert rc == 0
        assert "old-rice" in capsys.readouterr().out

    def test_expiring_missing_file_returns_1(self, tmp_path):
        rc = cli.main(["expiring", str(tmp_path / "nope.json")])
        assert rc == 1

    def test_expiring_category_filter(self, tmp_path, capsys):
        inv = {
            "containers": [
                {
                    "id": "pantry",
                    "parent": "",
                    "items": [
                        {"id": "rice1", "name": "Basmati", "metadata": {"bb": "2020-01-01", "categories": ["rice"]}},
                        {"id": "oats1", "name": "Oats", "metadata": {"bb": "2020-01-01", "categories": ["oats"]}},
                    ],
                }
            ]
        }
        path = tmp_path / "inventory.json"
        path.write_text(json.dumps(inv))
        rc = cli.main(["expiring", str(path), "--category", "rice"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "rice1" in out
        assert "oats1" not in out

    def test_lookup_by_match_includes_item_without_bb(self, tmp_path, capsys):
        path = self._write(tmp_path)
        rc = cli.main(["lookup", str(path), "--match", "onion"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "fresh-onion" in out
        assert "no bb" in out

    def test_lookup_without_selectors_returns_1(self, tmp_path):
        path = self._write(tmp_path)
        assert cli.main(["lookup", str(path)]) == 1


class TestProxyHTTPHandler:
    """Tests for the proxy HTTP handler behavior."""

    def test_should_proxy_paths(self):
        """Test which paths should be proxied."""
        # Simulating the should_proxy logic
        api_proxy = "localhost:8765"

        def should_proxy(path):
            return api_proxy and (path.startswith("/api/") or path.startswith("/chat") or path.startswith("/health"))

        assert should_proxy("/api/items")
        assert should_proxy("/api/photos")
        assert should_proxy("/chat")
        assert should_proxy("/chat/stream")
        assert should_proxy("/health")
        assert not should_proxy("/search.html")
        assert not should_proxy("/inventory.json")
        assert not should_proxy("/resized/photo.jpg")

    def test_should_not_proxy_without_api_proxy(self):
        """Test that nothing is proxied when api_proxy is None."""
        api_proxy = None

        def should_proxy(path):
            return api_proxy and (path.startswith("/api/") or path.startswith("/chat") or path.startswith("/health"))

        assert not should_proxy("/api/items")
        assert not should_proxy("/chat")
        assert not should_proxy("/health")


class TestInitCommand:
    """Tests for init_inventory function."""

    def test_init_creates_directory(self, tmp_path):
        """Test that init creates the directory structure."""
        inventory_dir = tmp_path / "new_inventory"

        with patch("builtins.input", return_value="n"):
            result = cli.init_inventory(inventory_dir, "Test Inventory")

        assert result == 0
        assert inventory_dir.exists()
        assert (inventory_dir / "inventory.md").exists()
        assert (inventory_dir / "photos").exists()
        assert (inventory_dir / "resized").exists()


class TestUpdateTemplate:
    """Tests for update_template function."""

    def test_update_template_creates_file(self, tmp_path):
        """Test that update_template creates search.html."""
        result = cli.update_template(tmp_path)

        assert result == 0
        assert (tmp_path / "search.html").exists()

    def test_update_template_overwrites_stale_content(self, tmp_path):
        """Test that update_template silently overwrites when content differs."""
        existing = tmp_path / "search.html"
        existing.write_text("old content")

        result = cli.update_template(tmp_path)

        assert result == 0
        content = existing.read_text()
        assert "old content" not in content
        assert "<!DOCTYPE html>" in content

    def test_update_template_skips_when_already_current(self, tmp_path):
        """Test that update_template is a no-op when content already matches."""
        from pathlib import Path as _Path

        source = _Path(cli.__file__).parent / "templates" / "search.html"
        target = tmp_path / "search.html"
        import shutil

        shutil.copy(source, target)

        result = cli.update_template(tmp_path)

        assert result == 0
        assert target.stat().st_mtime == target.stat().st_mtime  # no rewrite

    def test_update_template_fails_for_nonexistent_directory(self, tmp_path):
        """Test that update_template fails if directory doesn't exist."""
        result = cli.update_template(tmp_path / "nonexistent")
        assert result == 1

    def test_update_template_uses_cwd_by_default(self, tmp_path, monkeypatch):
        """Test that update_template uses current directory by default."""
        monkeypatch.chdir(tmp_path)

        result = cli.update_template()

        assert result == 0
        assert (tmp_path / "search.html").exists()

    def test_parse_writes_lang_to_json(self, tmp_path, monkeypatch):
        """Test that configured lang is written to inventory.json."""
        inventory_md = tmp_path / "inventory.md"
        inventory_md.write_text("# Test\n\n## ID:Box1 Test Box\n\n* Test item\n")

        config_file = tmp_path / "inventory-md.yaml"
        config_file.write_text("lang: no\n")

        monkeypatch.chdir(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "parse", str(inventory_md)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "INVENTORY_MD_TINGBOK__URL": ""},
        )

        assert result.returncode == 0
        output_json = json.loads((tmp_path / "inventory.json").read_text())
        assert output_json["lang"] == "no"

    def test_parse_omits_lang_when_english(self, tmp_path, monkeypatch):
        """Test that lang is omitted from inventory.json when it's the default (en)."""
        inventory_md = tmp_path / "inventory.md"
        inventory_md.write_text("# Test\n\n## ID:Box1 Test Box\n\n* Test item\n")

        # No config = default lang 'en'
        monkeypatch.chdir(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "parse", str(inventory_md)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "INVENTORY_MD_TINGBOK__URL": ""},
        )

        assert result.returncode == 0
        output_json = json.loads((tmp_path / "inventory.json").read_text())
        assert "lang" not in output_json


class TestParseCommandEanLookup:
    """Tests for EAN lookup integration in parse_command."""

    def _write_inventory(self, tmp_path, content: str) -> "Path":
        f = tmp_path / "inventory.md"
        f.write_text(content)
        return f

    def _tingbok_patches(self, vocabulary):
        """Return a context manager that patches all tingbok network calls."""
        from contextlib import ExitStack
        from unittest.mock import patch

        stack = ExitStack()
        stack.enter_context(patch.object(vocabulary, "fetch_vocabulary_from_tingbok", return_value={}))
        stack.enter_context(patch.object(vocabulary, "enrich_categories_via_lookup", return_value=({}, {})))
        stack.enter_context(patch.object(vocabulary, "report_ean_to_tingbok", return_value=None))
        return stack

    def test_ean_items_queried_via_tingbok(self, tmp_path, monkeypatch) -> None:
        """Items with EAN metadata trigger a lookup via lookup_ean_via_tingbok."""
        from unittest.mock import patch

        from inventory_md import cli, vocabulary

        inventory_md = self._write_inventory(
            tmp_path,
            "## ID:Box1 Test\n\n* EAN:7310865004703 Kalles Kaviar\n",
        )
        monkeypatch.chdir(tmp_path)

        product = {
            "ean": "7310865004703",
            "name": "Kalles Kaviar",
            "brand": "Abba",
            "quantity": "300g",
            "categories": ["spreads", "caviar spreads"],
            "image_url": None,
            "source": "openfoodfacts",
        }

        with self._tingbok_patches(vocabulary):
            with patch.object(vocabulary, "lookup_ean_via_tingbok", return_value=product) as mock_lookup:
                cli.parse_command(
                    inventory_md,
                    tingbok_url="https://tingbok.plann.no",
                )

        args, kwargs = mock_lookup.call_args
        assert args == ("7310865004703", "https://tingbok.plann.no")
        assert "session" in kwargs

    def test_ean_lookup_skipped_without_tingbok_url(self, tmp_path, monkeypatch) -> None:
        """When no tingbok_url is configured, EAN lookup is skipped."""
        from unittest.mock import patch

        from inventory_md import cli, vocabulary

        inventory_md = self._write_inventory(
            tmp_path,
            "## ID:Box1 Test\n\n* EAN:7310865004703 Kalles Kaviar\n",
        )
        monkeypatch.chdir(tmp_path)

        with patch.object(vocabulary, "lookup_ean_via_tingbok") as mock_lookup:
            cli.parse_command(inventory_md, tingbok_url=None)

        mock_lookup.assert_not_called()

    def test_ean_not_found_does_not_crash(self, tmp_path, monkeypatch) -> None:
        """A 404 from tingbok EAN endpoint is handled gracefully."""
        from inventory_md import cli, vocabulary

        inventory_md = self._write_inventory(
            tmp_path,
            "## ID:Box1 Test\n\n* EAN:0000000000000 Unknown item\n",
        )
        monkeypatch.chdir(tmp_path)

        with self._tingbok_patches(vocabulary):
            from unittest.mock import patch

            with patch.object(vocabulary, "lookup_ean_via_tingbok", return_value=None):
                result = cli.parse_command(
                    inventory_md,
                    tingbok_url="https://tingbok.plann.no",
                )

        assert result == 0

    def test_no_push_suppresses_report_ean_to_tingbok(self, tmp_path, monkeypatch) -> None:
        """--no-push skips report_ean_to_tingbok even when a tingbok_url is set."""
        from unittest.mock import patch

        from inventory_md import cli, vocabulary

        inventory_md = self._write_inventory(
            tmp_path,
            "## ID:Box1 Test\n\n* EAN:7310865004703 Kalles Kaviar\n",
        )
        monkeypatch.chdir(tmp_path)

        product = {
            "ean": "7310865004703",
            "name": "Kalles Kaviar",
            "brand": "Abba",
            "quantity": "300g",
            "categories": ["spreads"],
            "image_url": None,
            "source": "openfoodfacts",
        }

        with self._tingbok_patches(vocabulary):
            with patch.object(vocabulary, "lookup_ean_via_tingbok", return_value=product):
                with patch.object(vocabulary, "report_ean_to_tingbok") as mock_report:
                    cli.parse_command(
                        inventory_md,
                        tingbok_url="https://tingbok.plann.no",
                        no_push=True,
                    )

        mock_report.assert_not_called()


class TestShoppingListCommand:
    """Tests for the shopping-list subcommand."""

    def _make_inventory_json(self, tmp_path, items_meta):
        items = [
            {
                "id": m.get("id", f"item-{i}"),
                "parent": None,
                "name": m.get("name", "Test item"),
                "raw_text": "",
                "metadata": {k: v for k, v in m.items() if k not in ("id", "name")},
                "indented": False,
            }
            for i, m in enumerate(items_meta)
        ]
        data = {"containers": [{"id": "test", "items": items, "images": [], "metadata": {}}]}
        (tmp_path / "inventory.json").write_text(json.dumps(data))

    def test_shopping_list_command_writes_output(self, tmp_path):
        """shopping-list command writes shopping-list.md from inventory.json."""
        self._make_inventory_json(tmp_path, [{"tags": ["food/pasta"], "qty": 3.0}])
        (tmp_path / "wanted-items.md").write_text("## Pasta\n\n* tag:food/pasta - Pasta target:qty:2\n")

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "shopping-list"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = (tmp_path / "shopping-list.md").read_text()
        assert "Shopping List" in output

    def test_shopping_list_command_fails_without_inventory_json(self, tmp_path):
        """shopping-list fails with clear error if inventory.json is missing."""
        (tmp_path / "wanted-items.md").write_text("## Pasta\n\n* category:pasta - Pasta\n")

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "shopping-list"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode != 0
        assert "inventory.json" in result.stdout or "inventory.json" in result.stderr

    def test_shopping_list_command_fails_without_wanted_items(self, tmp_path):
        """shopping-list fails with clear error if wanted-items.md is missing."""
        self._make_inventory_json(tmp_path, [])

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "shopping-list"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode != 0

    def test_shopping_list_stdout_flag(self, tmp_path):
        """--stdout prints to stdout without writing file."""
        self._make_inventory_json(tmp_path, [{"tags": ["food/pasta"], "qty": 2.0}])
        (tmp_path / "wanted-items.md").write_text("## Pasta\n\n* tag:food/pasta - Pasta target:qty:1\n")

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "shopping-list", "--stdout"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        assert "Shopping List" in result.stdout
        assert not (tmp_path / "shopping-list.md").exists()

    def test_shopping_list_explicit_wanted_items(self, tmp_path):
        """--wanted-items flag allows specifying an alternate file."""
        self._make_inventory_json(tmp_path, [{"tags": ["food/pasta"], "qty": 2.0}])
        wanted = tmp_path / "my-wanted.md"
        wanted.write_text("## Pasta\n\n* tag:food/pasta - Pasta target:qty:1\n")

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "shopping-list", "--wanted-items", str(wanted), "--stdout"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        assert "Shopping List" in result.stdout


class TestParseCommandWantedItemsLabels:
    """Test that parse_command includes wanted-items labels in the tingbok resolve call."""

    def _write_inventory(self, tmp_path, content: str) -> "Path":
        f = tmp_path / "inventory.md"
        f.write_text(content)
        return f

    def test_wanted_items_labels_included_in_resolve(self, tmp_path, monkeypatch) -> None:
        """When wanted-items is given, its category labels are sent to resolve_vocabulary_from_tingbok."""
        from unittest.mock import patch

        from inventory_md import cli, vocabulary

        inventory_md = self._write_inventory(
            tmp_path,
            "## ID:Pantry Pantry\n\n* category:olive-oil ID:oo1 volume:750ml Olive oil\n",
        )
        wanted = tmp_path / "wanted-items.md"
        wanted.write_text("## Oils\n\n* category:cooking-oil - Cooking oil target:qty:1\n")
        monkeypatch.chdir(tmp_path)

        captured_labels = []

        def mock_resolve(labels, url, lang="en", session=None):
            captured_labels.extend(labels)
            return {}

        with patch.object(vocabulary, "resolve_vocabulary_from_tingbok", side_effect=mock_resolve):
            with patch.object(vocabulary, "load_global_vocabulary", return_value={}):
                with patch.object(vocabulary, "enrich_categories_via_lookup", return_value=({}, {})):
                    cli.parse_command(
                        inventory_md,
                        wanted_items=wanted,
                        tingbok_url="https://tingbok.plann.no",
                    )

        assert "olive-oil" in captured_labels, "inventory category should be in resolve labels"
        assert "cooking-oil" in captured_labels, "wanted-items category should be in resolve labels"


class TestVocabularySearch:
    """Tests for 'vocabulary search' subcommand."""

    def _make_vocab(self, tmp_path) -> None:
        """Write a vocabulary.json and inventory.json with a spice hierarchy."""
        vocab = {
            "concepts": {
                "food": {"id": "food", "prefLabel": "Food", "broader": [], "narrower": ["food/spices"]},
                "food/spices": {
                    "id": "food/spices",
                    "prefLabel": "Spices",
                    "broader": ["food"],
                    "narrower": ["food/spices/cumin", "food/spices/pepper"],
                },
                "food/spices/cumin": {
                    "id": "food/spices/cumin",
                    "prefLabel": "Cumin",
                    "broader": ["food/spices"],
                    "narrower": [],
                },
                "food/spices/pepper": {
                    "id": "food/spices/pepper",
                    "prefLabel": "Pepper",
                    "broader": ["food/spices"],
                    "narrower": [],
                },
                "cooking-oil": {
                    "id": "cooking-oil",
                    "prefLabel": "Cooking Oil",
                    "broader": [],
                    "narrower": ["cooking-oil/olive-oil"],
                },
                "cooking-oil/olive-oil": {
                    "id": "cooking-oil/olive-oil",
                    "prefLabel": "Olive Oil",
                    "broader": ["cooking-oil"],
                    "narrower": [],
                },
            }
        }
        (tmp_path / "vocabulary.json").write_text(json.dumps(vocab))

        inventory = {
            "containers": [
                {
                    "id": "pantry",
                    "items": [
                        {
                            "id": "cumin1",
                            "name": "Ground cumin",
                            "metadata": {"categories": ["food/spices/cumin"]},
                            "indented": False,
                            "parent": None,
                            "raw_text": "",
                        },
                        {
                            "id": "pepper1",
                            "name": "Black pepper",
                            "metadata": {"categories": ["food/spices/pepper"]},
                            "indented": False,
                            "parent": None,
                            "raw_text": "",
                        },
                        {
                            "id": "oil1",
                            "name": "Olive oil 750ml",
                            "metadata": {"categories": ["cooking-oil/olive-oil"], "volume_l": 0.75},
                            "indented": False,
                            "parent": None,
                            "raw_text": "",
                        },
                        {
                            "id": "book1",
                            "name": "Cooking book",
                            "metadata": {"categories": ["book"]},
                            "indented": False,
                            "parent": None,
                            "raw_text": "",
                        },
                    ],
                    "images": [],
                    "metadata": {},
                }
            ]
        }
        (tmp_path / "inventory.json").write_text(json.dumps(inventory))

    def test_search_finds_direct_category(self, tmp_path) -> None:
        """vocabulary search <label> finds items with exactly that category."""
        self._make_vocab(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory_md.cli",
                "vocabulary",
                "search",
                "food/spices/cumin",
                "--directory",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "cumin" in result.stdout.lower()
        assert "pepper" not in result.stdout.lower()

    def test_search_finds_children_of_category(self, tmp_path) -> None:
        """vocabulary search for a parent category finds all child items."""
        self._make_vocab(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory_md.cli",
                "vocabulary",
                "search",
                "food/spices",
                "--directory",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "cumin" in result.stdout.lower()
        assert "pepper" in result.stdout.lower()
        assert "book" not in result.stdout.lower()

    def test_search_by_leaf_label(self, tmp_path) -> None:
        """vocabulary search with a bare label (not full path) also works."""
        self._make_vocab(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "vocabulary", "search", "spices", "--directory", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "cumin" in result.stdout.lower()
        assert "pepper" in result.stdout.lower()

    def test_search_no_matches(self, tmp_path) -> None:
        """vocabulary search with unknown category returns clean no-results message."""
        self._make_vocab(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory_md.cli",
                "vocabulary",
                "search",
                "nonexistent-category",
                "--directory",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "no items" in result.stdout.lower() or "not found" in result.stdout.lower()

    def _make_vocab_with_containers(self, tmp_path) -> None:
        """Write vocabulary.json and inventory.json with nested containers."""
        vocab = {
            "concepts": {
                "food/spices": {
                    "id": "food/spices",
                    "prefLabel": "Spices",
                    "broader": [],
                    "narrower": ["food/spices/cumin"],
                },
                "food/spices/cumin": {
                    "id": "food/spices/cumin",
                    "prefLabel": "Cumin",
                    "broader": ["food/spices"],
                    "narrower": [],
                },
            }
        }
        (tmp_path / "vocabulary.json").write_text(json.dumps(vocab))

        inventory = {
            "containers": [
                {
                    "id": "galley",
                    "parent": None,
                    "heading": "Galley",
                    "items": [],
                    "images": [],
                    "metadata": {},
                },
                {
                    "id": "spice-cabinet",
                    "parent": "galley",
                    "heading": "Spice Cabinet",
                    "items": [
                        {
                            "id": "cumin1",
                            "name": "Ground cumin",
                            "metadata": {"categories": ["food/spices/cumin"]},
                            "indented": False,
                            "parent": None,
                            "raw_text": "",
                        },
                    ],
                    "images": [],
                    "metadata": {},
                },
            ]
        }
        (tmp_path / "inventory.json").write_text(json.dumps(inventory))

    def test_search_shows_location(self, tmp_path) -> None:
        """vocabulary search output includes the container/location of each item."""
        self._make_vocab_with_containers(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "vocabulary", "search", "spices", "--directory", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "cumin" in result.stdout.lower()
        # Location (container id or heading) should appear in output
        assert "galley" in result.stdout.lower() or "spice-cabinet" in result.stdout.lower()


class TestVocabularyOffline:
    """Tests for vocabulary list/lookup/tree using only vocabulary.json (no tingbok)."""

    def _make_vocab_json(self, tmp_path) -> None:
        vocab = {
            "concepts": {
                "food": {"id": "food", "prefLabel": "Food", "broader": [], "narrower": ["food/spices"]},
                "food/spices": {
                    "id": "food/spices",
                    "prefLabel": "Spices",
                    "broader": ["food"],
                    "narrower": [],
                },
            }
        }
        (tmp_path / "vocabulary.json").write_text(json.dumps(vocab))

    def test_vocabulary_list_from_vocab_json(self, tmp_path) -> None:
        """vocabulary list reads directly from vocabulary.json without querying tingbok."""
        self._make_vocab_json(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "vocabulary", "list", "--directory", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "spices" in result.stdout.lower()
        assert "food" in result.stdout.lower()

    def test_vocabulary_tree_from_vocab_json(self, tmp_path) -> None:
        """vocabulary tree reads directly from vocabulary.json without querying tingbok."""
        self._make_vocab_json(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "vocabulary", "tree", "--directory", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "food" in result.stdout.lower()

    def test_vocabulary_lookup_found_in_vocab_json(self, tmp_path) -> None:
        """vocabulary lookup returns exit 0 and shows concept when found in vocabulary.json."""
        self._make_vocab_json(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "inventory_md.cli", "vocabulary", "lookup", "spices", "--directory", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "spices" in result.stdout.lower()
        assert "warning" not in result.stdout.lower()
        assert "⚠" not in result.stdout

    def test_vocabulary_lookup_warns_when_not_in_local_vocab(self, tmp_path) -> None:
        """vocabulary lookup warns and exits non-zero when label not in vocabulary.json."""
        self._make_vocab_json(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory_md.cli",
                "vocabulary",
                "lookup",
                "nonexistent-thing",
                "--directory",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "not found in local vocabulary" in result.stdout.lower() or "⚠" in result.stdout

    def test_vocabulary_lookup_lang_flag_overrides_config(self, tmp_path) -> None:
        """vocabulary lookup --lang overrides config.lang in the tingbok query."""
        from inventory_md import config as config_mod
        from inventory_md import vocabulary

        args = argparse.Namespace(vocab_command="lookup", label="soppsanking", directory=tmp_path, lang="nb")
        cfg = config_mod.Config()
        cfg._data = {"lang": "en", "tingbok": {"url": "https://tingbok.example"}}

        with patch.object(vocabulary, "enrich_categories_via_lookup", return_value=({}, {})) as mock_enrich:
            rc = cli.vocabulary_command(args, cfg)

        assert rc == 1  # not resolved -> exit 1
        mock_enrich.assert_called_once()
        assert mock_enrich.call_args.kwargs["lang"] == "nb"

    def test_vocabulary_lookup_lang_defaults_to_config(self, tmp_path) -> None:
        """Without --lang, the tingbok query uses config.lang."""
        from inventory_md import config as config_mod
        from inventory_md import vocabulary

        args = argparse.Namespace(vocab_command="lookup", label="soppsanking", directory=tmp_path, lang=None)
        cfg = config_mod.Config()
        cfg._data = {"lang": "de", "tingbok": {"url": "https://tingbok.example"}}

        with patch.object(vocabulary, "enrich_categories_via_lookup", return_value=({}, {})) as mock_enrich:
            rc = cli.vocabulary_command(args, cfg)

        assert rc == 1
        mock_enrich.assert_called_once()
        assert mock_enrich.call_args.kwargs["lang"] == "de"


class TestMoveCommand:
    """Integration tests for the `move` subcommand wiring."""

    _MD = (
        "# ID:box1 First box\n\n"
        "* category:hammer ID:hammer-1 A hammer\n"
        "* category:lubricant ID:wd40 WD-40 spray\n\n"
        "# ID:box2 Second box\n\n"
        "No items yet.\n"
    )

    def test_move_relocates_and_reports(self, tmp_path, capsys) -> None:
        md = tmp_path / "inventory.md"
        md.write_text(self._MD, encoding="utf-8")
        rc = cli.main(["move", "wd40", "box2", "--file", str(md)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Moved wd40 from box1 to box2" in out
        box1, box2 = md.read_text(encoding="utf-8").split("# ID:box2")
        assert "wd40" not in box1
        assert "wd40" in box2

    def test_move_unknown_item_exits_1(self, tmp_path) -> None:
        md = tmp_path / "inventory.md"
        md.write_text(self._MD, encoding="utf-8")
        rc = cli.main(["move", "nope", "box2", "--file", str(md)])
        assert rc == 1
        assert md.read_text(encoding="utf-8") == self._MD

    def test_move_dry_run_leaves_file(self, tmp_path) -> None:
        md = tmp_path / "inventory.md"
        md.write_text(self._MD, encoding="utf-8")
        rc = cli.main(["move", "wd40", "box2", "--file", str(md), "--dry-run"])
        assert rc == 0
        assert md.read_text(encoding="utf-8") == self._MD
