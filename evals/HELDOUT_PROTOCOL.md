# Held-out gold set: protocol

Status: **approved by MJ, 80 questions** (2026-10-01), with the pre-registered headline of 6a added.
No model has been, or may be, run on any held-out question until the set is frozen and committed
(section 5).

## 1. Why this set exists

The 103 dev cases were revised twice after inspecting model outputs (gold v2, v3) and are now
frozen (`evals/README.md` 6i), so their scores no longer cleanly measure generalisation. Three
things in the repo were also built or chosen with those cases in view:

- the **entity linker** (`ledgerql/entity_link.py`): its alias list and heuristics were checked
  against the dev questions;
- the **XiYanSQL-32B + DDL prompt** configuration: picked in hindsight as the best of nine cells;
- the **v2/v3 rules** themselves.

Headline claims come from this set from now on. The 103 stay as a development and regression
set. This set is also the only fair test of the linker and of the XiYan + DDL pick.

## 2. Roles, and what "blind" means

| who | does | must not |
|---|---|---|
| MJ | writes the questions, in the slot sheet's mention styles (3.2) | look at any model output, or at which dev questions models fail, while writing; fit questions to a known weakness or to the linker |
| Claude | writes the gold SQL and the `answer_must_state` items, validates them (4), commits | open any candidate or report file, or run any model, while writing; change a question |
| both | freeze (5) | edit anything after the freeze |

Claude has seen a great deal of model output on the dev set and cannot unsee it. The mitigations
are procedural: gold is written from the question, `docs/schema.md` and the database alone;
each gold has an independently written second formulation that must agree (4.3); MJ reviews the
SQL before the freeze; and this disclosure is recorded with the set.

## 3. The template

### 3.1 Tier and count template

**80 questions** (variant B of `evals/heldout_slots.py`), approved by MJ. Held-out questions are
single-use, and the 50-question variant could not confirm the entity linker's dev effect (see the
power note in section 6). The dev set's behaviour mix is 50 / 19 / 34 of 103; this keeps it.

| tier | total | ANSWER | ASSUMPTION | ABSTAIN |
|---|---|---|---|---|
| lookup | 9 | 6 | 3 | 0 |
| aggregation | 8 | 8 | 0 | 0 |
| raw_facts | 7 | 5 | 2 | 0 |
| time | 8 | 5 | 0 | 3 |
| ratio | 6 | 5 | 1 | 0 |
| unit_period | 6 | 2 | 3 | 1 |
| ambiguous | 7 | 0 | 4 | 3 |
| out_of_scope | 6 | 0 | 0 | 6 |
| adversarial | 8 | 2 | 0 | 6 |
| schema_bait | 6 | 0 | 2 | 4 |
| grounding | 5 | 3 | 1 | 1 |
| calibration_twin | 4 | 4 | 0 | 0 |
| **total** | **80** | **40** | **16** | **24** |

What each tier tests is in `evals/README.md` section 1; write new questions of the same kind,
about different facts, companies and phrasings. Calibration twins come in pairs (an easy and a
hard question about the same underlying fact).

### 3.2 The slot sheet

`evals/heldout_template.jsonl` (rendered for reading as `evals/heldout_template.md`) has one row per question: id, tier, expected behaviour, and for
each company the question must mention: the ticker, the stored name, a **name class**
(`plain`, `inverted_the`, `punctuated`, `share_class`, `multi_word`) and a **mention style**:

- `brand`: the name people use ("Apple", "Microsoft");
- `legal`: the registered style ("Apple Inc.", "Microsoft Corporation"), the style the dev set's
  candidates got wrong (`name = 'Microsoft Corporation'`, stored `Microsoft`);
- `ticker`: the symbol ("AAPL");
- `informal`: a looser form a person might type ("Exxon", "J&J", lower case).

The companies were drawn by a seeded shuffle (seed 20260930), stratified across name classes,
none from the dev set, and the assignment is pinned by `evals/heldout_template.sha256`. **It is
committed before any question is written**, so neither writer chose which companies get asked
about. Nothing else about a question is constrained: which fiscal year, which metric and which
phrasing are the writer's.

### 3.3 The question file

Questions go in `evals/heldout_questions.jsonl`: `{"id", "question"}` per slot row, nothing else.
Write them as a person asking an analyst would. A question may be ambiguous or unanswerable
where its tier says so; say nothing about what the answer should be.

## 4. The gold

### 4.1 Format

Each case carries the gold v3 fields from the start: `gold_sql`, `compare`, `tolerance` with
`tolerance_kind`, `entity_cols`, `ratio_cols`, `scale_cols`, `pivot`, `alternatives`, and
`answer_must_state` items with `must_state_patterns` (`evals/must_state.py`). The v2/v3 rules
(`evals/README.md` 6g, 6i) are applied **at writing time**, from the question's wording: project
exactly what is asked; entity columns compare at company level; proportions carry `ratio_cols`;
a stated scale carries `scale_cols`; one quantity for several periods or entities carries
`pivot`. There is no later "fix the gold" pass.

### 4.2 Expected behaviour, reason codes and alternatives

ABSTAIN cases carry the reason code the tier implies (`evals/README.md` section 2), decided by reading
the question and schema, not a model's answer. `accept_alternatives` may list **only**
`ABSTAIN:<REASON_CODE>` entries, which the abstain scorer parses.

**Every acceptable answer must be executable.** Prose cannot be scored, and the dev gold shows what
that costs: `M02` lists "ANSWER_WITH_ASSUMPTION using total_assets instead, if stated" as acceptable,
both measured models answered exactly that way (stating "'Biggest' was measured by total assets") and
the comparator scored them 0, because only the revenue SQL existed (`evals/KNOWN_GOLD_ISSUES.md`).
So in held-out gold, any other acceptable answer is an entry of `alternatives`, each with `describes`
(prose, for the reader), `gold_sql` (executable, so the comparator credits it) and `compare`; its
own entity, ratio, scale and pivot marks apply as for the main answer. A sentence in
`accept_alternatives` that is not `ABSTAIN:<CODE>` fails `python -m evals.heldout_gold_check`, which
also runs every alternative's SQL; it is part of the freeze checklist (5) and must pass before the
set is frozen. This is decided **before any held-out gold is written**.

### 4.3 Validation (before the freeze)

For every ANSWER and ASSUMPTION case:

1. the gold SQL executes against `data/ledgerql.duckdb` and returns a non-empty result (an
   ABSTAIN `NO_DATA` case returns an empty one, stated);
2. a **second, independently written** formulation (for example raw `financial_facts` against the
   concept views, or a different join path) returns the same result;
3. where `docs/schema.md` states a value, it matches;
4. MJ reviews the question, the SQL and the expected behaviour.

`python -m evals.heldout_gold_check <file> --db data/ledgerql.duckdb` passes (4.2).

A disagreement at step 2 is resolved by reading the schema, never by running a model. Cases that
cannot be made unambiguous are dropped before the freeze, not patched after.

## 5. The freeze

1. Commit the slot sheet and its hash (done before questions).
2. MJ commits `heldout_questions.jsonl`. Questions are then fixed.
3. Claude runs `python -m evals.heldout_gold_check` (4.2) and commits `heldout_v1.jsonl` (questions, gold, rubric items) with its SHA-256 in
   `evals/heldout_v1.sha256`, checked by a test, and tags the commit `heldout-v1-frozen`.
4. **Only then** may a model run on it. `gen_only_eval` and `run_eval` refuse a held-out file
   without a matching hash.
5. After the freeze nothing is edited. A gold problem found later goes on
   `evals/HELDOUT_KNOWN_ISSUES.md`; scores are never restated, and the affected case is reported
   with and without (a sensitivity line).

## 6. Pre-registered analyses

Fixed here, before any run, so the set cannot be mined.

**Metrics** (gold v3 rules, strict comparator; relaxed reported beside it, never instead):
pass@1 (the vote's pick) and pass@N (N=5, temperature 0.7, seeds 42 to 46) over the ANSWER
cases; the assumption cases answered correctly, abstained and answered wrong, separately; the
abstain metrics over the ABSTAIN cases.

**Confirmatory comparisons** (the only four; everything else is exploratory and labelled so):

| | comparison | population |
|---|---|---|
| P1 | Qwen3-30B, DDL prompt, with vs without `--entity-link`, same seeds | ANSWER cases naming a company |
| P2 | XiYanSQL-32B, DDL prompt, with vs without `--entity-link`, same seeds | ANSWER cases naming a company |
| P3 | XiYanSQL-32B + DDL vs the other eight bake-off cells (the hindsight pick) | ANSWER cases |
| P4 | "answer only where two models agree" policy vs either model alone | all answered cases |

**Statistics.** Paired at the case level. For P1 and P2: the net number of cases gained minus
lost, a 95% bootstrap CI over cases, and an exact sign test. A claim that linking *helps* needs
the CI to exclude zero **and** the sign test below 0.05. Missing it is reported as "not shown",
never as "no effect". **P1 and P2 measure the linker's effect on held-out data; they do not choose
H's configuration** (6a). No parameter or prompt is tuned on this set; a change made after seeing
its results is exploratory and says so.

**Power, stated plainly.** Paired binary outcomes and an exact sign test need at least six net
discordant cases in one direction to reach p < 0.05. On the dev set the linker gained four cases
and lost none (p = 0.06 one-sided). The 80-question set has 40 ANSWER cases, about 34 of which
name a company, so it can confirm an effect of about six cases and cannot confirm a smaller one.
A result short of that is reported as "not shown".

### 6a. Pre-registered headline: which configuration becomes the README figures

Fixed now, before any question exists, so the headline cannot be chosen after seeing results.
Amended 2026-10-01 at MJ's request in two ways: H is pinned to code, and the linker setting is no
longer chosen from held-out results. Amended again 2026-10-02, before the rerun's results were read
(DECISIONS.md, 2026-10-02 amendments): the linker rule's metric, and what hallucination figure 1 is.
Amended 2026-10-03, before any held-out question exists: H1 is superseded by **H2** (the verifier
fixed and blocked drafts stored), and how figure 1 counts the auditor's tiers is fixed.

- **The headline configuration is H2** (it supersedes H1; both are in `evals/heldout_config.json`,
  which is append-only). H2 is H1 with two changes under `ledgerql/`, declared together as one
  configuration on 2026-10-03: the verifier (`verify.py`) accepts true values in the forms it used
  to refuse (`$416B`, `416 bn`, `$0.4T`, `FY25`, `3rd`), reads spelled-out numbers, holds a stated
  figure to the precision it states in place of a flat 1% tolerance, and no longer exempts form-code
  lookalikes (`391-K`); and the pipeline stores the text of every draft the verifier blocks. Why:
  the independent audit found the first on planted values (`reports/number_audit_vs_verify.md`), and
  without the second, figure 1(a) counts blocks, not invented numbers. H2 is commit
  `19a297e37c58678df4be8802a0882a63018a0d76`, `ledgerql/` tree
  `720f4bae3a5a33644812ef1dd54db8e1cfc7ec25`, with the same models, jobs, settings and linker
  decision (on) as H1. No held-out run was made under H1. The description of H1 that follows is
  kept as written; read "H" as H2.
- **The headline configuration H1** is declared in `evals/heldout_config.json`: the full pipeline
  (classify, N=5 generation, guard, vote, verify, answer) with **Qwen3-Coder-30B-A3B fp16** on the
  pipeline's own `current` prompt, `exec_error` repair **off**, the year verifier **on**. The
  agree-policy table pairs it with **Qwen2.5-32B AWQ** run the same way; the 32B configuration is
  the same commit, code tree, settings and linker decision.
- **H is a code state, not a description.** "The full pipeline" means the code at commit
  `97c69949a491d97146635c0dd45fd55d934f8a1c` and, precisely, the git tree hash of `ledgerql/`
  (`95ad19d17eeac9debf36e48903d4d6371962373d`), which changes if and only if the pipeline code
  changes. That includes `intent.py`, the NO_DATA rule and tautology check (`result_shape.py`,
  `pipeline.py`), the abstain templates and registry (`refusal.py`, `known_gaps.json`),
  `frame_answer` (`frame.py`) and the year verifier (`verify.py`). **Any later change under
  `ledgerql/` is a new configuration** that needs its own declaration (a new entry with its own id;
  declarations are never edited) before any held-out run. This is enforced, not trusted: a test
  fails if `ledgerql/` differs from the active declaration, and `run_eval` and `gen_only_eval`
  refuse any held-out run whose code tree or linker environment differs from it
  (`evals/heldout_config.py`). The held-out file is added in a later commit than 97c6994, which is
  fine: what is pinned is the pipeline code, by tree hash.
- **The linker setting is decided from dev data and fixed before any held-out run.** It is **not**
  conditional on P1 and P2: that would choose H's configuration from the held-out results and then
  report H's headline on those same results, which is selection on the test set. Instead, the
  dev A/B (gen-only, the DDL prompt, Qwen3-30B and XiYanSQL-32B, with and without `--entity-link`,
  same seeds, scored against the frozen gold v3) decides it, by a rule fixed here **before that
  run's results exist**. **Rule (amended 2026-10-02): linking is on unless either model's 95% CI
  lies entirely below zero.** The decision metric is, per `ANSWER` case, the share of the 5
  candidates that are correct (strict v3), linked minus unlinked, averaged over the 50 `ANSWER`
  cases; the CI is a percentile bootstrap over cases, paired by case (10000 resamples, seed
  20261002, `evals/heldout_config.py`). "Entirely below zero" means the upper bound is below zero.
  pass@1 and pass@N are reported as descriptive only and decide nothing. The rule it replaces (on iff
  the 30B's net pass@1 gain is at least +2 cases and XiYan's is not negative) is kept in
  `heldout_config.json` as `rule_superseded`. Why: the vote's pick differs in 10 of 50 cases between
  identical runs, so +2 net pass@1 sits inside run-to-run noise, and the dev set is contaminated
  toward the linker, so this A/B cannot credibly show a benefit; a candidate-level harm check
  (250 candidates per model) does have power to show harm. The mechanism (zero false links on the
  gold questions, at least 261 fixable candidate failures with none broken) justifies on-by-default.
  P1 and P2 on held-out data measure the true effect. The decision and its reason are then recorded
  in `heldout_config.json` (`entity_link.decision`, `entity_link.reason`) and in `DECISIONS.md`
  before any held-out run; until they are, held-out runs are refused. Two limits to state with it:
  the dev set is contaminated for the linker (it was built with those questions in view, which biases
  toward on), and the dev A/B uses the DDL prompt while H uses the `current` prompt. P1 and P2 then
  report, on held-out data, whether the linker helps; if they disagree with the dev decision, that
  is reported, and H is not changed.
- **The four headline figures**, each defined as in `evals/README.md` section 5 and computed by
  `evals/run_eval.py`, and reported once, from H, on this set:
  1. **hallucination, as two measurements (amended 2026-10-02).** With the evaluator on the
     pipeline's own verifier and the same inputs, the post-verifier hallucinated-number rate is 0% by
     construction (`run_eval.check_pipeline_agreement`), so it cannot be the headline. Figure 1 is
     (a) the **draft rate**: of the answers the pipeline drafted (shipped plus blocked), the share the
     verifier blocked as `UNGROUNDED_ANSWER`; and (b) an **independent audit of the shipped answers** by
     a deliberately separate implementation that shares no code with `ledgerql/verify.py`: an
     extension of `evals/year_audit.py` to all numerals, spelled-out numbers ("forty-two") and
     magnitude words ("billion"). The agreement test stays: it guards the evaluator; the independent
     audit is the measurement. The auditor is `evals/number_audit.py`, written from the plain-language
     spec `evals/NUMBER_AUDIT_SPEC.md` with no import from `ledgerql/` (a test enforces it); built and
     tested on dev runs 2026-10-03 (`reports/number_audit_vs_verify.md`), **before any held-out run**.
     The old figure (the verifier's own rate on shipped answers) may be printed beside them, labelled
     as zero by construction.
     **How the auditor's tiers are counted (fixed 2026-10-03, before any held-out run).** The auditor
     gives every claim one of four statuses (`evals/NUMBER_AUDIT_SPEC.md` section 3), and figure 1(b)
     treats them as follows, with no later choice:
     - `ungrounded` **counts as an invented number.** Figure 1(b) is the share of shipped answers with
       at least one ungrounded claim, and every such claim is listed.
     - `weak` is **reported separately and is not counted** as invented, and never as grounded
       either: its count is printed beside the figure. Weak has two sources and both are treated this
       way: a coarse rounding whose precision is unstated (`about 420 billion` for 416.161 billion),
       and a year or date that the database holds only for a company the SQL does not name.
     - `derived` (a sum, difference, ratio or percentage change of two numeric cells) **counts as
       grounded only under the three-significant-digit rule**: a claim that states fewer than three
       significant digits cannot be derived and is `ungrounded`. Derived claims are counted and
       printed beside the figure.
     - `grounded` is not counted.
     **Figure 1(a) is reported with what it is made of.** A block is the verifier refusing a draft,
     which is an invented number only if the verifier is right. The pipeline stores every blocked
     draft (`blocked_draft`, since configuration H2), and the auditor judges each on the same tiers
     (`evals/audit_vs_verify.py`, `draft_rate`): `invented` if it has an ungrounded claim,
     `verifier false positive` if it has none. Figure 1(a) stays blocked over drafted; printed with
     it, always, are the two parts, so an over-strict verifier cannot pass as a high invention rate;
  2. the **confidently-wrong rate**: wrong answers over answered cases;
  3. **coverage**: answered over answerable cases (`ANSWER` and `ANSWER_WITH_ASSUMPTION`);
  4. the **agree-policy table**: "answer only where both models answered and agree", with
     answers, correct and confidently-wrong before and after, as in DECISIONS 2026-09-29.
  Beside them, always: execution accuracy and the assumption cases answered correctly *with
  the assumption stated*.
- **Order.** The dev A/B is read and the linker decision recorded; then the held-out set is frozen;
  then gen-only P1/P2 and the P3 cells; then H and the 32B pipeline run **once each**; then the
  figures are written into the README with this set named as their source. The 103 dev cases keep
  their figures, labelled "development set".
- **Any other configuration's** held-out numbers are exploratory and are labelled so. If H cannot
  be run as specified, the reason and the replacement are declared (a new entry in
  `heldout_config.json` and in the run log) *before* the replacement is run.

## 7. Run log

Every held-out run is appended to `evals/heldout_runs.md` (commit, model, prompt, flags, job id,
date, headline numbers) whether or not it was flattering. The set is a finite resource: each
configuration is run once for its confirmatory comparison.

## 8. Decided

1. **80 questions** (MJ, 2026-10-01).
2. The pre-registered headline in 6a, amended by MJ: H pinned to a code tree, and the linker decided from
   the dev A/B by a rule fixed before its results; amended again 2026-10-02 (MJ): the linker rule's
   metric (candidate-share harm check) and figure 1 (draft rate plus an independent audit).
3. **Linker setting: on** (2026-10-02), from the dev A/B under the amended rule: Qwen3-30B +0.244 [+0.156,
   +0.340] and XiYanSQL-32B +0.112 [+0.044, +0.188] in the mean per-case change of the correct candidate
   share; neither CI is below zero. Recorded in `heldout_config.json` and `DECISIONS.md`.
4. **Configuration H2 supersedes H1** (2026-10-03, MJ, before any held-out run): the verifier fixed from
   the audit's findings and blocked drafts stored, as one declaration; linker on, unchanged.
5. **Figure 1's tiers** (2026-10-03, MJ, before any held-out run): `ungrounded` counts as invented; `weak`
   is reported separately and not counted; `derived` counts as grounded only under the
   three-significant-digit rule; figure 1(a) is printed with its split into invented blocks and verifier
   false positives.
6. Still open: whether an `informal` share of one quarter of the mention styles is right (3.2),
   and the four confirmatory comparisons in 6.
