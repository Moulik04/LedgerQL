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

    from evals import measurement_pin

    monkeypatch.setattr(ollama, "Client", FakeClient)
    monkeypatch.setattr(measurement_pin, "load_pins", lambda path=None: [])
    judge = M.OllamaJudge()
    assert judge("q", "an answer", "an item") is True
    assert seen["num_ctx"] == M.JUDGE_NUM_CTX == 1024
    assert seen["temperature"] == 0 and seen["seed"] == 42


# --- labelling the blind sheet by hand ----------------------------------------------------------


def _sheet(tmp_path, n=3, labelled=()):
    rows = [
        {
            "answer_id": f"run-a:X{i}:0",
            "run": "run-a",
            "case": f"X{i}",
            "item": 0,
            "question": f"question {i}?",
            "item_text": f"rubric item {i}",
            "answer": f"the answer text {i}",
            "label": labelled[i] if i < len(labelled) else None,
            "note": "",
        }
        for i in range(n)
    ]
    path = tmp_path / "sheet.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path, rows


def _read(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _replies(*replies):
    left = list(replies)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return left.pop(0)

    return ask, asked


def test_labelling_shows_each_row_alone_and_writes_yes_or_no_as_true_or_false(tmp_path):
    path, before = _sheet(tmp_path)
    ask, asked = _replies("y", "n", "Y")
    shown = []
    assert M.label_sheet(path, ask=ask, show=shown.append) == 3
    after = _read(path)
    assert [r["label"] for r in after] == [True, False, True]
    assert len(asked) == len(shown) == 3 and all("[y/n]" in prompt for prompt in asked)
    for i, text in enumerate(shown):  # its own answer and rubric item, and no other row's
        assert f"the answer text {i}" in text and f"rubric item {i}" in text
        assert f"question {i}?" in text and f"{i + 1} of 3" in text
        assert not any(f"the answer text {j}" in text for j in range(3) if j != i)
    # nothing but the labels changed
    assert [{**r, "label": None} for r in after] == before


def test_a_reply_that_is_not_yes_or_no_is_asked_again(tmp_path):
    path, _ = _sheet(tmp_path, n=1)
    ask, asked = _replies("maybe", "", " NO ")
    M.label_sheet(path, ask=ask, show=lambda text: None)
    assert _read(path)[0]["label"] is False and len(asked) == 3


def test_each_answer_is_saved_as_it_is_given_and_a_second_run_asks_only_for_the_rest(tmp_path):
    import pytest

    path, _ = _sheet(tmp_path)

    replies = ["y"]

    def interrupted(prompt):
        if not replies:
            raise KeyboardInterrupt
        return replies.pop()

    with pytest.raises(KeyboardInterrupt):
        M.label_sheet(path, ask=interrupted, show=lambda text: None)
    assert [r["label"] for r in _read(path)] == [True, None, None]  # the first answer was kept

    ask, asked = _replies("n", "n")
    shown = []
    assert M.label_sheet(path, ask=ask, show=shown.append) == 2
    assert [r["label"] for r in _read(path)] == [True, False, False]  # the first is not re-asked
    assert "2 of 3" in shown[0] and "the answer text 0" not in "".join(shown)


def test_a_sheet_that_is_already_labelled_asks_nothing(tmp_path):
    path, _ = _sheet(tmp_path, labelled=(True, False, True))
    text = path.read_text()
    assert M.label_sheet(path, ask=lambda prompt: 1 / 0, show=lambda text: 1 / 0) == 0
    assert path.read_text() == text


def test_the_label_command_labels_the_subset_sheet_it_is_given(tmp_path, monkeypatch, capsys):
    path, _ = _sheet(tmp_path, n=2)
    replies = ["n", "y"]
    monkeypatch.setattr("builtins.input", lambda prompt="": replies.pop(0))
    assert M.main(["label", "--blind-file", str(path)]) == 0
    assert [r["label"] for r in _read(path)] == [False, True]
    assert "the answer text 1" in capsys.readouterr().out


def test_stopping_the_label_command_part_way_says_so_and_keeps_what_was_answered(
    tmp_path, monkeypatch, capsys
):
    path, _ = _sheet(tmp_path, n=2)
    replies = ["y"]

    def stop_after_one(prompt=""):
        if not replies:
            raise EOFError
        return replies.pop()

    monkeypatch.setattr("builtins.input", stop_after_one)
    assert M.main(["label", "--blind-file", str(path)]) == 1
    assert [r["label"] for r in _read(path)] == [True, None]
    assert "run it again" in capsys.readouterr().out


def test_the_label_command_defaults_to_the_14_item_subset_and_would_leave_its_text_as_it_is():
    # written back row by row, the committed sheet is byte-identical: a diff shows labels only
    assert M.SUBSET_PATH.name == "must_state_labels_blind_subset.jsonl"
    text = M.SUBSET_PATH.read_text()
    assert "".join(json.dumps(r) + "\n" for r in _read(M.SUBSET_PATH)) == text


# --- the adjudication ---------------------------------------------------------------------------


def test_a_final_call_is_read_from_the_note_and_a_row_without_one_has_none():
    assert M.final_call({"note": "FINAL (MJ, 2026-10-07): stated. It names the metric."}) is True
    assert M.final_call({"note": "FINAL (MJ, 2026-10-07): not stated. A slip."}) is False
    assert M.final_call({"note": "FINAL: not stated"}) is False
    assert M.final_call({"note": ""}) is None and M.final_call({}) is None
    # only at the start of the note, and only the two calls: prose that mentions them is no call
    assert M.final_call({"note": "I think it is stated, FINAL: stated"}) is None
    assert M.final_call({"note": "FINAL (MJ): unsure"}) is None


def _three_adjudicated():
    """Three answers that state no fiscal year (the grader says False to each), all blind-labelled
    True. Re-read: X0 was a slip, X1 stands against the grader, X2 was not adjudicated."""
    patterns = {f"X{i}": [item(case=f"X{i}")] for i in range(3)}
    records = {"r": [{"id": f"X{i}", "answer": f"It was {i}", "question": "q"} for i in range(3)]}
    claude = [
        {"run": "r", "case": f"X{i}", "item": 0, "label": lab, "note": ""}
        for i, lab in enumerate((False, False, True))
    ]
    blind = [
        {"run": "r", "case": f"X{i}", "item": 0, "label": True, "note": note}
        for i, note in enumerate(("FINAL (MJ): not stated. Slip.", "FINAL (MJ): stated. Why.", ""))
    ]
    return blind, claude, records, patterns


def test_adjudication_keeps_the_blind_figures_and_reports_the_final_calls_beside_them():
    blind, claude, records, patterns = _three_adjudicated()
    out = M.agreement(blind, claude, records, patterns)
    # the blind agreement is what it was before any note was written
    assert out["mj_vs_grader"] == {"n": 3, "agree": 0}
    assert out["mj_vs_claude"] == {"n": 3, "agree": 1}
    assert out == {**M.agreement([{**b, "note": ""} for b in blind], claude, records, patterns),
                   "adjudicated": out["adjudicated"],
                   "disagreements": out["disagreements"]}  # fmt: skip
    adj = out["adjudicated"]
    assert adj["n"] == 2 and adj["differed_from_grader"] == 3
    assert adj["to_grader"] == 1  # X0: the blind label differed from the grader and was wrong
    assert adj["final_vs_grader"] == {"n": 3, "agree": 1}
    assert adj["final_vs_claude"] == {"n": 3, "agree": 2}  # X0 and X2
    assert [(r["case"], r["final"]) for r in adj["false_fails"]] == [("X1", True), ("X2", True)]
    assert adj["false_passes"] == []


def test_the_report_states_the_blind_agreement_first_and_then_the_adjudicated_outcome():
    blind, claude, records, patterns = _three_adjudicated()
    text = M._format_agreement(M.agreement(blind, claude, records, patterns))
    assert "**MJ vs the grader:** 0 of 3 (0%) gradable" in text
    assert text.index("## What the check covers") < text.index("## After adjudication")
    assert "1 was resolved in the grader's favour on re-reading" in text
    assert "**Final call vs the grader:** 1 of 3 (33%) gradable" in text
    assert "**Final call vs the first labeller:** 2 of 3 (67%)" in text
    assert "| r | X0 | 0 | True | False | False | False |" in text  # blind, final, grader, first
    assert "not adjusted until" not in text
    # before any final call is written there is no such section
    unread = [{**b, "note": ""} for b in blind]
    before = M._format_agreement(M.agreement(unread, claude, records, patterns))
    assert "## After adjudication" not in before and "not adjusted until" in before


def test_the_committed_sheet_keeps_every_blind_label_and_carries_eight_final_calls():
    rows = _read(M.SUBSET_PATH)
    assert len(rows) == 14 and all(r["label"] in (True, False) for r in rows)
    finals = {r["answer_id"]: M.final_call(r) for r in rows if M.final_call(r) is not None}
    assert len(finals) == 8
    # the three that stand against the grader, which are listed as its known false fails
    assert {k for k, v in finals.items() if v} == {
        "qwen25_32b:U08:0",
        "qwen3_30b:U08:0",
        "qwen25_32b:M02:0",
    }
    issues = (M.SUBSET_PATH.parent / "KNOWN_GOLD_ISSUES.md").read_text()
    assert "U08" in issues and "known false fail" in issues


# --- the pinned judge ---------------------------------------------------------------------------


def _fake_ollama(monkeypatch, digest):
    class FakeClient:
        def __init__(self, host=None):
            pass

        def list(self):
            served = [("other:1b", "0" * 64), ("llama3.1:8b", digest)]
            models = [type("M", (), {"model": m, "digest": d})() for m, d in served if d]
            return type("L", (), {"models": models})()

        def generate(self, model, prompt, options):
            return type("R", (), {"response": "NO"})()

    import ollama

    monkeypatch.setattr(ollama, "Client", FakeClient)


def test_the_judge_is_refused_once_pinned_unless_ollama_serves_the_pinned_digest(monkeypatch):
    import pytest

    from evals import measurement_pin
    from evals.scoring import FrozenGoldError

    pin = {"id": "M1", "status": "active", "judge": {"llama3.1:8b": "a" * 64}}
    monkeypatch.setattr(measurement_pin, "load_pins", lambda path=None: [pin])
    _fake_ollama(monkeypatch, "a" * 64)
    assert M.OllamaJudge()("q", "an answer", "an item") is False
    _fake_ollama(monkeypatch, "b" * 64)
    with pytest.raises(FrozenGoldError, match="bbbbbbbbbbbb"):
        M.OllamaJudge()
    _fake_ollama(monkeypatch, None)  # Ollama does not have the model at all
    with pytest.raises(FrozenGoldError, match="llama3.1:8b"):
        M.OllamaJudge()
    _fake_ollama(monkeypatch, "a" * 64)
    with pytest.raises(FrozenGoldError, match="other:1b"):  # a judge the pin does not name
        M.OllamaJudge("other:1b")


def test_before_any_pin_the_judge_is_not_held_to_a_digest(monkeypatch):
    from evals import measurement_pin

    monkeypatch.setattr(measurement_pin, "load_pins", lambda path=None: [])
    _fake_ollama(monkeypatch, "b" * 64)
    assert M.OllamaJudge()("q", "an answer", "an item") is False
