import json

import duckdb

from evals import heldout_gold_check as C

DB = "tests/fixtures/eval_fixture.duckdb"
V3 = {c["id"]: c for c in (json.loads(x) for x in open("evals/gold_v3.jsonl"))}


def case(**kw):
    base = {"id": "H01", "expected": "ANSWER_WITH_ASSUMPTION", "compare": "scalar",
            "gold_sql": "SELECT 1", "question": "q"}  # fmt: skip
    return {**base, **kw}


def test_a_case_with_no_alternatives_has_no_problems():
    assert C.check_case(case()) == []


def test_a_prose_alternative_is_rejected_because_the_comparator_cannot_credit_it():
    """The dev gold's M02 says 'ANSWER_WITH_ASSUMPTION using total_assets instead, if stated'.
    Nothing can score that sentence: both models took it and scored 0 (KNOWN_GOLD_ISSUES)."""
    problems = C.check_case(V3["M02"])
    assert any("prose" in p and "total_assets" in p for p in problems)


def test_abstain_alternatives_are_machine_parsed_so_they_are_allowed():
    assert C.check_case(case(accept_alternatives=["ABSTAIN:AMBIGUOUS", "ABSTAIN:NO_DATA"])) == []
    assert C.check_case(case(accept_alternatives=["ABSTAIN: probably fine"]))  # not a reason code


def test_an_answer_alternative_needs_a_description_executable_sql_and_a_compare_mode():
    good = {"describes": "by total assets, if stated", "gold_sql": "SELECT 2", "compare": "scalar"}
    assert C.check_case(case(alternatives=[good])) == []
    for missing in ("describes", "gold_sql", "compare"):
        bad = {k: v for k, v in good.items() if k != missing}
        assert any(missing in p for p in C.check_case(case(alternatives=[bad])))
    assert any(
        "compare" in p for p in C.check_case(case(alternatives=[{**good, "compare": "vibes"}]))
    )


def test_alternatives_must_really_execute_when_a_database_is_given():
    con = duckdb.connect(DB, read_only=True, config={"enable_external_access": "false"})
    ok = {"describes": "x", "gold_sql": "SELECT name FROM companies LIMIT 1", "compare": "scalar"}
    broken = {**ok, "gold_sql": "SELECT nope FROM companies"}
    assert C.check_case(case(alternatives=[ok]), con) == []
    assert any("does not execute" in p for p in C.check_case(case(alternatives=[broken]), con))
    con.close()


def test_the_dev_gold_r07_alternative_has_executable_sql_and_lacks_only_the_new_describes_field():
    # R07's V9 alternative predates the `describes` field; dev gold is frozen, held-out gold is not
    problems = C.check_case(V3["R07"])
    assert problems == ["alternatives[0] is missing `describes`"]


def test_check_file_reports_every_failing_case_and_exits_nonzero(tmp_path):
    f = tmp_path / "heldout_v1.jsonl"
    f.write_text(
        json.dumps(case()) + "\n" + json.dumps(case(id="H02", accept_alternatives=["prose"])) + "\n"
    )
    out = C.check_file(f)
    assert list(out) == ["H02"]
    assert C.main([str(f)]) == 1
    f.write_text(json.dumps(case()) + "\n")
    assert C.main([str(f)]) == 0
