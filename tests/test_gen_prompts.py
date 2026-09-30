import json

import duckdb
import pytest

from evals import gen_prompts
from evals.gen_prompts import (
    Column,
    SchemaInfo,
    Table,
    build_messages,
    extract_sql,
    introspect,
    to_ddl,
    to_mschema,
)
from ledgerql import generate

SCHEMA = SchemaInfo(
    tables=[
        Table(
            name="companies",
            kind="table",
            columns=[
                Column("cik", "INTEGER", ["320193", "789019", "1018724", "999"], primary_key=True),
                Column("ticker", "VARCHAR", ["AAPL", "MSFT"]),
                Column(
                    "name", "VARCHAR", ["A very long company name that is over fifty chars long"]
                ),
            ],
        ),
        Table(
            name="filings",
            kind="table",
            columns=[
                Column("cik", "INTEGER", ["320193"]),
                Column("filed_date", "DATE", ["2024-11-01", "2024-10-31"]),
                Column("form", "VARCHAR", ["Twenty-two characters!!", "10-K"]),
            ],
        ),
    ],
    foreign_keys=[("filings", "cik", "companies", "cik")],
)


def test_extract_sql_takes_a_plain_statement_unchanged():
    assert extract_sql("SELECT 1") == "SELECT 1"


def test_extract_sql_takes_the_last_complete_code_block_after_reasoning():
    text = (
        "Let me think. A first idea:\n```sql\nSELECT wrong FROM t\n```\n"
        "Actually the right one is:\n```sql\nSELECT right FROM t\n```\nDone."
    )
    assert extract_sql(text) == "SELECT right FROM t"


def test_extract_sql_handles_a_bare_fence_and_a_lone_closing_fence():
    # XiYan's template ends with an opening ```sql, so the reply is the SQL
    # followed only by the closing fence.
    assert extract_sql("```\n-- Your SQL query\nSELECT 2\n```") == "-- Your SQL query\nSELECT 2"
    assert extract_sql("SELECT 3\n```") == "SELECT 3"


def test_extract_sql_of_empty_text_is_empty():
    assert extract_sql("") == ""


def test_to_mschema_follows_the_published_m_schema_layout():
    text = to_mschema(SCHEMA, db_id="ledgerql")
    assert text.startswith("【DB_ID】 ledgerql\n【Schema】\n# Table: companies\n[\n")
    # types upper-cased, primary key flagged, at most 3 examples
    assert "(cik:INTEGER, Primary Key, Examples: [320193, 789019, 1018724])," in text
    # a value longer than 50 chars drops the examples altogether
    assert "(name:VARCHAR)" in text
    # dates keep a single example; 20-50 char values keep only the first
    assert "(filed_date:DATE, Examples: [2024-11-01])," in text
    assert "(form:VARCHAR, Examples: [Twenty-two characters!!])" in text
    assert text.endswith("【Foreign keys】\nfilings.cik=companies.cik")


def test_to_ddl_renders_create_table_with_example_comments_and_keys():
    ddl = to_ddl(SCHEMA)
    assert "CREATE TABLE companies (" in ddl
    assert "cik INTEGER, -- example: [320193, 789019, 1018724]" in ddl
    assert "PRIMARY KEY (cik)" in ddl
    assert "FOREIGN KEY (cik) REFERENCES companies (cik)" in ddl


def test_current_profile_is_exactly_the_pipelines_own_prompt():
    msgs = build_messages("current", "the q", schema=SCHEMA, schema_context="CTX")
    assert msgs == [
        {"role": "system", "content": generate.SYSTEM_PROMPT},
        {"role": "user", "content": generate.build_prompt("the q", "CTX")},
    ]


def test_omnisql_profile_is_one_user_message_in_the_published_template():
    question = "Q-MARKER-7 what is revenue?"
    msgs = build_messages("omnisql", question, schema=SCHEMA, schema_context="CTX")
    assert [m["role"] for m in msgs] == ["user"]  # no system prompt: not its format
    body = msgs[0]["content"]
    assert body.startswith("Task Overview:\nYou are a data science expert.")
    assert "Database Engine:\nSQLite\n" in body  # its only supported dialect
    assert "CREATE TABLE companies (" in body
    assert "Question:\n" in body and question in body
    # external knowledge rides in the question slot, ahead of the question
    assert body.index(gen_prompts.EVIDENCE.splitlines()[0]) < body.index(question)
    assert body.endswith("Take a deep breath and think step by step to find the correct SQL query.")


def test_xiyan_profile_is_one_user_message_with_m_schema_in_postgres_mode():
    msgs = build_messages("xiyan", "the q", schema=SCHEMA, schema_context="CTX")
    assert [m["role"] for m in msgs] == ["user"]
    body = msgs[0]["content"]
    assert body.startswith("你是一名PostgreSQL专家")
    assert "【DB_ID】 ledgerql" in body and "# Table: companies" in body
    assert body.count("the q") == 2  # the published template states the question twice
    assert gen_prompts.EVIDENCE in body
    assert body.endswith("```sql")


def test_unknown_profile_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError, match="profile"):
        build_messages("nope", "q", schema=SCHEMA, schema_context="CTX")


def test_evidence_carries_the_schema_notes_the_current_context_gives():
    # The native formats must not be starved of the domain notes the baseline
    # sees in docs/schema.md, or the comparison measures information, not model.
    for needle in ("GOOGL", "never treat absence as zero", "v_revenue", "qtrs", "DuckDB"):
        assert needle in gen_prompts.EVIDENCE


def test_introspect_reads_columns_examples_and_keys_from_the_database(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE companies (cik INTEGER, ticker VARCHAR)")
    con.execute("INSERT INTO companies VALUES (1, 'AAA'), (2, 'BBB'), (3, 'CCC'), (4, 'DDD')")
    con.execute("CREATE VIEW v_revenue AS SELECT cik, ticker FROM companies")
    con.close()

    schema = introspect(db)
    names = [t.name for t in schema.tables]
    assert names == ["companies", "v_revenue"]  # absent allowed tables are skipped
    companies = schema.tables[0]
    assert companies.kind == "table" and schema.tables[1].kind == "view"
    cik = companies.columns[0]
    assert (cik.name, cik.type, cik.primary_key) == ("cik", "INTEGER", True)
    assert len(cik.examples) == 3 and set(cik.examples) <= {"1", "2", "3", "4"}
    assert all(not c.primary_key for c in schema.tables[1].columns)


@pytest.mark.parametrize("profile", gen_prompts.PROFILES)
def test_entity_hint_reaches_every_profile_and_is_absent_by_default(profile):
    hint = "Companies named in the question: HINT-MARKER\n\n"
    plain = build_messages(profile, "the q", schema=SCHEMA, schema_context="CTX")
    hinted = build_messages(profile, "the q", schema=SCHEMA, schema_context="CTX", entity_hint=hint)
    assert "HINT-MARKER" not in json.dumps(plain)
    assert "HINT-MARKER" in json.dumps(hinted)
    assert plain == build_messages(
        profile, "the q", schema=SCHEMA, schema_context="CTX", entity_hint=""
    )
