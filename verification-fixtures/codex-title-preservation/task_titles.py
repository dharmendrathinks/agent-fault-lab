"""Read one task title from a text line."""


def title_from_line(line: str) -> str:
    """Remove the line ending while preserving the title."""
    return line.strip()
