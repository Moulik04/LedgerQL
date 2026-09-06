"""Stage 2: schema retrieval.

Phase 2 injects the full analyst schema into every generation prompt --
the schema is small (3 tables + 4 views) so there's nothing to
selectively retrieve yet. Reads docs/schema.md and keeps only the H2
sections that define tables/views, dropping narrative sections (the
intro, the dual-class note, the worked SQL example) that read well for
a human but don't improve SQL correctness and cost tokens.
"""

from pathlib import Path

SCHEMA_MD_PATH = Path(__file__).resolve().parent.parent / "docs" / "schema.md"

KEPT_SECTIONS = {"companies", "filings", "financial_facts", "concept views"}


def get_schema_context(schema_md_path: Path = SCHEMA_MD_PATH) -> str:
    text = schema_md_path.read_text()
    sections = _split_into_h2_sections(text)
    kept = [body for title, body in sections if title.strip().lower() in KEPT_SECTIONS]
    return "\n\n".join(kept).strip()


def _split_into_h2_sections(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = [line]
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections
