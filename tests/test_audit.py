import json

import duckdb

from ledgerql import audit


def test_write_record_returns_a_uuid_id(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    record_id = audit.write_record({"question": "q"}, log_path=log_path)
    assert isinstance(record_id, str)
    assert len(record_id) == 36  # uuid4 string length, incl. hyphens


def test_write_record_appends_id_and_timestamp(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    record_id = audit.write_record({"question": "q"}, log_path=log_path)
    line = json.loads(log_path.read_text().splitlines()[0])
    assert line["id"] == record_id
    assert "timestamp" in line
    assert line["question"] == "q"


def test_write_record_preserves_list_fields(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit.write_record({"guardrail_events": ["single_statement", "cost_limit"]}, log_path=log_path)
    line = json.loads(log_path.read_text().splitlines()[0])
    assert line["guardrail_events"] == ["single_statement", "cost_limit"]


def test_write_record_appends_not_overwrites(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit.write_record({"question": "first"}, log_path=log_path)
    audit.write_record({"question": "second"}, log_path=log_path)
    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["question"] == "first"
    assert json.loads(lines[1])["question"] == "second"


def test_write_record_creates_parent_directory(tmp_path):
    log_path = tmp_path / "nested" / "logs" / "audit.jsonl"
    audit.write_record({"question": "q"}, log_path=log_path)
    assert log_path.exists()


def test_audit_log_readable_via_duckdb(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    audit.write_record(
        {"question": "q", "guardrail_events": ["cost_limit"], "confidence": None},
        log_path=log_path,
    )
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT question, guardrail_events, confidence FROM read_json_auto('{log_path}')"
    ).fetchall()
    assert rows == [("q", ["cost_limit"], None)]
