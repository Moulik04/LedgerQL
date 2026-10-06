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
fixed and blocked drafts stored), and how figure 1 counts the auditor's tiers is fixed. H2 and the
tiers were themselves amended once the same day, before anything ran under H2 (a round number passes
as a rounding only when hedged; another company's year or date is ungrounded, not weak).
Amended 2026-10-04, before any held-out question exists and before any held-out run: the auditor
gains a fifth status, **`unresolved`**, and how figure 1 treats it is fixed below. This is in the
auditor and this protocol only; nothing under `ledgerql/` changes, so H2 stands.
Amended 2026-10-04 (later), at MJ's request, before any held-out question exists: H2 is superseded by
**H3** (an accession number is an identifier, not three numbers), **H3 is final and `ledgerql/` is
frozen**, and figure 1(b) is reported as a range, not one number.
Amended 2026-10-04 (night), at MJ's request, before the held-out set is frozen and before any
held-out run: the auditor reads a hyphenated identifier as one claim, grounded by the exact string
in the result or in a string literal of the SQL (below, under figure 1(a)). This is in the auditor
and its spec only; nothing under `ledgerql/` changes, so H3 and the freeze stand.
Amended 2026-10-05, at MJ's request, before the held-out set is frozen and before any held-out
run: in the auditor an identifier is atomic in the evidence too. A number or a year in an answer is
not grounded by one group of an identifier in the result or the SQL. Auditor and spec only.
Amended 2026-10-05 (later), at MJ's request, before any held-out run: what the figures depend on
outside `ledgerql/` (the measurement code and the environment) is pinned separately from H. H3 is
not amended and `heldout_config.json` is not touched.
Amended 2026-10-05 (evening), by MJ's decisions on that draft, before the set is frozen and before
any held-out run: the pinned list is approved; the offline figure commands are held to the pin; and
the database, the generation settings and the model server's versions are enforced, not only
recorded. H3 is not amended.

- **The headline configuration is H3, and it is final** (it supersedes H2; all three are in
  `evals/heldout_config.json`, which is append-only). H3 is H2 with one change under `ledgerql/`, in
  `verify.py`: three or more groups of digits joined by hyphens, such as an SEC accession number
  (`0000037996-26-000015`), are an identifier, one claim that states no quantity, grounded only if
  that exact string is in a string cell of the result (whole: not a piece of a longer run of digits
  and hyphens, never by its groups as numbers, never by the SQL). Two groups stay two numbers, an
  ISO date stays a date, a run of years stays years. Why: in the 30B dev run under H2 (job 47412929)
  the one verifier false positive was `L11`, a lookup whose result was one accession number that the
  draft quoted and the verifier refused as the numbers 37996, 26 and 15; held-out lookups will
  plausibly ask for accession numbers. The rule was written from `verify.py`'s own spec, not from
  the auditor's code. **Checked offline, with no model run**: the verifier at H2's commit and at
  H3's, replayed on that run's 63 stored drafts (`reports/verifier_replay_h3_30b_47412929.md`).
  `L11` goes from blocked to shipped and the auditor grounds every claim in it; no other draft's
  verdict changes; the auditor flags 0 of the 60 shipped. H3 is commit
  `458478a284d2f9a594d88e4b225d494d913078b8`, `ledgerql/` tree
  `8758231d5c11b904e8f3f30df828147a5855952a`, with the same models, jobs, settings and linker
  decision (on) as H2. It is a new declaration and not an amendment of H2 because a run was made
  under H2 (that dev run); no held-out run was made under H1 or H2. The descriptions of H2 and H1
  that follow are kept as written; read "H" as H3.
- **`ledgerql/` is frozen at H3 until the held-out runs are done** (MJ, 2026-10-04), exactly like
  the gold freeze (`evals/KNOWN_GOLD_ISSUES.md`). A verifier or pipeline issue found from now on,
  on dev or on held-out data, is listed in `evals/KNOWN_PIPELINE_ISSUES.md` with what it does to a
  figure. It is not fixed, there is no H4, and no figure is restated. Why: every fix so far was made
  after reading more output, and a configuration that keeps being fixed until the day of the run is
  a configuration chosen with that output in view. Enforced: a test fails if `ledgerql/` differs
  from H3's tree, and `evals/heldout_config.py` refuses any declaration after a final one until the
  freeze is lifted (`frozen.lifted`, set once the held-out runs of H3 and the 32B are in
  `evals/heldout_runs.md`). The freeze covers `ledgerql/` only: the evaluator and the auditor are
  under the rules fixed below. An issue is not a reason H "cannot be run as specified" (the last
  bullet of this section): that clause is for a run that cannot be made at all.
- **The measurement and the environment are pinned too, separately from H (MJ, 2026-10-05).** H3
  pins `ledgerql/`. A figure also depends on code and inputs outside it, and on the versions of the
  packages that parse and execute SQL. So, before any held-out run:
  - **The measurement pin** (`evals/measurement_pin.py`, stored in `evals/measurement_pin.json`):
    the SHA-256 of each file on a named list, not of `evals/` as a tree, because `evals/` also holds
    files that change after the pin (the configuration declarations, the held-out files, the run
    log). The list is every `evals` module that a command producing a held-out figure imports,
    directly or not (the scorer and comparator, the metrics, the auditor and its specification,
    the `answer_must_state` grader and its patterns, the generation-only prompts, the gold check,
    the configuration and pin code), plus `docs/schema.md`, the schema text that `ledgerql/` puts
    in every generation prompt and that H3's tree hash does not cover, plus the job scripts. A test
    fails if such a module is missing from the list, and every other `evals` module is listed with
    the reason it is not pinned. **MJ approved the list on 2026-10-05** (40 files, with the three
    additions beyond MJ's own list: the generation-only prompts, `docs/schema.md` and the ten job
    scripts). **The pin is recorded only after MJ's blind labels are in and any grader
    disagreement is adjudicated**, since that may change the grader. `docs/schema.md` was part of
    the pipeline all along: `ledgerql/` reads it into every generation prompt, and it has been the
    same file (git blob `de17a780`) at the commits of H1, H2 and H3 and since, so every run made
    under any of them read the same schema text.
  - **The environment pin**, in the same record: the SHA-256 of `uv.lock`. A held-out run is refused
    if `uv.lock` differs from it, **or if the installed `duckdb` or `sqlglot` is not the version
    that `uv.lock` names**, since a matching file proves nothing about an environment that was not
    built from it.
  - **A held-out run is refused** (`run_eval`, `gen_only_eval`) unless a pin is recorded and every
    pinned file, `uv.lock` and those two installed versions match it. Until a pin is recorded every
    held-out run is refused. A change after the pin needs a new pin (`M2`), declared before any
    held-out run, as a pipeline change needs a new configuration; the old one is kept.
  - **Whatever can change an output is enforced, not only recorded (MJ, 2026-10-05).** The pin
    also holds, and a held-out run is refused on any difference in:
    - **the database**, by the SHA-256 of the file, taken from the cluster's own record and
      required to equal the laptop's copy, which the offline figures are computed against;
    - **the model server's `vllm`, `transformers` and `torch`**, taken from the same record and
      read again by each run from the environment the server is started from. `setup_env.sh`
      names the vLLM version the development runs were served by (0.29.0, job 47412929's server
      log; MJ confirms it on the cluster before the pin);
    - **the generation settings**: the model, the backend, the seed, the candidate and answer
      temperatures, the number of candidates, the generation-only token limit and the linker must
      equal the declaration (`SETTINGS` in `evals/measurement_pin.py`, which restates H3 where H3
      speaks; a test holds it to H3). A variable that overrides a pipeline default stops the run
      if it is set at all, so nothing depends on what the submitting shell exported. The context
      length and the server flags are set in each pinned job file and inherited by none.
  - **The offline figure commands are held to the pin too.** Figure 1 and the re-scored figures
    are computed on the laptop from retrieved records, by commands that cannot tell a held-out
    run from a development one. Once a pin is recorded, each of them refuses to run if a pinned
    file, `uv.lock`, an installed package or the database differs from it. The files are hashed
    as they are in the working tree, so an edit that was never committed is refused.
  - **Recorded only:** what legitimately varies between runs (the job id, the node, the port, the
    time), in each run's `run_meta.json`, with everything above as that run resolved it.
  - **The weights are pinned to a commit (MJ, 2026-10-05).** Each job used to download its model
    at the repository's `main`. The pin now names the commit of each model's repository
    (`MODEL_REVISIONS`), each pinned job file downloads that commit, and a held-out run is refused
    unless the job's own download cache holds that commit and no other. Each repository's latest
    commit (the 30B 2025-12-03, the 32B AWQ 2024-11-18, XiYanSQL 2025-12-04) is older than the
    first cluster run (2026-09-14), so these are the weights every development run was served.
- **Configuration H2** (superseded by H3 on 2026-10-04; kept as written). H2 supersedes H1; both
  are in `evals/heldout_config.json`, which is append-only. H2 is H1 with two changes under `ledgerql/`, declared together as one
  configuration on 2026-10-03: the verifier (`verify.py`) accepts true values in the forms it used
  to refuse (`$416B`, `416 bn`, `$0.4T`, `FY25`, `3rd`), reads spelled-out numbers, holds a stated
  figure to the precision it states in place of a flat 1% tolerance (a round number such as `420
  billion` is read as a rounding only when the answer hedges it: `about`, `approximately`, `roughly`,
  `around`, `nearly`, `~`), and no longer exempts form-code lookalikes (`391-K`); and the pipeline
  stores the text of every draft the verifier blocks. Why:
  the independent audit found the first on planted values (`reports/number_audit_vs_verify.md`), and
  without the second, figure 1(a) counts blocks, not invented numbers. H2 is commit
  `590188e3ace789fea9e2ef8816ae4444baf5ff83`, `ledgerql/` tree
  `2cbe737057fd2c58abafd324161701dafb9896fa`, with the same models, jobs, settings and linker
  decision (on) as H1. (As first declared, before the hedge rule, it was commit `19a297e` and tree
  `720f4ba`; nothing was run under that, so it was amended in place and not replaced by an H3. The
  declaration records both.) No held-out run was made under H1. The description of H1 that follows is
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
     gives every claim one of five statuses (`evals/NUMBER_AUDIT_SPEC.md` section 3; four until
     2026-10-04), and figure 1(b) treats them as follows, with no later choice:
     - `ungrounded` **counts as an invented number.** Figure 1(b) is the share of shipped answers with
       at least one ungrounded claim, and every such claim is listed.
     - `weak` is **reported separately and is not counted** as invented, and never as grounded
       either: its count is printed beside the figure. Weak is coarse rounding only: a *hedged* round
       number whose precision is therefore unstated (`about 420 billion` for 416.161 billion).
       Unhedged, `420 billion` is `ungrounded`.
     - **A year or date the database holds only for a different company is `ungrounded`**, not weak
       (amended 2026-10-03): another company's period attached to this company's figure is the
       misattributed-period error the year rule exists to catch. The same holds when the SQL has no
       predicate on `cik`, `ticker` or `name` at all (a cross-company query): a single company's
       period label is tied to nothing in the answer.
     - `unresolved` is **reported separately and never counted as ungrounded**, and never as grounded
       either (fixed 2026-10-04, before any held-out run). It is a year or date that some company in
       the database has, under SQL that does restrict the company (a predicate on `cik`, `ticker` or
       `name`) in a way the auditor cannot resolve to a company through the `companies` table: the
       auditor cannot tell, which is not the same as the answer having invented it. The same
       principle as a timeout not scoring as a wrong answer. Figure 1(b)'s numerator is unchanged
       (shipped answers with at least one `ungrounded` claim) and so is its denominator (all shipped
       answers): an answer whose only open claims are unresolved is not in the numerator. (Amended
       2026-10-04, later: that numerator and denominator are the **point rate**; such an answer is in
       the **worst case**'s numerator, below. The claim's status does not change.) The number
       of shipped answers with an unresolved claim is printed beside the figure, and every such claim
       is listed with its answer and SQL. Which SQL forms resolve is fixed in
       `evals/NUMBER_AUDIT_SPEC.md` section 3, and is not changed after seeing held-out results.
     - `derived` (a sum, difference, ratio or percentage change of two numeric cells) **counts as
       grounded only under the three-significant-digit rule**: a claim that states fewer than three
       significant digits cannot be derived and is `ungrounded`. Derived claims are counted and
       printed beside the figure.
     - `grounded` is not counted.
     **Figure 1(b) is reported as a range, not as one number (fixed 2026-10-04 by MJ, before any
     held-out question exists).** Two rates over the same denominator, all shipped answers, always
     printed together:
     - the **point rate**: shipped answers with at least one `ungrounded` claim, over shipped;
     - the **worst case**: shipped answers with at least one `ungrounded` claim *or* at least one
       `unresolved` claim, over shipped. It reads every claim the auditor cannot resolve as
       invented; an answer with both kinds is counted once.
     The README states both, as "point rate (worst case)", wherever figure 1(b) appears; neither is
     quoted alone. With no unresolved claim the two are equal and both are still printed. `weak` and
     `derived` claims enter neither rate, as above. The worst case is a bound, not a
     reclassification: an `unresolved` claim is still listed as unresolved and judged by reading.
     Why: "cannot tell" is not "invented", and it is not "grounded" either, so the honest figure is
     the interval between the two readings. Computed by `evals/audit_vs_verify.py` (`figure_1b`).
     **Figure 1(a) is reported with what it is made of.** A block is the verifier refusing a draft,
     which is an invented number only if the verifier is right. The pipeline stores every blocked
     draft (`blocked_draft`, since configuration H2), and the auditor judges each on the same tiers
     (`evals/audit_vs_verify.py`, `draft_rate`): `invented` if it has an ungrounded claim,
     `verifier false positive` if the auditor grounds every claim, and `unresolved` (2026-10-04) if
     it has no ungrounded claim but one the auditor cannot resolve: such a block is counted as
     neither an invention nor a verifier false positive. Figure 1(a) stays blocked over drafted;
     printed with it, always, are the three parts, so an over-strict verifier cannot pass as a high
     invention rate.
     **An identifier in a blocked draft (fixed 2026-10-04, night, before any held-out run).** The
     auditor reads three or more hyphen-joined digit groups as one claim, grounded by the exact
     string, whole, in a string cell of the result **or in a string literal of the executed SQL**
     (`evals/NUMBER_AUDIT_SPEC.md` 1.8 and 3.8), as it already grounds a year by the SQL's
     literals. The frozen verifier grounds an identifier by the result only
     (`evals/KNOWN_PIPELINE_ISSUES.md`), so it blocks an answer that restates an accession number
     the query was given. Restating it is not inventing it: the auditor finds nothing ungrounded in
     such a draft and the block is counted as a **verifier false positive**. Before this the
     auditor read the identifier as three ungrounded numbers and would have counted the block as
     `invented`. An identifier in neither place is `ungrounded`, one claim. Figure 1(b) is not
     affected under H3: an answer whose identifier is not in the result is never shipped.
     **An identifier is atomic in both directions (fixed 2026-10-05, before any held-out run).** A
     number or a year in an answer is not grounded by one group of an identifier in a string cell of
     the result or in the SQL (`26`, or `2024`, beside `0000037996-26-000015` or `12-2024-7`), as
     an ISO date in a string cell was already a date and not three numbers
     (`evals/NUMBER_AUDIT_SPEC.md` 3.3, 3.4). Any other numeral in the same cell still counts. This
     can move figure 1(b) and the split of 1(a) in one direction only, toward more claims counted
     `ungrounded`: a number that used to be grounded by such a group no longer is;
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
   the audit's findings and blocked drafts stored, as one declaration; linker on, unchanged. Amended
   once the same day, before anything ran under it: a round number passes as a rounding only when
   hedged.
5. **Figure 1's tiers** (2026-10-03, MJ, before any held-out run): `ungrounded` counts as invented, and
   includes a year or date the database holds only for a different company; `weak` is hedged coarse
   rounding only, reported separately and not counted; `derived` counts as grounded only under the
   three-significant-digit rule; figure 1(a) is printed with its split into invented blocks and verifier
   false positives.
6. **The `unresolved` status** (2026-10-04, MJ, before any held-out question exists): a year or date
   some company has, under SQL whose company predicate the auditor cannot resolve, is `unresolved`:
   reported separately, never counted as ungrounded or as grounded, with figure 1(b)'s numerator and
   denominator unchanged; a blocked draft with only such claims is its own part of figure 1(a). With
   no company predicate at all the query is cross-company and the label stays `ungrounded`.
7. **Configuration H3 supersedes H2, and is final** (2026-10-04, MJ, before any held-out question
   exists): an accession number, or any three or more hyphen-joined digit groups, is one identifier
   claim grounded only by the exact string in the result. Checked offline on the 63 drafts of dev run
   47412929: `L11` flips to shipped and passes the auditor, nothing else changes. Linker on, unchanged.
8. **`ledgerql/` is frozen at H3 until the held-out runs are done** (2026-10-04, MJ): a later verifier
   or pipeline issue goes on `evals/KNOWN_PIPELINE_ISSUES.md` and is not fixed, exactly like the gold
   freeze.
9. **Figure 1(b) is a range** (2026-10-04, MJ, before any held-out question exists): the point rate
   (shipped answers with an ungrounded claim over shipped) and a worst case (shipped answers with an
   ungrounded or an unresolved claim over shipped), always together.
10. **The auditor reads an identifier as one claim** (2026-10-04, MJ, before the set is frozen and
   before any held-out run): three or more hyphen-joined digit groups, grounded by the exact string
   in the result or in a string literal of the SQL. A block for restating an identifier the query
   was given is a verifier false positive in figure 1(a)'s split. The verifier is unchanged and
   frozen.
11. **In the auditor an identifier is atomic in the evidence too** (2026-10-05, MJ, before the set is
   frozen and before any held-out run): its groups ground no number and no year. On dev no claim
   changes (291 distinct stored texts; two of them have an identifier in their evidence).
12. **The measurement and the environment are pinned separately from H** (MJ, 2026-10-04 and
   2026-10-05; H3 is not amended). A named file list and the hash of `uv.lock`, in
   `evals/measurement_pin.json`; a held-out run is refused unless a pin is recorded and the files,
   `uv.lock` and the installed `duckdb` and `sqlglot` match it; every run records its resolved
   versions, the model server's included. MJ approved the list on 2026-10-05 and decided that the
   database, the generation settings and the server's versions are enforced, and that the offline
   figure commands refuse on a tree that differs from the pin. **Owed:** the cluster's record
   (`docs/bridges2.md`), then the pin itself, recorded after the blind labels are in and any
   grader disagreement is adjudicated.
13. Still open: whether an `informal` share of one quarter of the mention styles is right (3.2),
   and the four confirmatory comparisons in 6.
