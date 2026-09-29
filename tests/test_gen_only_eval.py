import json
import time

import duckdb
import httpx
import pytest

from evals import gen_only_eval
from evals.gen_only_eval import (
    Generation,
    HttpGenerator,
    run,
    select_cases,
    smoke_cases,
    smoke_ok,
    summarize,
    write_outputs,
)
from evals.gen_prompts import Column, SchemaInfo, Table
from ledgerql import generate

RIGHT = "SELECT revenue FROM companies WHERE cik = 1"
WRONG = "SELECT revenue FROM companies WHERE cik = 2"

CASES = [
    {
        "id": "A1",
        "tier": "lookup",
        "expected": "ANSWER",
        "question": "What is company 1's revenue?",
        "gold_sql": RIGHT,
        "compare": "scalar",
    },
    {"id": "X1", "tier": "adversarial", "expected": "ABSTAIN", "question": "Drop everything"},
    {
        "id": "W1",
        "tier": "lookup",
        "expected": "ANSWER_WITH_ASSUMPTION",
        "question": "an assumption case",
        "gold_sql": RIGHT,
        "compare": "scalar",
    },
    {
        "id": "A2",
        "tier": "aggregation",
        "expected": "ANSWER",
        "question": "What is company 2's revenue?",
        "gold_sql": WRONG,
        "compare": "scalar",
    },
]
CASES_BY_ID = {c["id"]: c for c in CASES}
SCHEMA = SchemaInfo(tables=[Table("companies", "table", [Column("cik", "INTEGER")])])


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE companies (cik INTEGER, revenue INTEGER)")
    con.execute("INSERT INTO companies VALUES (1, 100), (2, 999)")
    con.close()
    return path


def _by_seed(*replies_by_index):
    """A fake model: candidate i (seed = OLLAMA_SEED + i) replies replies_by_index[i]."""

    def fake(messages, seed):
        return Generation(text=replies_by_index[seed - generate.OLLAMA_SEED], finish_reason="stop")

    return fake


def _run(db, fake, cases=CASES[:1], profile="current", n=5, **kw):
    return run(cases, profile, fake, db_path=db, schema=SCHEMA, schema_context="CTX", n=n, **kw)


def test_only_answer_expected_cases_are_selected():
    assert [c["id"] for c in select_cases(CASES)] == ["A1", "A2"]


def test_a_correct_majority_wins_the_vote_and_is_scored_correct(db):
    fake = _by_seed(RIGHT, RIGHT, RIGHT, WRONG, "```sql\n" + WRONG + "\n```")
    [rec] = _run(db, fake)
    assert rec["id"] == "A1" and rec["tier"] == "lookup"
    assert rec["confidence"] == pytest.approx(0.6)
    assert rec["execution_correct"] is True
    assert rec["reason_code"] is None
    assert len(rec["candidates"]) == 5


def test_a_wrong_majority_with_a_correct_minority_is_a_selection_failure(db):
    fake = _by_seed(RIGHT, RIGHT, WRONG, WRONG, WRONG)
    [rec] = _run(db, fake)
    assert rec["execution_correct"] is False
    stats = summarize([rec], CASES_BY_ID, db)
    assert stats["passn"]["overall"]["pass_at_1"] == 0.0
    assert stats["passn"]["overall"]["pass_at_n"] == 1.0  # a correct one was generated


def test_every_candidate_keeps_its_raw_reply_and_finish_reason(db):
    reply = "Thinking...\n```sql\n" + RIGHT + "\n```"
    [rec] = _run(db, lambda messages, seed: Generation(reply, "length"), n=2)
    cand = rec["candidates"][0]
    assert cand["raw"] == reply and cand["finish_reason"] == "length"
    assert cand["sql"] == RIGHT  # extracted, so passn_scoring can re-execute it


def test_unusable_replies_are_logged_not_dropped_and_do_not_crash(db):
    fake = _by_seed("", "NOT SQL AT ALL(((", RIGHT, "DROP TABLE companies", RIGHT)
    [rec] = _run(db, fake)
    assert len(rec["candidates"]) == 5
    assert [c["guard_ok"] for c in rec["candidates"]] == [False, False, True, False, True]
    assert rec["execution_correct"] is True  # the two usable candidates agree


def test_a_failed_model_call_is_recorded_as_an_error_candidate(db):
    def fake(messages, seed):
        if seed == generate.OLLAMA_SEED:
            raise httpx.ReadTimeout("slow")
        return Generation(text=RIGHT, finish_reason="stop")

    [rec] = _run(db, fake)
    first = rec["candidates"][0]
    assert first["finish_reason"] == "error:ReadTimeout" and first["sql"] == ""
    assert rec["execution_correct"] is True  # the other four still vote


def test_no_usable_candidate_yields_a_reason_code_and_an_incorrect_case(db):
    [rec] = _run(db, lambda messages, seed: Generation("", "stop"))
    assert rec["execution_correct"] is False
    assert rec["reason_code"] is not None and rec["confidence"] == 0.0


def test_the_model_is_called_once_per_candidate_with_the_pipelines_seeds(db):
    seen = []

    def fake(messages, seed):
        seen.append((messages[-1]["content"], seed))
        return Generation(RIGHT, "stop")

    _run(db, fake, cases=[CASES[0], CASES[3]])
    assert len(seen) == 10
    assert sorted({s for _, s in seen}) == [generate.OLLAMA_SEED + i for i in range(5)]
    assert {q for q, _ in seen} == {
        generate.build_prompt(CASES[0]["question"], "CTX"),
        generate.build_prompt(CASES[3]["question"], "CTX"),
    }


def test_records_come_back_in_case_order_whatever_order_calls_finish(db):
    def fake(messages, seed):
        if "company 1" in messages[-1]["content"]:
            time.sleep(0.05)  # the first case finishes last
        return Generation(RIGHT, "stop")

    recs = _run(db, fake, cases=[CASES[0], CASES[3]], concurrency=8)
    assert [r["id"] for r in recs] == ["A1", "A2"]


def test_summary_counts_candidate_outcomes_and_reports_pass_at_1_and_n(db):
    fake = _by_seed(RIGHT, "SELECT nope FROM companies", "", "SELECT * FROM stg_num", RIGHT)
    recs = _run(db, fake)
    stats = summarize(recs, CASES_BY_ID, db)
    census = stats["candidates"]
    assert census["total"] == 5 and census["executed"] == 2
    assert census["guard_rejected"] == 3  # unknown column, empty, stg_num not allowlisted
    assert stats["passn"]["overall"]["total"] == 1


def test_smoke_takes_the_first_answer_case_of_each_of_the_first_k_tiers():
    assert [c["id"] for c in smoke_cases(select_cases(CASES), 2)] == ["A1", "A2"]
    assert [c["id"] for c in smoke_cases(select_cases(CASES), 1)] == ["A1"]


def test_smoke_passes_when_all_but_at_most_one_case_execute_and_return_rows():
    ok = {"candidates": [{"guard_ok": True, "exec_error": None, "n_rows": 1}]}
    bad = {"candidates": [{"guard_ok": False, "exec_error": None, "n_rows": None}]}
    assert smoke_ok([ok, ok, ok])
    assert smoke_ok([ok, ok, bad])
    assert not smoke_ok([ok, bad, bad])
    assert not smoke_ok([bad])  # k=1 tolerates nothing


def test_http_generator_posts_the_chat_payload_and_returns_text_and_finish_reason():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "SELECT 1"}, "finish_reason": "length"}]}
        )

    client = httpx.Client(base_url="http://vllm", transport=httpx.MockTransport(handler))
    gen = HttpGenerator(model="m/x", temperature=0.7, max_tokens=2048, http=client)
    out = gen([{"role": "user", "content": "hi"}], seed=43)
    assert out == Generation(text="SELECT 1", finish_reason="length")
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"] == {
        "model": "m/x",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.7,
        "seed": 43,
        "max_tokens": 2048,
    }


def test_write_outputs_writes_records_and_a_summary(db, tmp_path):
    recs = _run(db, _by_seed(RIGHT, RIGHT, RIGHT, RIGHT, RIGHT))
    out = tmp_path / "out"
    stats = summarize(recs, CASES_BY_ID, db)
    write_outputs(recs, stats, out, profile="current", meta={"model": "m/x"})
    lines = (out / "gen_only_current.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["A1"]
    summary = json.loads((out / "gen_only_current_summary.json").read_text())
    assert summary["meta"]["model"] == "m/x" and summary["passn"]["overall"]["pass_1"] == 1
    assert "pass@1" in (out / "gen_only_current.md").read_text()


def test_module_exposes_the_profiles_the_job_scripts_pass():
    assert set(gen_only_eval.PROFILES) == {"current", "omnisql", "xiyan"}
