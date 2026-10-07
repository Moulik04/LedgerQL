# ruff: noqa: E501  (the form's texts are kept on single lines)
"""The held-out questions' writers: which writer gets which slots, and the form they write in.

Ten external writers write the 80 held-out questions (evals/HELDOUT_PROTOCOL.md 2 and 3.4). This
draws the ten groups of eight slots from a committed seed, and generates the Google Apps Script
that builds the one form all ten use. It reads the slot sheet and nothing else: no question, no
gold, no model output. It computes no figure, which is why it is not under `evals/`.

    python scripts/heldout_writers.py            # the groups, for reading; writes nothing
    python scripts/heldout_writers.py --write    # assignment.json, build_form.gs and README.md

All three files are generated: a test regenerates them and fails if a committed one differs.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO / "evals" / "heldout_template.jsonl"
OUT_DIR = REPO / "evals" / "heldout_writers"
ASSIGNMENT_PATH = OUT_DIR / "assignment.json"
FORM_PATH = OUT_DIR / "build_form.gs"
README_PATH = OUT_DIR / "README.md"

SEED = 20261007
N_GROUPS = 10
EXPECTED = ("ANSWER", "ANSWER_WITH_ASSUMPTION", "ABSTAIN")

# What a writer is shown. The slot sheet's own words (tier, name class, expected behaviour,
# mention style) are not: a writer sees a type, a company and how to refer to it.
TYPES = {
    "ANSWER": ("answerable", "a clear question the data can answer."),
    "ANSWER_WITH_ASSUMPTION": (
        "needs an assumption",
        "a reasonable question that leaves something unspecified, such as no year or a vague "
        "word like “profit”. Say in the note what you left unclear.",
    ),
    "ABSTAIN": (
        "should be refused",
        "something the tool shouldn’t answer, such as a prediction, an opinion or advice, "
        "information not in companies’ annual filings, or a request to change data or "
        "ignore its rules. Say in the note why.",
    ),
}
STYLES = {
    "legal": "official name",
    "informal": "everyday name",
    "ticker": "ticker",
    "brand": "brand",
}

TITLE = "Eight questions for a financial-data assistant"
INTRO = """Thank you for helping. You will write 8 short questions that a person might ask a tool that answers questions about large US companies from their annual filings. It takes about 10 minutes.

Each page gives you one slot: a type of question, a company, and how to refer to that company. Write one question per page.

Before you start:
• Write every question yourself. Please don’t use ChatGPT, Claude or any AI tool, not even to fix wording.
• Write each question the way you’d actually type it to an analyst. Casual phrasing and typos are fine.
• Don’t try to check whether the data can answer your question.
• Please don’t look up the project or ask how the tool works until you’re done.
• Stay signed into Google if you can, so your progress saves.

How to refer to the company:
• “official name” is the full registered name (like “Apple Inc.”).
• “everyday name” is how people normally say it (“Apple”).
• “ticker” is the stock symbol (“AAPL”).
• “brand” is a brand people use instead of the company’s name (“Google” for Alphabet).
• “none” means a question about many companies; two tickers means a question involving both.

Types of question:
• “answerable” is a clear question the data can answer.
• “needs an assumption” is a reasonable question that leaves something unspecified, such as no year or a vague word like “profit”; say in the note what you left unclear.
• “should be refused” is something the tool shouldn’t answer, such as a prediction, an opinion or advice, information not in companies’ annual filings, or a request to change data or ignore its rules; say in the note why."""

# Only what the database holds (docs/schema.md, checked against data/ledgerql.duckdb on
# 2026-10-07). What it does not hold is not listed: a writer is not told where the gaps are.
CONTAINS_TITLE = "What the data contains"
CONTAINS = """• Companies: the 500 companies of the S&P 500 index, each with its name, its stock ticker and one of 11 industry sectors (for example Information Technology, Health Care, Financials, Energy).
• Filings: about 4,350 filings these companies made with the US Securities and Exchange Commission (SEC) between July 2024 and June 2026, mostly quarterly reports (form 10-Q) and annual reports (form 10-K). Each has its form type, the date it was filed, and the fiscal year and period end date it states.
• Annual figures: the numbers in the main financial statements of each company’s annual report (10-K), for the company as a whole and for that report’s own fiscal year. Nearly every company has two fiscal years on record.
• Examples of figures: revenue, net income, total assets, cash, shareholders’ equity, goodwill, income tax expense, cash flow from operations, share buybacks, earnings per share.
• Units: amounts are stored in full (416,161,000,000, not 416 billion), in US dollars for almost every figure; share counts and per-share figures are in their own units."""

CODE_HELP = "The code in the message you received, for example W4."
GROUP_HELP = "The group number in the message you received. It decides which 8 slots you get."
QUESTION_HELP = "Please write a full question (at least 10 characters)."
THANKS = (
    "Thank you. Your questions are saved. Please don’t look up the project until you hear back."
)

MESSAGE = """Hi <NAME>,

Thank you for helping with my project. I need 8 short questions written by a real person, and it takes about 10 minutes.

Link: <FORM LINK>
Your writer code: {code}
Your group number: {primary}

The form explains everything. Please write the questions yourself, with no ChatGPT, Claude or other AI tool, and please don’t look up the project or ask me how the tool works until you’re done.

Optional: if you have another 10 minutes, open the same link again and do group {extra} as well, with the same code {code}. Please don’t do any other group.

Thank you!"""


def load_template(path: Path = TEMPLATE_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def assign_groups(
    rows: list[dict], seed: int = SEED, n_groups: int = N_GROUPS
) -> dict[int, list[str]]:
    """The slots dealt into `n_groups` equal groups, each as close to the whole sheet's mix of
    expected behaviours as whole slots allow. Each behaviour's slots are shuffled, the groups are
    shuffled, and the slots are dealt one at a time round the groups, the behaviours end to end,
    so no group is more than one slot from its proportional share of any behaviour and every
    group has the same number of slots. Within a group the slots are in the sheet's order.
    Deterministic for a seed."""
    rng = random.Random(seed)
    deck: list[str] = []
    for expected in EXPECTED:
        ids = [r["id"] for r in rows if r["expected"] == expected]
        rng.shuffle(ids)
        deck += ids
    if len(deck) != len(rows) or len(deck) % n_groups:
        raise ValueError(f"{len(rows)} slots cannot be dealt into {n_groups} equal groups")
    order = list(range(1, n_groups + 1))
    rng.shuffle(order)
    groups: dict[int, list[str]] = {g: [] for g in range(1, n_groups + 1)}
    for i, slot in enumerate(deck):
        groups[order[i % n_groups]].append(slot)
    return {g: sorted(ids) for g, ids in groups.items()}


def writers(n_groups: int = N_GROUPS) -> dict[str, dict[str, int]]:
    """Wn is the primary writer of group n and may also take group n+1 (the last takes group 1),
    so if every writer takes the extra group each slot has exactly two writers."""
    return {f"W{n}": {"primary": n, "extra": n % n_groups + 1} for n in range(1, n_groups + 1)}


def assignment(rows: list[dict], seed: int = SEED) -> dict:
    from evals.heldout_slots import assignment_digest

    groups = assign_groups(rows, seed)
    by_id = {r["id"]: r for r in rows}
    return {
        "seed": seed,
        "slot_sheet_sha256": assignment_digest(rows),
        "method": "scripts/heldout_writers.py assign_groups: each expected behaviour's slots "
        "shuffled, the groups shuffled, the slots dealt round the groups",
        "groups": {str(g): ids for g, ids in groups.items()},
        "mix": {
            str(g): {e: sum(by_id[i]["expected"] == e for i in ids) for e in EXPECTED}
            for g, ids in groups.items()
        },
        "writers": writers(len(groups)),
        "reassigned": [],
    }


def display_name(stored: str) -> str:
    """A company's name as a person would read it, from the stored one: a trailing `(The)` goes
    to the front, a share class is dropped, and any other trailing parenthesis goes to the front
    (`Lilly (Eli)`). The stored form itself is never shown: it is what the database matches on."""
    found = re.fullmatch(r"(.+?) \(([^()]+)\)", stored)
    if not found:
        return stored
    name, inside = found.groups()
    if inside.startswith("Class "):
        return name
    return f"{inside} {name}"


def slot_header(row: dict) -> str:
    """What a slot's page says under its title: the type and what it means, the company or
    companies, and how to refer to each. Nothing else from the sheet."""
    kind, meaning = TYPES[row["expected"]]
    lines = [f"Type: {kind} — {meaning}"]
    companies = row["company_slots"]
    if not companies:
        lines += ["Company: none (a question about many companies)"]
    for c in companies:
        lines += [
            f"Company: {display_name(c['name'])} (ticker: {c['ticker']})",
            f"Refer to it by: {STYLES[c['mention_style']]}",
        ]
    if len(companies) > 1:
        lines += ["Your question should involve both companies."]
    return "\n".join(lines)


def form_data(rows: list[dict], groups: dict[int, list[str]]) -> dict:
    by_id = {r["id"]: r for r in rows}
    return {
        "title": TITLE,
        "intro": INTRO,
        "containsTitle": CONTAINS_TITLE,
        "contains": CONTAINS,
        "codeHelp": CODE_HELP,
        "groupHelp": GROUP_HELP,
        "questionHelp": QUESTION_HELP,
        "thanks": THANKS,
        "groups": [
            {
                "number": g,
                "slots": [
                    {
                        "id": slot,
                        "title": f"Group {g}, question {k} of {len(ids)} (slot {slot})",
                        "header": slot_header(by_id[slot]),
                        "noteRequired": by_id[slot]["expected"] != "ANSWER",
                        "noteHelp": {
                            "ANSWER": "Optional: anything you want to add.",
                            "ANSWER_WITH_ASSUMPTION": "Required: what did you leave unclear?",
                            "ABSTAIN": "Required: why should the tool refuse this?",
                        }[by_id[slot]["expected"]],
                    }
                    for k, slot in enumerate(ids, 1)
                ],
            }
            for g, ids in sorted(groups.items())
        ],
    }


_FORM_JS = r"""
/**
 * Builds the form the ten writers use: one form, the writer's code, a group number, and that
 * group's 8 slots, one page each. Responses go to a new Google Sheet.
 *
 * Run buildForm ONCE at script.google.com (evals/heldout_writers/README.md). Each run creates
 * a new form.
 */
function buildForm() {
  var form = FormApp.create(DATA.title);
  form.setDescription(DATA.intro);
  // Off: the bar counts every page of the form, so it barely moves for a writer on one group.
  // The page titles ("question 5 of 8") say where a writer is.
  form.setProgressBar(false);
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setAllowResponseEdits(false);
  form.setShowLinkToRespondAgain(true);
  form.setConfirmationMessage(DATA.thanks);
  // Only a Google Workspace account has this setting; elsewhere no sign-in is the default.
  try { form.setRequireLogin(false); } catch (e) { Logger.log('setRequireLogin: ' + e); }

  form.addSectionHeaderItem().setTitle(DATA.containsTitle).setHelpText(DATA.contains);
  form.addTextItem()
      .setTitle('Writer code')
      .setHelpText(DATA.codeHelp)
      .setRequired(true)
      .setValidation(FormApp.createTextValidation()
          .setHelpText('A code looks like W4.')
          .requireTextMatchesPattern('^ *[Ww][0-9]{1,2} *$')
          .build());
  var groupItem = form.addListItem()
      .setTitle('Group number')
      .setHelpText(DATA.groupHelp)
      .setRequired(true);

  var firstPage = {};
  DATA.groups.forEach(function (group, g) {
    group.slots.forEach(function (slot, k) {
      var page = form.addPageBreakItem().setTitle(slot.title).setHelpText(slot.header);
      if (k === 0) {
        firstPage[group.number] = page;
        // Reaching this page from the page before it means the previous group is finished.
        if (g > 0) page.setGoToPage(FormApp.PageNavigationType.SUBMIT);
      }
      form.addParagraphTextItem()
          .setTitle(slot.id + ': your question')
          .setRequired(true)
          .setValidation(FormApp.createParagraphTextValidation()
              .setHelpText(DATA.questionHelp)
              .requireTextLengthGreaterThanOrEqualTo(10)
              .build());
      form.addParagraphTextItem()
          .setTitle(slot.id + ': note')
          .setHelpText(slot.noteHelp)
          .setRequired(slot.noteRequired);
    });
  });
  groupItem.setChoices(DATA.groups.map(function (group) {
    return groupItem.createChoice(String(group.number), firstPage[group.number]);
  }));

  var sheet = SpreadsheetApp.create(DATA.title + ' (responses)');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());
  // A form made by a script is published already on most accounts; this is for the others.
  try { form.setPublished(true); } catch (e) { Logger.log('setPublished: ' + e); }

  Logger.log('Send this link to the writers: ' + form.getPublishedUrl());
  Logger.log('Edit the form: ' + form.getEditUrl());
  Logger.log('Responses (Google Sheet): ' + sheet.getUrl());
}
"""


def form_script(data: dict) -> str:
    """The Apps Script source: the form's content as one object, then the function that builds
    it. Non-ASCII characters are escaped, so the file survives any copy and paste."""
    return (
        "// Generated by scripts/heldout_writers.py from evals/heldout_writers/assignment.json.\n"
        "// Do not edit by hand: change the generator and run it with --write.\n\n"
        f"var DATA = {json.dumps(data, indent=1)};\n" + _FORM_JS
    )


def readme(assigned: dict) -> str:
    """For MJ: how to build and check the form, the message for each writer, and what comes back."""
    pages = sum(len(ids) for ids in assigned["groups"].values())
    lines = [
        "# The held-out questions' writers",
        "",
        "Generated by `scripts/heldout_writers.py --write`; the rules are in "
        "`evals/HELDOUT_PROTOCOL.md` (2, 3.4, 3.5). Do not edit by hand.",
        "",
        f"`assignment.json` is the draw (seed {assigned['seed']}): ten groups of eight slots, and "
        "which writer code has which group. `build_form.gs` is the script that builds the form.",
        "",
        "| group | primary writer | extra writer (optional) | answerable | needs an assumption | should be refused | slots |",
        "|---|---|---|---|---|---|---|",
    ]
    extra_of = {w["extra"]: code for code, w in assigned["writers"].items()}
    primary_of = {w["primary"]: code for code, w in assigned["writers"].items()}
    for g, ids in assigned["groups"].items():
        mix = assigned["mix"][g]
        lines.append(
            f"| {g} | {primary_of[int(g)]} | {extra_of[int(g)]} | {mix['ANSWER']} | "
            f"{mix['ANSWER_WITH_ASSUMPTION']} | {mix['ABSTAIN']} | {' '.join(ids)} |"
        )
    lines += [
        "",
        "## Building the form",
        "",
        "1. Sign in to the Google account that should own the form and open "
        "<https://script.google.com>. Click **New project**.",
        "2. In the editor, select everything in `Code.gs` and delete it. Paste the whole of "
        "`evals/heldout_writers/build_form.gs`. Click the save icon.",
        "3. In the toolbar, the function menu should read `buildForm`. Click **Run**.",
        "4. The first run asks for permission: **Review permissions**, choose your account, then "
        "**Advanced** and **Go to Untitled project (unsafe)** if Google shows the unverified-app "
        "screen (it is your own script), then **Allow**. It needs your Forms and Sheets.",
        f"5. Wait for **Execution completed** in the Execution log (a minute or two: it adds "
        f"{3 + 3 * pages} items). The log ends with three links: the one to send to the writers, the form's "
        "editor, and the response sheet.",
        "6. Run it **once**. A second run builds a second form; if that happens, delete the "
        "extra form and sheet from Google Drive and use one pair.",
        "",
        "## Checking it before anyone gets the link",
        "",
        "1. Open the writers' link in a private (incognito) window, where you are not signed in. "
        "It must open without asking you to sign in. If it asks: in the form's editor, open "
        "**Publish** (or **Send**) and set responders to **Anyone with the link**, and under "
        "**Settings > Responses** make sure **Limit to 1 response** is off and email collection "
        "is **Do not collect**.",
        "2. The first page shows the instructions, *What the data contains*, **Writer code** and "
        "**Group number** (a dropdown, 1 to 10). A code such as `X1` must be rejected.",
        "3. Enter code `W99` and pick a group. You should get exactly that group's 8 pages, each "
        "titled *Group n, question k of 8 (slot Hxx)*, with the type, the company and how to "
        "refer to it, and no tier or name class. Compare the slot numbers with the table above.",
        "4. On each page **your question** is required and refuses fewer than 10 characters; "
        "**note** is required on *needs an assumption* and *should be refused* pages only.",
        "5. After the 8th page the form offers **Submit**, not another group's page. Submit, then "
        "check that a row arrived in the response sheet with the code, the group and the "
        "answers under columns named `Hxx: your question` and `Hxx: note`.",
        "6. Try at least the first group, the last and one in the middle. There is no progress "
        f"bar, on purpose: it would count all {pages + 1} pages of the form. The page title is "
        "what tells a writer where they are.",
        "7. Delete your test responses before sending the link: in the editor, **Responses**, "
        "the three-dot menu, **Delete all responses**; then delete the test rows in the sheet. "
        "(A row with a code that is not assigned to its group is discarded by the rules anyway.)",
        "",
        "## The message for each writer",
        "",
        "Replace `<NAME>` and `<FORM LINK>`. Keep who has which code in a note of your own, "
        "outside this repository: the repository records codes only.",
    ]
    for code, w in assigned["writers"].items():
        lines += ["", f"### {code}", "", "```", MESSAGE.format(code=code, **w), "```"]
    lines += [
        "",
        "## Bringing the responses back",
        "",
        "In the response sheet: **File > Download > Comma-separated values (.csv)**. Save it "
        "as `evals/heldout_writers/responses.csv`, unedited. If you reassign a group first, "
        "say which group went from which code to which, so it is recorded in "
        "`assignment.json` (`reassigned`) before the replacement's questions are read.",
        "",
    ]
    return "\n".join(lines)


def build(rows: list[dict], seed: int = SEED) -> dict[Path, str]:
    """Every generated file and its text."""
    assigned = assignment(rows, seed)
    groups = {int(g): ids for g, ids in assigned["groups"].items()}
    return {
        ASSIGNMENT_PATH: json.dumps(assigned, indent=1) + "\n",
        FORM_PATH: form_script(form_data(rows, groups)),
        README_PATH: readme(assigned),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    files = build(load_template())
    if args.write:
        OUT_DIR.mkdir(exist_ok=True)
        for path, text in files.items():
            path.write_text(text)
            print(f"wrote {path.relative_to(REPO)}")
        return 0
    assigned = json.loads(files[ASSIGNMENT_PATH])
    for g, ids in assigned["groups"].items():
        print(g, assigned["mix"][g], " ".join(ids))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
