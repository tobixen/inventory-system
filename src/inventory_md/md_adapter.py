"""
Adapter for markdown-it-py library.

Provides structured access to markdown content with proper handling of mixed content
(text + lists). Unlike markdown-to-json, this adapter preserves the distinction
between paragraphs and list items.
"""

from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt


@dataclass
class MarkdownSection:
    """
    Represents a section of a markdown document (under a heading).

    Attributes:
        heading: The heading text (without # markers)
        level: Heading level (1 for H1, 2 for H2, etc.)
        paragraphs: List of paragraph text content
        list_items: List of list items (each item is a dict with 'text' and 'nested' list)
        subsections: Nested sections under this heading
        parent: Parent section (None for top-level)
    """

    heading: str
    level: int
    paragraphs: list[str] = field(default_factory=list)
    list_items: list[dict[str, Any]] = field(default_factory=list)
    subsections: list["MarkdownSection"] = field(default_factory=list)
    parent: "MarkdownSection | None" = None


def parse_markdown_string(content: str) -> list[MarkdownSection]:
    """
    Parse a markdown string into structured sections.

    Args:
        content: Markdown content as string

    Returns:
        List of top-level MarkdownSection objects
    """
    md = MarkdownIt()
    tokens = md.parse(content)

    sections: list[MarkdownSection] = []
    section_stack: list[MarkdownSection] = []  # Stack for tracking heading hierarchy

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.type == "heading_open":
            level = int(token.tag[1])  # h1 -> 1, h2 -> 2, etc.
            # Next token should be inline with heading text
            heading_text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                heading_text = tokens[i + 1].content
                i += 1

            new_section = MarkdownSection(heading=heading_text, level=level)

            # Find appropriate parent based on heading level
            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()

            if section_stack:
                new_section.parent = section_stack[-1]
                section_stack[-1].subsections.append(new_section)
            else:
                sections.append(new_section)

            section_stack.append(new_section)

        elif token.type == "paragraph_open":
            # Collect paragraph content
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                para_text = tokens[i + 1].content
                if section_stack:
                    section_stack[-1].paragraphs.append(para_text)
                i += 1

        elif token.type == "bullet_list_open":
            # Parse the entire list
            list_items, end_i = _parse_list(tokens, i)
            if section_stack:
                section_stack[-1].list_items.extend(list_items)
            i = end_i

        i += 1

    return sections


def _parse_list(tokens: list, start_i: int) -> tuple[list[dict[str, Any]], int]:
    """
    Parse a bullet list starting at start_i.

    Returns:
        Tuple of (list of item dicts, index after list_close)
    """
    items = []
    i = start_i + 1  # Skip bullet_list_open

    while i < len(tokens) and tokens[i].type != "bullet_list_close":
        token = tokens[i]

        if token.type == "list_item_open":
            item = {"text": "", "nested": []}
            i += 1

            # Collect item content
            while i < len(tokens) and tokens[i].type != "list_item_close":
                if tokens[i].type == "paragraph_open":
                    if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                        item["text"] = tokens[i + 1].content
                        i += 1
                elif tokens[i].type == "bullet_list_open":
                    # Nested list
                    nested_items, end_i = _parse_list(tokens, i)
                    item["nested"] = nested_items
                    i = end_i
                i += 1

            items.append(item)
        else:
            i += 1

    return items, i


def sections_to_dict(sections: list[MarkdownSection]) -> dict[str, Any]:
    """
    Convert sections to a nested dictionary structure.

    The dictionary keys are heading texts, and values are dicts containing:
    - 'paragraphs': list of paragraph strings
    - 'list_items': list of item dicts
    - 'subsections': nested dict of subsections

    Args:
        sections: List of MarkdownSection objects

    Returns:
        Nested dictionary structure
    """
    result = {}
    for section in sections:
        section_data = {
            "paragraphs": section.paragraphs,
            "list_items": section.list_items,
        }
        if section.subsections:
            section_data["subsections"] = sections_to_dict(section.subsections)
        result[section.heading] = section_data
    return result


def iter_all_sections(sections: list[MarkdownSection]) -> list[MarkdownSection]:
    """
    Flatten sections into a list of all sections (depth-first).

    Args:
        sections: List of top-level sections

    Returns:
        Flat list of all sections including nested ones
    """
    result = []
    for section in sections:
        result.append(section)
        result.extend(iter_all_sections(section.subsections))
    return result


def find_section(sections: list[MarkdownSection], heading: str) -> MarkdownSection | None:
    """
    Find a section by heading text (case-insensitive partial match).

    Args:
        sections: List of sections to search
        heading: Heading text to find

    Returns:
        MarkdownSection if found, None otherwise
    """
    heading_lower = heading.lower()
    for section in iter_all_sections(sections):
        if heading_lower in section.heading.lower():
            return section
    return None


def get_all_list_items(section: MarkdownSection, include_nested: bool = True) -> list[str]:
    """
    Get all list item texts from a section.

    Args:
        section: The section to extract items from
        include_nested: Whether to include nested list items

    Returns:
        List of item text strings
    """
    items = []
    for item in section.list_items:
        items.append(item["text"])
        if include_nested and item.get("nested"):
            for nested in item["nested"]:
                items.append(nested["text"])
    return items
