"""Release documentation must not ship broken repository-relative links."""

import re
from pathlib import Path


def test_local_markdown_links_resolve() -> None:
    root = Path(__file__).resolve().parents[1]
    documents = sorted(root.glob("*.md"))
    for folder in ("docs", "examples", ".github"):
        documents.extend(sorted((root / folder).rglob("*.md")))
    missing: list[str] = []
    for document in documents:
        for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", document.read_text()):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text = target.split("#", maxsplit=1)[0]
            if path_text and not (document.parent / path_text).exists():
                missing.append(f"{document.relative_to(root)} -> {target}")
    assert missing == []
