from evals import replay_refusals as RR

DB = "tests/fixtures/eval_fixture.duckdb"


def rec(cid, reason, answer=None):
    return {"id": cid, "answer": answer, "reason_code": reason, "question": ""}


def test_only_abstains_get_a_refusal_and_it_is_graded_against_the_cases_rubric_items():
    questions = {"U06": "Which fiscal period does Tesla's most recent 8-K filing correspond to?",
                 "L01": "What was Apple's revenue in fiscal year 2024?"}  # fmt: skip
    records = [rec("U06", "NO_DATA"), rec("L01", None, answer="391 billion")]
    out = RR.replay(records, questions, db_path=DB)
    assert [r["id"] for r in out] == ["U06"]  # an answered record has no refusal to grade
    row = out[0]
    assert "8-K" in row["refusal"] and row["items"][0]["passed"] is True


def test_a_refusal_with_the_wrong_explanation_fails_its_item():
    questions = {"H04": "Break down Apple's fiscal 2024 revenue by geographic region."}
    out = RR.replay([rec("H04", "OUT_OF_SCOPE")], questions, db_path=DB)
    # the documented-gap text takes over, so the generic OUT_OF_SCOPE text never wrongly passes
    assert out[0]["items"][0]["passed"] is True
    out = RR.replay([rec("H04", "AMBIGUOUS")], {"H04": "Tell me about Apple in 2024"}, db_path=DB)
    assert out[0]["items"][0]["passed"] is False  # a generic sentence does not state the gap


def test_cases_without_rubric_items_are_not_reported():
    out = RR.replay([rec("L01", "NO_DATA")], {"L01": "What was Apple's revenue?"}, db_path=DB)
    assert out == []
