"""The held-out writers' groups and the form they write in (scripts/heldout_writers.py): the draw
is seeded and stratified, the committed files are the generator's, a writer is shown nothing
internal, and the generated script builds the form it should."""

import importlib.util
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "heldout_writers", REPO / "scripts/heldout_writers.py"
)
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

ROWS = W.load_template()
BY_ID = {r["id"]: r for r in ROWS}


def test_the_draw_is_ten_groups_of_eight_with_every_slot_in_exactly_one():
    groups = W.assign_groups(ROWS)
    assert sorted(groups) == list(range(1, 11))
    assert all(len(ids) == 8 for ids in groups.values())
    assert sorted(i for ids in groups.values() for i in ids) == sorted(BY_ID)


def test_every_group_is_as_close_to_the_sheets_mix_as_whole_slots_allow():
    # the sheet is 40 / 16 / 24, so a group's share is 4 / 1.6 / 2.4
    mixes = Counter()
    for ids in W.assign_groups(ROWS).values():
        mix = Counter(BY_ID[i]["expected"] for i in ids)
        assert mix["ANSWER"] == 4
        assert mix["ANSWER_WITH_ASSUMPTION"] in (1, 2) and mix["ABSTAIN"] in (2, 3)
        mixes[(mix["ANSWER_WITH_ASSUMPTION"], mix["ABSTAIN"])] += 1
    assert mixes == {(2, 2): 6, (1, 3): 4}


def test_the_draw_is_fixed_by_its_seed():
    assert W.assign_groups(ROWS) == W.assign_groups(ROWS, W.SEED)
    assert W.assign_groups(ROWS) != W.assign_groups(ROWS, W.SEED + 1)
    assert W.SEED == 20261007


def test_each_writer_has_one_group_and_one_optional_next_group_and_no_slot_gets_three():
    writers = W.writers()
    assert writers["W1"] == {"primary": 1, "extra": 2}
    assert writers["W10"] == {"primary": 10, "extra": 1}
    assert sorted(w["primary"] for w in writers.values()) == list(range(1, 11))
    assert sorted(w["extra"] for w in writers.values()) == list(range(1, 11))
    assert all(w["primary"] != w["extra"] for w in writers.values())


def test_the_committed_files_are_what_the_generator_writes_from_the_committed_sheet():
    for path, text in W.build(ROWS).items():
        assert path.read_text() == text, f"{path.name}: run scripts/heldout_writers.py --write"
    recorded = json.loads(W.ASSIGNMENT_PATH.read_text())
    sheet_hash = (REPO / "evals/heldout_template.sha256").read_text().split()[0]
    assert recorded["seed"] == W.SEED and recorded["slot_sheet_sha256"] == sheet_hash


def test_a_company_is_shown_by_a_readable_name_and_never_by_its_stored_form():
    assert W.display_name("Trade Desk (The)") == "The Trade Desk"
    assert W.display_name("Lilly (Eli)") == "Eli Lilly"
    assert W.display_name("Fox Corporation (Class A)") == "Fox Corporation"
    assert W.display_name("Block, Inc.") == "Block, Inc." and W.display_name("AT&T") == "AT&T"
    shown = [W.display_name(c["name"]) for r in ROWS for c in r["company_slots"]]
    assert not [name for name in shown if "(" in name]


def test_a_slot_page_shows_the_type_the_company_and_the_style_and_nothing_internal():
    data = W.form_data(ROWS, W.assign_groups(ROWS))
    slots = [s for g in data["groups"] for s in g["slots"]]
    assert len(slots) == 80 and len({s["id"] for s in slots}) == 80
    internal = [*{r["tier"] for r in ROWS}, *{c["class"] for r in ROWS for c in r["company_slots"]}]
    internal += ["legal", "informal", "ANSWER", "ABSTAIN", "(The)"]
    for s in slots:
        row = BY_ID[s["id"]]
        assert s["noteRequired"] is (row["expected"] != "ANSWER")
        assert W.TYPES[row["expected"]][0] in s["header"]
        for c in row["company_slots"]:
            assert c["ticker"] in s["header"] and W.STYLES[c["mention_style"]] in s["header"]
        if not row["company_slots"]:
            assert "Company: none" in s["header"]
        text = s["title"] + " " + s["header"]
        assert not [w for w in internal if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text)], s[
            "id"
        ]


def test_the_form_names_no_project_and_lists_only_what_the_data_contains():
    data = W.form_data(ROWS, W.assign_groups(ROWS))
    everything = json.dumps(data).lower()
    assert "ledgerql" not in everything and "github" not in everything
    for gap in ("not contain", "no quarterly", "missing", "segment", "bank"):
        assert gap not in data["contains"].lower(), gap


_STUB = r"""
var calls = {pages: [], items: [], form: {}};
function chain(record) {
  return new Proxy(record, {get: function (t, name) {
    if (name in t) return t[name];
    if (name === 'createChoice') {
      return function (v, page) { return {value: v, page: page.setTitle}; };
    }
    if (name === 'build') return function () { return t; };
    return function (v) { t[String(name)] = v === undefined ? true : v; return chain(t); };
  }});
}
function item(kind, list) {
  return function () { var r = {kind: kind}; list.push(r); return chain(r); };
}
var FormApp = {
  create: function (title) {
    calls.form.title = title;
    return new Proxy({}, {get: function (_, name) {
      if (name === 'addPageBreakItem') return function () {
        var r = {kind: 'page'};
        calls.pages.push(r);
        calls.items.push(r);
        return chain(r);
      };
      if (/^add/.test(name)) return item(String(name), calls.items);
      if (name === 'getPublishedUrl') return function () { return 'https://forms.example/send'; };
      if (name === 'getEditUrl') return function () { return 'https://forms.example/edit'; };
      if (name === 'setRequireLogin') return function () { throw new Error('consumer account'); };
      return function (a, b) { calls.form[String(name)] = b === undefined ? a : [a, b]; };
    }});
  },
  createTextValidation: function () { return chain({}); },
  createParagraphTextValidation: function () { return chain({}); },
  PageNavigationType: {SUBMIT: 'SUBMIT'},
  DestinationType: {SPREADSHEET: 'SPREADSHEET'},
};
var SpreadsheetApp = {create: function (name) {
  return {
    getId: function () { return 'sheet-id'; },
    getUrl: function () { return 'https://sheet'; },
  };
}};
var logged = [];
var Logger = {log: function (line) { logged.push(line); }};
"""


def test_the_generated_script_runs_and_builds_one_branching_page_per_slot(tmp_path):
    node = shutil.which("node")
    assert node, "node is needed to run the generated Apps Script against a stand-in FormApp"
    script = tmp_path / "form.js"
    script.write_text(
        _STUB
        + W.FORM_PATH.read_text()
        + "\nbuildForm();\nconsole.log(JSON.stringify({calls: calls, logged: logged}));\n"
    )
    out = json.loads(
        subprocess.run([node, str(script)], capture_output=True, text=True, check=True).stdout
    )
    calls, groups = out["calls"], W.assign_groups(ROWS)
    form, items, pages = calls["form"], calls["items"], calls["pages"]
    assert form["setProgressBar"] is True and form["setCollectEmail"] is False
    assert form["setLimitOneResponsePerUser"] is False
    assert form["setDestination"] == ["SPREADSHEET", "sheet-id"]
    assert [i["kind"] for i in items[:3]] == ["addSectionHeaderItem", "addTextItem", "addListItem"]
    assert items[1]["setTitle"] == "Writer code" and items[1]["setRequired"] is True
    # ten choices, each going to the first page of its own group
    choices = items[2]["setChoices"]
    assert [c["value"] for c in choices] == [str(g) for g in range(1, 11)]
    assert all(f"Group {c['value']}, question 1 of 8" in c["page"] for c in choices)
    # 80 pages, each followed by a required question of ten characters or more and a note
    assert len(pages) == 80 and len(items) == 3 + 3 * 80
    order = [slot for g in sorted(groups) for slot in groups[g]]
    for k, slot in enumerate(order):
        page, question, note = items[3 + 3 * k : 6 + 3 * k]
        assert page["kind"] == "page" and f"(slot {slot})" in page["setTitle"]
        assert question["setTitle"] == f"{slot}: your question" and question["setRequired"] is True
        assert question["setValidation"]["requireTextLengthGreaterThanOrEqualTo"] == 10
        assert note["setTitle"] == f"{slot}: note"
        assert note["setRequired"] is (BY_ID[slot]["expected"] != "ANSWER")
        # a group ends in Submit: the first page of every later group sends its predecessor there
        assert page.get("setGoToPage") == ("SUBMIT" if k % 8 == 0 and k else None)
    assert any("https://forms.example/send" in line for line in out["logged"])


def test_each_writers_message_has_their_code_group_link_time_and_the_optional_next_group():
    text = W.README_PATH.read_text()
    for code, w in W.writers().items():
        message = text.split(f"### {code}\n")[1].split("```")[1]
        assert f"Your writer code: {code}\n" in message
        assert f"Your group number: {w['primary']}\n" in message
        assert "<FORM LINK>" in message and "about 10 minutes" in message
        assert f"do group {w['extra']} as well, with the same code {code}" in message
