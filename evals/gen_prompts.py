# ruff: noqa: E501  (the published prompt templates and EVIDENCE are kept verbatim, unwrapped)
"""Prompt profiles for the generation-only bake-off (evals/gen_only_eval.py).

Each model is prompted in the format it was trained on, because the point is
to measure what the model can generate, and a text-to-SQL specialist prompted
in someone else's format under-reports itself:

- `current`: the pipeline's own system prompt and user prompt, unchanged
  (`ledgerql.generate`), for the Qwen3-30B baseline and as a control.
- `omnisql`: OmniSQL's published template (seeklhy/OmniSQL-32B model card),
  DDL schema with sample values in comments, one user message, no system
  prompt. It documents SQLite as its only supported dialect, so the template
  says SQLite; DuckDB syntax is stated as external knowledge, which the card
  says goes in the question slot.
- `xiyan`: XiYanSQL-QwenCoder's published template (model card), schema in
  M-Schema (XGenerationLab/M-Schema `to_mschema`), dialect "PostgreSQL" (its
  card lists SQLite/PostgreSQL/MySQL; DuckDB is PostgreSQL-like), one user
  message.

Native formats carry the same domain notes as docs/schema.md via EVIDENCE, so
the comparison is not one of information. The schema itself is introspected
from the live database, not parsed from the markdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb

from ledgerql import generate

# Order in which tables are presented; absent ones are skipped.
TABLE_ORDER = [
    "companies",
    "filings",
    "financial_facts",
    "v_revenue",
    "v_net_income",
    "v_total_assets",
    "v_cash",
]
PRIMARY_KEYS = {"companies": {"cik"}, "filings": {"adsh"}}
FOREIGN_KEYS = [("filings", "cik", "companies", "cik")]
COLUMN_COMMENTS = {("financial_facts", "qtrs"): "4 = full fiscal year, 0 = instant (balance sheet)"}
EXAMPLES_PER_COLUMN = 3

# The narrative notes from docs/schema.md that are not table structure.
EVIDENCE = """\
The database is DuckDB: write one PostgreSQL-compatible SELECT statement.
Coverage: S&P 500 constituents (pinned snapshot), 8 quarters of SEC filings (2024q3-2026q2), annual figures only (10-K filings, fiscal-year period).
companies has one canonical ticker per CIK: dual-class shares (GOOGL/GOOG, FOXA/FOX, NWSA/NWS) appear only under the first-listed ticker (GOOGL, FOXA, NWSA).
filings has one row per SEC submission of any form type; fiscal_year and fiscal_period can be NULL for non-10-K forms.
financial_facts is long format: one row per reported numeric fact from a 10-K's primary statements, for the filing's own fiscal-year period, consolidated and non-dimensional; only plain 10-K with fp = 'FY' (no 10-K/A or 10-KT). uom may be USD, shares, pure or vote. qtrs is 4 for a full fiscal year and 0 for an instant (e.g. a balance sheet). A tag absent for a company and year means "not reported under a known tag": never treat absence as zero.
Concept views v_revenue (qtrs=4; tags RevenueFromContractWithCustomerExcludingAssessedTax, RevenueFromContractWithCustomerIncludingAssessedTax, Revenues, SalesRevenueNet), v_net_income (qtrs=4; NetIncomeLoss, ProfitLoss), v_total_assets (qtrs=0; Assets) and v_cash (qtrs=0; CashAndCashEquivalentsAtCarryingValue, CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents) pick the first tag present per company per fiscal year. Their columns: cik, ticker, name, fiscal_year, fiscal_period, period_end_date, value, uom, source_tag.
Bank holding companies (e.g. JPMorgan) generally have no v_revenue row: absence, not zero."""

OMNISQL_TEMPLATE = """\
Task Overview:
You are a data science expert. Below, you are provided with a database schema and a natural language question. Your task is to understand the schema and generate a valid SQL query to answer the question.

Database Engine:
SQLite

Database Schema:
{db_details}
This schema describes the database's structure, including tables, columns, primary keys, foreign keys, and any relevant relationships or constraints.

Question:
{question}

Instructions:
- Make sure you only output the information that is asked in the question. If the question asks for a specific column, make sure to only include that column in the SELECT clause, nothing more.
- The generated query should return all of the information asked in the question without any missing or extra information.
- Before generating the final SQL query, please think through the steps of how to write the query.

Output Format:
In your answer, please enclose the generated SQL query in a code block:
```
-- Your SQL query
```

Take a deep breath and think step by step to find the correct SQL query."""

XIYAN_TEMPLATE = """\
你是一名{dialect}专家，现在需要阅读并理解下面的【数据库schema】描述，以及可能用到的【参考信息】，并运用{dialect}知识生成sql语句回答【用户问题】。
【用户问题】
{question}

【数据库schema】
{db_schema}

【参考信息】
{evidence}

【用户问题】
{question}

```sql"""

PROFILES = ("current", "omnisql", "xiyan")


@dataclass
class Column:
    name: str
    type: str
    examples: list[str] = field(default_factory=list)
    primary_key: bool = False
    comment: str = ""


@dataclass
class Table:
    name: str
    kind: str  # "table" | "view"
    columns: list[Column]


@dataclass
class SchemaInfo:
    tables: list[Table]
    foreign_keys: list[tuple[str, str, str, str]] = field(default_factory=list)


def introspect(db_path: str) -> SchemaInfo:
    """Tables, column types, sample values and keys from the live database.
    Sample values are the most frequent per column, ties by value: representative
    and reproducible, where DISTINCT ... LIMIT is neither."""
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        kinds = dict(
            con.execute("SELECT table_name, table_type FROM information_schema.tables").fetchall()
        )
        tables = []
        for name in TABLE_ORDER:
            if name not in kinds:
                continue
            columns = []
            for col_name, col_type, *_ in con.execute(f'DESCRIBE "{name}"').fetchall():
                examples = [
                    str(v[0])
                    for v in con.execute(
                        f'SELECT "{col_name}" FROM "{name}" WHERE "{col_name}" IS NOT NULL '
                        f"GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT {EXAMPLES_PER_COLUMN}"
                    ).fetchall()
                ]
                columns.append(
                    Column(
                        name=col_name,
                        type=col_type,
                        examples=examples,
                        primary_key=col_name in PRIMARY_KEYS.get(name, ()),
                        comment=COLUMN_COMMENTS.get((name, col_name), ""),
                    )
                )
            tables.append(
                Table(name=name, kind="view" if kinds[name] == "VIEW" else "table", columns=columns)
            )
    finally:
        con.close()
    present = {t.name for t in tables}
    fks = [fk for fk in FOREIGN_KEYS if fk[0] in present and fk[2] in present]
    return SchemaInfo(tables=tables, foreign_keys=fks)


def _mschema_examples(col: Column) -> list[str]:
    # Mirrors XGenerationLab/M-Schema `single_table_mschema`.
    examples = col.examples[:EXAMPLES_PER_COLUMN]
    if not examples:
        return []
    if col.type.upper() in ("DATE", "TIME", "DATETIME", "TIMESTAMP"):
        return [examples[0]]
    longest = max(len(s) for s in examples)
    if longest > 50:
        return []
    if longest > 20:
        return [examples[0]]
    return examples


def to_mschema(schema: SchemaInfo, db_id: str = "ledgerql") -> str:
    out = [f"【DB_ID】 {db_id}", "【Schema】"]
    for table in schema.tables:
        out.append(f"# Table: {table.name}")
        lines = []
        for col in table.columns:
            line = f"({col.name}:{col.type.upper()}"
            if col.comment:
                line += f", {col.comment}"
            if col.primary_key:
                line += ", Primary Key"
            examples = _mschema_examples(col)
            if examples:
                line += f", Examples: [{', '.join(examples)}]"
            lines.append(line + ")")
        out += ["[", ",\n".join(lines), "]"]
    if schema.foreign_keys:
        out.append("【Foreign keys】")
        out += [f"{t}.{c}={rt}.{rc}" for t, c, rt, rc in schema.foreign_keys]
    return "\n".join(out)


def to_ddl(schema: SchemaInfo) -> str:
    """CREATE TABLE statements with sample values in comments, the layout
    OmniSQL's card describes ("database values ... in DDLs with SQL comments")."""
    statements = []
    for table in schema.tables:
        items: list[tuple[str, str]] = []
        for col in table.columns:
            shown = col.examples[:EXAMPLES_PER_COLUMN]
            comment = f"example: [{', '.join(shown)}]" if shown else ""
            if col.comment:
                comment = f"{col.comment}; {comment}" if comment else col.comment
            items.append((f"{col.name} {col.type}", comment))
        pks = [c.name for c in table.columns if c.primary_key]
        if pks:
            items.append((f"PRIMARY KEY ({', '.join(pks)})", ""))
        for t, c, rt, rc in schema.foreign_keys:
            if t == table.name:
                items.append((f"FOREIGN KEY ({c}) REFERENCES {rt} ({rc})", ""))
        lines = []
        for i, (text, comment) in enumerate(items):
            sep = "," if i < len(items) - 1 else ""
            lines.append(f"    {text}{sep}" + (f" -- {comment}" if comment else ""))
        statements.append(f"CREATE TABLE {table.name} (\n" + "\n".join(lines) + "\n);")
    return "\n".join(statements)


def build_messages(
    profile: str,
    question: str,
    *,
    schema: SchemaInfo,
    schema_context: str,
    entity_hint: str = "",
) -> list[dict]:
    """`entity_hint` (empty by default) rides where each format keeps external knowledge:
    after the question in the pipeline's prompt, in the question slot beside EVIDENCE for
    OmniSQL, and in the evidence slot for XiYan. Empty, every profile is unchanged."""
    if profile == "current":
        return [
            {"role": "system", "content": generate.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": generate.build_prompt(question, schema_context, entity_hint),
            },
        ]
    if profile == "omnisql":
        body = OMNISQL_TEMPLATE.format(
            db_details=to_ddl(schema), question=f"{EVIDENCE}\n{entity_hint}{question}"
        )
        return [{"role": "user", "content": body}]
    if profile == "xiyan":
        body = XIYAN_TEMPLATE.format(
            dialect="PostgreSQL",
            question=question,
            db_schema=to_mschema(schema),
            evidence=EVIDENCE + (f"\n{entity_hint.rstrip()}" if entity_hint else ""),
        )
        return [{"role": "user", "content": body}]
    raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")


_BLOCK_RE = re.compile(r"```[ \t]*(?:sql|SQL)?[ \t]*\n(.*?)```", re.DOTALL)


def extract_sql(text: str) -> str:
    """The SQL in a model reply. A reasoning model may draft several queries;
    the last complete fenced block is its answer. Otherwise fall back to the
    pipeline's own fence stripping (a bare statement, or one followed only by
    a closing fence, as XiYan's template elicits)."""
    blocks = _BLOCK_RE.findall(text)
    if blocks:
        return blocks[-1].strip()
    return generate._strip_fences(text)
