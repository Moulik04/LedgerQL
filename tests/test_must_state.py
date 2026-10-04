"""answer_must_state: deterministic patterns, a judge that cannot override them, and the rules
for what is gradable (evals/must_state.py)."""

import json

from evals import must_state as M

ITEM = {
    "case": "X1",
    "item": 0,
    "text": "which fiscal year was used",
    "surface": "answer",
    "primary": "pattern",
    "groups": [{"any": [r"(?i)fiscal\s+year\s+(19|20)\d\d", r"(?i)\bFY\s?(19|20)?\d\d"]}],
}


def item(**kw):
    return {**ITEM, **kw}


def test_a_group_passes_when_any_of_its_alternatives_matches_and_a_item_needs_every_group():
    two = item(groups=[{"any": [r"(?i)\bbank"]}, {"any": [r"(?i)absent", r"(?i)missing"]}])
    assert M.pattern_pass(two, "Banks are absent from the revenue view")
    assert not M.pattern_pass(two, "Banks report revenue")  # second group unmet
    assert not M.pattern_pass(two, "Figures are absent")  # first group unmet


def test_patterns_are_case_insensitive_only_when_they_say_so_and_unanchored_otherwise():
    assert M.pattern_pass(ITEM, "In FISCAL YEAR 2024 revenue was high")
    assert M.pattern_pass(ITEM, "That is FY24")
    assert not M.pattern_pass(ITEM, "The fiscal year is not stated")


def test_min_distinct_requires_several_different_matches():
    two_years = item(groups=[{"any": [r"\b(19|20)\d\d\b"], "min_distinct": 2}])
    assert M.pattern_pass(two_years, "Amazon's 2025 figure against Walmart's 2026 figure")
    assert not M.pattern_pass(two_years, "2025 and again 2025")


def test_grading_is_on_the_text_the_user_sees_and_none_means_not_gradable():
    r = M.grade_item(ITEM, "In fiscal year 2025 it was $1")
    assert r.passed is True and r.decided_by == "pattern"
    assert M.grade_item(ITEM, "It was $1").passed is False
    assert M.grade_item(ITEM, None).passed is None  # an abstain has no answer text
    assert M.grade_item(ITEM, "").passed is None


def test_a_refusal_item_is_graded_only_on_refusal_text():
    refusal = item(surface="refusal", groups=[{"any": [r"(?i)8-K"]}])
    assert M.grade_item(refusal, "answer text that mentions 8-K", refusal_text=None).passed is None
    assert M.grade_item(refusal, None, refusal_text="No 8-K filings are loaded").passed is True
    assert M.grade_item(refusal, None, refusal_text="No data").passed is False


def test_the_judge_decides_only_judge_primary_items_and_pattern_items_just_log_it():
    calls = []

    def judge(question, answer, text):
        calls.append(text)
        return True

    pat = M.grade_item(ITEM, "It was $1", judge=judge)  # the pattern fails, the judge says yes
    assert pat.passed is False and pat.decided_by == "pattern" and pat.judge_pass is True
    jp = item(primary="judge", groups=[{"any": [r"(?i)bank"]}])
    r = M.grade_item(jp, "It is a bank", judge=lambda q, a, t: False)
    assert r.passed is False and r.decided_by == "judge" and r.pattern_pass is True
    assert M.grade_item(jp, "whatever", judge=None).passed is None  # no judge, no decision


def test_stated_needs_every_item_and_an_ungradable_item_is_not_a_pass():
    ok, bad, none = (
        M.ItemResult("X", i, p, None, p, "pattern") for i, p in enumerate((True, False, None))
    )
    assert M.stated([ok, ok]) is True
    assert M.stated([ok, bad]) is False
    assert M.stated([ok, none]) is None  # cannot be said to be stated
    assert M.stated([]) is None  # a case with no rubric items is not assessed


def test_the_judge_reply_is_parsed_strictly_yes_no_and_ambiguity_is_none():
    assert M.parse_judge_reply("YES") is True
    assert M.parse_judge_reply("  no.\n") is False
    assert M.parse_judge_reply("Yes, because...") is True
    assert M.parse_judge_reply("maybe") is None
    assert M.parse_judge_reply("") is None


def test_the_committed_patterns_cover_every_rubric_item_of_the_gold_and_compile():
    gold = {}
    for line in open("evals/gold.jsonl"):
        c = json.loads(line)
        if c.get("answer_must_state"):
            gold[c["id"]] = c["answer_must_state"]
    patterns = M.load_patterns()
    assert set(patterns) == set(gold)
    for cid, texts in gold.items():
        assert [i["text"] for i in patterns[cid]] == texts  # one entry per item, in order
        for it in patterns[cid]:
            assert it["surface"] in ("answer", "refusal", "either") and it["primary"] in (
                "pattern",
                "judge",
            )
            M.compile_item(it)  # every regex compiles
    assert sum(len(v) for v in patterns.values()) == 27


def test_calibration_counts_agreement_false_passes_and_false_fails():
    patterns = {"X": [ITEM]}
    records = {"run": [{"id": "X", "answer": "In fiscal year 2024 it was 1", "question": "q"}]}
    labels = [
        {"run": "run", "case": "X", "item": 0, "label": True, "note": ""},
        {"run": "run", "case": "X", "item": 0, "label": False, "note": "disagree"},
    ]
    out = M.calibrate(records, patterns, labels)
    assert out["n"] == 2 and out["agree"] == 1
    assert out["false_pass"] == 1 and out["false_fail"] == 0  # grader True where the label is False
    assert out["disagreements"][0]["note"] == "disagree"


def test_calibration_reports_the_judge_on_its_own_and_skips_unanswered_records():
    patterns = {"X": [ITEM]}
    records = {"run": [{"id": "X", "answer": None, "question": "q"}]}
    labels = [{"run": "run", "case": "X", "item": 0, "label": False, "note": ""}]
    assert M.calibrate(records, patterns, labels)["n"] == 0  # nothing to grade, not a pass
    records = {"run": [{"id": "X", "answer": "It was 1", "question": "q"}]}
    out = M.calibrate(records, patterns, labels, judge=lambda q, a, t: True)
    assert out["judge"]["n"] == 1 and out["judge"]["agree"] == 0  # the judge said yes, the label no


def test_judge_check_reports_recall_and_precision_on_constructed_answers():
    checks = [
        {"case": "X", "item": 0, "question": "q", "answer": "yes stated", "label": True},
        {"case": "X", "item": 0, "question": "q", "answer": "also stated", "label": True},
        {"case": "X", "item": 0, "question": "q", "answer": "not stated", "label": False},
    ]
    patterns = {"X": [ITEM]}
    out = M.judge_check(checks, patterns, judge=lambda q, a, t: "stated" in a and "not" not in a)
    assert out["n"] == 3 and out["recall"] == 1.0 and out["precision"] == 1.0
    always_no = M.judge_check(checks, patterns, judge=lambda q, a, t: False)
    assert always_no["recall"] == 0.0 and always_no["false_negatives"] == 2


def test_the_blind_sheet_has_the_answers_and_items_but_none_of_the_labels_or_notes():
    records = {"run": [{"id": "X", "answer": "In fiscal year 2024 it was 1", "question": "q?"}]}
    labels = [{"run": "run", "case": "X", "item": 0, "label": True, "note": "SECRET NOTE"}]
    rows = M.build_blind(records, {"X": [ITEM]}, labels, seed=1)
    assert len(rows) == 1
    row = rows[0]
    assert row["answer"] == "In fiscal year 2024 it was 1" and row["item_text"] == ITEM["text"]
    assert row["question"] == "q?" and row["label"] is None
    assert "SECRET" not in json.dumps(rows) and "True" not in json.dumps(rows)


def test_the_blind_sheet_order_is_shuffled_but_reproducible():
    records = {"r": [{"id": "X", "answer": f"a{i}", "question": "q"} for i in range(1)]}
    labels = [{"run": "r", "case": "X", "item": 0, "label": True, "note": ""}]
    many = [{"run": "r", "case": "X", "item": 0, "label": True, "note": ""}] * 1
    assert M.build_blind(records, {"X": [ITEM]}, many, 3) == M.build_blind(
        records, {"X": [ITEM]}, labels, 3
    )


def _six_labelled_answers(calls=("X0",)):
    """Six answers on six cases; the first labeller marked those in `calls` as judgement calls."""
    cases = [f"X{i}" for i in range(6)]
    records = {"r": [{"id": c, "answer": f"answer {c}", "question": "q"} for c in cases]}
    labels = [
        {
            "run": "r",
            "case": c,
            "item": 0,
            "label": True,
            "note": "JUDGEMENT CALL: either way" if c in calls else "plain",
        }
        for c in cases
    ]
    return records, {c: [ITEM] for c in cases}, labels


def test_the_blind_subset_is_every_judgement_call_and_a_seeded_draw_of_the_rest():
    records, patterns, labels = _six_labelled_answers(calls=("X0", "X3"))
    rows = M.build_blind_subset(records, patterns, labels, n_random=2, seed=7)
    cases = {r["case"] for r in rows}
    assert len(rows) == 4 and {"X0", "X3"} <= cases  # both judgement calls, two of the other four
    assert rows == M.build_blind_subset(records, patterns, labels, n_random=2, seed=7)
    draws = {
        frozenset(r["case"] for r in M.build_blind_subset(records, patterns, labels, 2, seed))
        for seed in range(20)
    }
    assert len(draws) > 1  # the draw depends on the seed: it is a draw, not a fixed pick


def test_the_blind_subset_does_not_say_which_rows_are_the_judgement_calls():
    records, patterns, labels = _six_labelled_answers()
    rows = M.build_blind_subset(records, patterns, labels, n_random=2, seed=7)
    assert all(r["label"] is None and r["note"] == "" for r in rows)
    assert "JUDGEMENT" not in json.dumps(rows) and "plain" not in json.dumps(rows)
    assert len({tuple(sorted(r)) for r in rows}) == 1  # every row has the same fields


def test_the_committed_blind_subset_is_the_four_judgement_calls_and_the_seeded_ten():
    """Holds before and after MJ fills it: the labels and notes are MJ's, the rest is pinned."""

    def read(path):
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

    def answer_id(lab):
        return f"{lab['run']}:{lab['case']}:{lab['item']}"

    labels = M.load_labels()
    subset = read(M.SUBSET_PATH)
    full = {r["answer_id"]: r for r in read(M.BLIND_PATH)}
    calls = {answer_id(lab) for lab in labels if M.is_judgement_call(lab)}
    ids = [r["answer_id"] for r in subset]
    assert len(labels) == 28 and len(calls) == 4
    assert len(ids) == len(set(ids)) == 14 and calls <= set(ids)
    assert set(ids) == {answer_id(lab) for lab in M.subset_labels(labels)}  # the seeded draw
    for row in subset:  # the same question, item and answer text as the full sheet
        theirs = {k: v for k, v in row.items() if k not in ("label", "note")}
        assert theirs == {k: v for k, v in full[row["answer_id"]].items() if k in theirs}


def test_agreement_says_which_part_of_the_first_labellers_items_was_checked():
    records, patterns, labels = _six_labelled_answers(calls=("X0",))
    # MJ labels the judgement call and two of the other five, and differs on the judgement call.
    blind = [
        {"run": "r", "case": "X0", "item": 0, "label": False, "note": ""},
        {"run": "r", "case": "X1", "item": 0, "label": True, "note": ""},
        {"run": "r", "case": "X2", "item": 0, "label": True, "note": ""},
    ]
    out = M.agreement(blind, labels, records, patterns)
    assert out["n"] == 3 and out["first_labeller_total"] == 6
    assert out["judgement_calls"] == {"n": 1, "of": 1, "mj_claude": 0, "mj_grader": 1}
    assert out["others"] == {"n": 2, "of": 5, "mj_claude": 2, "mj_grader": 0}
    text = M._format_agreement(out)
    assert "3 labelled (0 left blank), of the 6 items the first labeller labelled" in text
    assert "| the other items | 2 of 5 | 2 | 0 |" in text
    assert "The 3 items MJ did not label" in text
    # With nothing labelled yet the report still renders (no rate to compute).
    blank = [{**b, "label": None} for b in blind]
    assert "0 labelled (3 left blank)" in M._format_agreement(
        M.agreement(blank, labels, records, patterns)
    )


def test_agreement_reports_per_item_overall_and_every_disagreement_in_both_comparisons():
    patterns = {"X": [ITEM]}
    records = {"r": [{"id": "X", "answer": "It was 1", "question": "q"}]}  # no fiscal year stated
    claude = [{"run": "r", "case": "X", "item": 0, "label": True, "note": ""}]
    blind = [{"run": "r", "case": "X", "item": 0, "label": False, "note": "my read"}]
    out = M.agreement(blind, claude, records, patterns)
    assert out["n"] == 1
    assert out["mj_vs_claude"] == {"n": 1, "agree": 0}  # the first labeller said True, MJ False
    assert out["mj_vs_grader"] == {"n": 1, "agree": 1}  # the grader said False, with MJ
    (d,) = out["disagreements"]  # listed because the first labeller differs from MJ
    assert (d["case"], d["mj"], d["claude"], d["grader"]) == ("X", False, True, False)
    assert out["per_item"][("X", 0)] == {"n": 1, "mj_claude": 0, "mj_grader": 1}
    blank = M.agreement([{**blind[0], "label": None}], claude, records, patterns)
    assert blank["unlabelled"] == 1 and blank["n"] == 0


def test_the_judge_asks_for_a_small_context_so_it_fits_beside_other_applications(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, host=None):
            pass

        def generate(self, model, prompt, options):
            seen.update(options)
            return type("R", (), {"response": "YES"})()

    import ollama

    monkeypatch.setattr(ollama, "Client", FakeClient)
    judge = M.OllamaJudge()
    assert judge("q", "an answer", "an item") is True
    assert seen["num_ctx"] == M.JUDGE_NUM_CTX == 1024
    assert seen["temperature"] == 0 and seen["seed"] == 42
