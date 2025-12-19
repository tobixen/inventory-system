# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Automatic image discovery from filesystem
  - Parser now scans `photos/{container_id}/` directories for source images
  - Automatically creates missing thumbnails in `resized/{container_id}/`
  - No more manual image list maintenance in markdown
  - Supports `.jpg`, `.jpeg`, `.png`, `.gif` formats
  - Images automatically sorted by filename
  - Uses PIL/Pillow for high-quality resizing (max 800px, quality 85)
- Photo directory metadata support
  - Containers can specify photo directory via `photos:dirname` in heading
  - Allows split containers (e.g., A78-1, A78-2) to share photo directories
  - Priority: photos metadata → photos_link (legacy) → container_id
  - Example: `## ID:A78-1 photos:A78 A78 - stor`
- Container-level tag support
  - Tags can be added to container headings (e.g., `tag:jul,påske`)
  - Search interface shows container-level tag badges when filtering
  - Parser extracts metadata from container headings
- Click-to-view full resolution in lightbox
  - Clicking on lightbox image opens full resolution in new tab
  - Zoom-in cursor and tooltip indicate clickability
  - Provides access to original unscaled images

### Changed
- **Breaking:** Image references in markdown are now ignored
  - Images are discovered from filesystem instead of markdown `![...]` syntax
  - Workflow: copy photos to directories → re-parse → done
  - Removed 1,851 image reference lines from markdown (43% file size reduction)
- **Breaking:** Photo links removed from markdown
  - Removed 172 `[Fotos, full oppløsning](photos/...)` link lines
  - Migrated to `photos:dirname` metadata in container headings (37 containers)
  - Parser no longer parses photo link lines
  - Cleaner markdown files with less clutter
- Parser creates `metadata` field for all containers
  - Includes tags, parent, type, photos, and other metadata from headings

### Fixed
- Split containers (relabeled IDs) now find their photos correctly
  - Added photos metadata to H11-2, A78-1/2, A89-3, C18-2, C19-1/2, C20-1/2, C21-1/2, C23-2
  - Images discovered increased from 1,297 to 2,082 (+785 images)

## [0.2.0] - 2025-12-15

### Added
- Multi-language support with English and Norwegian translations
  - Configurable via `LANGUAGE` constant in search.html
  - All UI strings translated (titles, labels, messages, etc.)
- Hierarchical heading parsing for all markdown heading levels (H1-H6)
  - Automatic parent-child relationships inferred from heading structure
  - Supports deeply nested location hierarchies (e.g., boat compartments)
- Dynamic filter button generation based on container ID prefixes
  - No more hardcoded filter buttons for specific series
  - Automatically detects and displays top 10 container prefixes
- Improved container ID generation from headings
  - Sanitizes heading text to create valid IDs
  - Handles special characters and spaces
  - Truncates long IDs to 50 characters
- Demo inventory with comprehensive examples
  - Shows hierarchical organization
  - Demonstrates tagging system
  - Includes sample data for testing
- `.gitignore` file for Python projects

### Changed
- Generic container terminology throughout UI
  - Changed "bokser" (boxes) to "containere" (containers)
  - Removed hardcoded references to specific box series
  - Search placeholder updated to be more generic
- Parser now creates containers for all heading levels, not just H1 and H2
- Heading stack tracking for proper parent inference
- Python version requirement changed to >=3.13,<4.0 (was >=3.14,<4.0)

### Fixed
- Container navigation links now work properly
  - Fixed event bubbling issue with parent links
  - Toggle container function checks if click originated from link
- Filter matching updated to work with dynamic prefixes
  - Uses same prefix extraction logic as filter generation

## [0.1.0] - 2025-12-15

### Added
- Initial release of inventory-system package
- Markdown-based inventory parser
  - Parse inventory.md files into structured JSON
  - Support for hierarchical containers
  - Metadata extraction (ID, parent, type, tags)
  - Image reference parsing
- CLI tool with three commands:
  - `init` - Initialize new inventory
  - `parse` - Parse and validate inventory
  - `serve` - Start local web server
- Web-based search interface
  - Searchable container and item database
  - Lazy-loaded images with lightbox viewer
  - Tag-based filtering with AND logic
  - Gallery view for browsing all images
  - Alias search support
- Package structure with templates
  - Reusable search.html template
  - Aliases.json template for search aliases
  - Example inventory.md template
- Automatic version management with setuptools-scm
- Ruff configuration for code quality

[unreleased]: https://github.com/yourusername/inventory-system/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/yourusername/inventory-system/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/yourusername/inventory-system/releases/tag/v0.1.0
