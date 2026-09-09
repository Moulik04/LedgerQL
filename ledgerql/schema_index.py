"""Stage 2: schema retrieval.

Phase 2 injects the full analyst schema into every generation prompt --
the schema is small (3 tables + 4 views) so there's nothing to
selectively retrieve yet. Reads docs/schema.md and keeps the file's
intro (the title and any paragraphs before the first H2 heading --
notably the Coverage paragraph, which states the fiscal years and
annual-only granularity a model needs to reason about time-based
questions) plus whole H2 sections that define tables/views (companies,
filings, financial_facts, Concept views), dropping any H2 sections that
are pure narrative (e.g., notes or examples with their own headings) to
save tokens without losing schema structure.
"""

from pathlib import Path

SCHEMA_MD_PATH = Path(__file__).resolve().parent.parent / "docs" / "schema.md"

KEPT_SECTIONS = {"companies", "filings", "financial_facts", "concept views"}


def get_schema_context(schema_md_path: Path = SCHEMA_MD_PATH) -> str:
    text = schema_md_path.read_text()
    intro = _leading_intro(text)
    sections = _split_into_h2_sections(text)
    kept = [body for title, body in sections if title.strip().lower() in KEPT_SECTIONS]
    return "\n\n".join([p for p in (intro, *kept) if p]).strip()


def _leading_intro(text: str) -> str:
    """Everything before the first H2 heading (the file's title and intro)."""
    lines = text.splitlines()
    intro_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        intro_lines.append(line)
    return "\n".join(intro_lines).strip()


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
