"""The evaluator and the pipeline must verify an answer on the SAME inputs.

The first 30B pipeline run reported a 14.3% hallucination rate that was the evaluator verifying the
framing's year and day labels without the context the pipeline had given the verifier: duplicated
logic, different inputs (the same class of bug the repo has hit before). The evaluator stays an
independent call site, but for every answer the pipeline gave, whatever the pipeline accepted the
evaluator must accept, and the framing the evaluator recomputes must be the framing in the answer.
Any disagreement fails here, loudly, by record id."""

import json
from pathlib import Path

import pytest

from evals import run_eval
from tests.support import BRIDGES2_HINT, require_fixture

DB = "tests/fixtures/eval_fixture.duckdb"
GOLD = {c["id"]: c for c in (json.loads(x) for x in open("evals/gold_v3.jsonl"))}
RUNS = [
    "reports/eval_bridges2_qwen25_32b_pipeline_47314855.jsonl",
    "reports/eval_bridges2_qwen3_30b_pipeline_47314853_PARTIAL.jsonl",
]
MSFT_SQL = "SELECT value FROM v_net_income WHERE ticker='MSFT' ORDER BY fiscal_year DESC LIMIT 1"
MSFT_Q = "What was Microsoft's net income in its most recent fiscal year on record?"
FRAMED = (
    "The value is 101,832,000,000.0. The most recent fiscal year on record, fiscal year 2025 "
    "(period ended June 30, 2025), was used."
)


def problems(answer, rows=((101832000000.0,),), sql=MSFT_SQL, question=MSFT_Q):
    return run_eval.check_pipeline_agreement(
        answer, ["value"], [tuple(r) for r in rows], sql, question, DB
    )


def test_a_consistent_answer_has_no_problems():
    assert problems(FRAMED) == []
    assert problems("The value is 391,035,000,000.0.", rows=[(391035000000.0,)],
                    sql="SELECT value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2024",
                    question="What was Apple's revenue in fiscal year 2024?") == []  # fmt: skip


def test_an_answer_whose_framing_is_not_the_one_the_evaluator_recomputes_is_a_problem():
    tampered = FRAMED.replace("June 30, 2025", "June 29, 2025")
    found = problems(tampered)
    assert any(
        "framing" in p for p in found
    )  # different framing inputs, caught before verification
    assert any("verif" in p for p in found)  # and the stated day is not a label the framing owns


def test_a_number_that_is_not_in_the_result_is_a_problem():
    assert any(
        "verif" in p for p in problems(FRAMED.replace("101,832,000,000.0", "999,999,000,000.0"))
    )


@pytest.mark.parametrize("path", RUNS)
def test_for_every_answered_record_in_a_real_pipeline_run_the_evaluator_agrees_with_the_pipeline(
    path,
):
    """The pipeline gave each of these answers only after verifying it. Re-verified by the
    evaluator on the recorded answer, result and recomputed framing labels, none may disagree."""
    require_fixture(path, BRIDGES2_HINT)
    records = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    answered = [r for r in records if r.get("answer") is not None]
    assert len(answered) >= 30  # the check is not vacuous
    disagreements = {}
    for r in answered:
        found = run_eval.check_pipeline_agreement(
            r["answer"], r["columns"], [tuple(x) for x in r["rows"]],
            r.get("generated_sql"), GOLD[r["id"]]["question"], DB,
        )  # fmt: skip
        if found:
            disagreements[r["id"]] = found
    assert (
        not disagreements
    ), f"evaluator and pipeline disagree on {len(disagreements)} records: {disagreements}"


def test_run_eval_fails_loudly_when_it_disagrees_with_an_answer_the_pipeline_gave(
    monkeypatch, tmp_path
):
    import duckdb

    gold = tmp_path / "gold.jsonl"
    case = {"id": "L03", "tier": "lookup", "expected": "ANSWER_WITH_ASSUMPTION", "question": MSFT_Q,
            "gold_sql": None, "compare": "none"}  # fmt: skip
    gold.write_text(json.dumps(case) + "\n")
    duckdb.connect(str(tmp_path / "x.duckdb")).close()
    bad = FRAMED.replace(
        "June 30, 2025", "June 29, 2025"
    )  # the pipeline "answered" with an altered label

    def fake_ask(question, db_path=None):
        return {"sql": MSFT_SQL, "error": None, "answer": bad, "columns": ["value"],
                "rows": [(101832000000.0,)], "truncated": False, "reason_code": None,
                "guardrail_events": [], "confidence": 1.0, "repair": None, "candidates": None,
                "refusal": None, "state": "ANSWER_WITH_ASSUMPTION",
                "assumptions": ["x"]}  # fmt: skip

    monkeypatch.setattr(run_eval.pipeline, "ask", fake_ask)
    monkeypatch.setattr(
        run_eval, "write_reports", lambda s, d: (tmp_path / "a.md", tmp_path / "b.jsonl")
    )
    summary = run_eval.run(gold, DB)
    assert summary["verifier_disagreements"] == {"L03": summary["verifier_disagreements"]["L03"]}
    monkeypatch.setattr(run_eval, "run", lambda *a, **k: summary)
    assert (
        run_eval.main(["--reports-dir", str(tmp_path), "--gold", str(gold)])
        == run_eval.DISAGREEMENT_EXIT_CODE
    )
