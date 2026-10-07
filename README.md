# LedgerQL

> **Status: held-out figures pending.** The held-out set is still being built and no model has run
> on it; each figure marked `[held-out: pending]` will be filled from pre-registered runs, each made
> once ([protocol, section 6a](evals/HELDOUT_PROTOCOL.md)). Every other number is from the 103-case
> development set.

Questions in plain English about company financials, answered by local open-weight models that
write SQL over SEC filings. It is built so that every question ends one of three ways: an answer
taken from the data, an answer that says what it assumed, or a refusal that says why.

## The problem

Point a language model at a database of filings and ask "What was Apple's revenue for 2024?". You
get a fluent sentence with a number in it. That sentence can be wrong in ways nothing on the page
shows:

- the SQL ran and returned a number, for the wrong company, period or metric;
- "2024" was quietly read as Apple's fiscal 2024, which ended in September, and the answer never
  says so;
- the sentence states a figure, or a year, that is not in the query result at all.

With financial data a confident wrong number costs more than no number, and a system that is
usually right is not usable if nothing separates the answers that are right from the ones that are
not.

LedgerQL is a text-to-SQL pipeline built around that. Each question ends in one of three states.
These are real outputs from a development-set run (Qwen3-Coder-30B, job 47412929):

| state | question | what comes back |
|---|---|---|
| `ANSWER` | What was Apple's revenue in fiscal year 2025? | "The result shows a value of 416,161,000,000.0." |
| `ANSWER_WITH_ASSUMPTION` | What was Apple's revenue for 2024? | "The result shows a value of 391,035,000,000.0. 2024 was read as fiscal year 2024, which ended on September 30, 2024." |
| `ABSTAIN` | What was JPMorgan's net profit margin in fiscal year 2024? | `NO_DATA`: "JPMorgan Chase has no revenue figure under the standard revenue tags in this database. [...] This is a documented gap, not missing data." |

Three things this repository is meant to show:

1. **A pipeline where the sentence is checked, not trusted.** Every number, year, date and filing
   identifier in an answer has to be found in the result of the query that ran, or the answer is
   withheld. The model that writes the sentence never sees the question, so it has nothing to
   answer from except the table.
2. **An evaluation whose headline cannot be chosen after the fact.** The development questions
   were looked at too often to be a fair test. The headline comes from 80 new questions that no
   model has been run on, with the figures, the statistics and the exact code fixed in advance,
   and the pipeline frozen until that run is done.
3. **An account of where our own metrics were wrong.** Four times a headline number turned out to
   measure something other than what its name said. Each is written up
   [below](#what-our-metrics-got-wrong), with the number before and after.

Everything runs on local, open-weight models: a 7B model through Ollama on a laptop, and 30B-class
models through vLLM on a university GPU cluster (PSC Bridges-2). No hosted LLM API is called
anywhere.

## Results

### Held-out set (the headline): not yet run

Configuration **H3** (Qwen3-Coder-30B-A3B at full precision, five candidates, entity linking on),
run once on the frozen 80-question set. The four figures, their definitions and their order are
those of protocol 6a. Nothing in this table is a result.

| | figure | how it is computed | Qwen3-Coder-30B, H3 |
|---|---|---|---|
| 1a | **Draft rate** | drafted answers the verifier blocked, over all drafted (shipped plus blocked) | `[held-out: pending]` |
| | of the blocks: invented number / verifier false positive / unresolved | the independent auditor's verdict on each stored blocked draft | `[held-out: pending]` / `[held-out: pending]` / `[held-out: pending]` |
| 1b | **Invented numbers in shipped answers**, point rate (worst case) | shipped answers with an ungrounded claim, over shipped (the same, counting every claim the auditor cannot resolve as invented) | `[held-out: pending]` (`[held-out: pending]`) |
| | beside it: shipped answers with a weak / derived / unresolved claim | counted separately, in neither rate | `[held-out: pending]` / `[held-out: pending]` / `[held-out: pending]` |
| 2 | **Confidently-wrong rate** | wrong answers over answered cases | `[held-out: pending]` |
| 3 | **Coverage** | answered over answerable cases (the template has 40 `ANSWER` and 16 `ANSWER_WITH_ASSUMPTION`) | `[held-out: pending]` |
| | beside them: execution accuracy | `ANSWER` cases whose result matches gold, strict (relaxed beside it) | `[held-out: pending]` (`[held-out: pending]`) |
| | beside them: assumption cases answered correctly with the assumption stated | of the `ANSWER_WITH_ASSUMPTION` cases | `[held-out: pending]` |

The pipeline's own verifier will report 0% invented numbers on the answers it shipped. That
figure is zero by construction ([why](#4-0-by-construction)) and is not a measurement; if printed,
it is labelled so.

Figure 4, the agree-policy table ("answer only where both models answered and agree"), pairing H3
with Qwen2.5-Coder-32B AWQ run the same way:

| | answers | correct | confidently wrong |
|---|---|---|---|
| Qwen3-Coder-30B alone | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |
| Qwen2.5-Coder-32B AWQ alone | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |
| only where both answered and agree | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |

The four confirmatory comparisons (protocol section 6). A claim that something helps needs the
95% bootstrap interval to exclude zero and an exact sign test below 0.05. Anything short of that is
reported as "not shown", never as "no effect".

| | comparison | net cases gained minus lost | 95% CI | sign test | reading |
|---|---|---|---|---|---|
| P1 | Qwen3-30B with vs without entity linking | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |
| P2 | XiYanSQL-32B with vs without entity linking | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |
| P3 | XiYanSQL-32B on the DDL prompt vs the other eight model and prompt cells (a pick made in hindsight on the development set) | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |
| P4 | the agree policy vs either model alone | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` | `[held-out: pending]` |

### Development set (not the headline)

The 103 development cases were revised twice after reading model output, and the entity linker,
the answer framing and the refusal registry were all written with these questions in view. These
figures are optimistic and are here to show what the pipeline does, not how well it generalises.

| figure | value | run |
|---|---|---|
| Draft rate (1a) | 4 of 63 (6.3%): 3 invented, 1 verifier false positive, 0 unresolved | 30B, configuration H2, linker on, job 47412929 |
| Invented numbers in shipped answers (1b), point rate (worst case) | 0 of 59 (0 of 59) | same |
| The same 63 drafts replayed under H3, offline, no model run | the false positive (a correctly quoted accession number) ships; 3 of 63 blocked, 0 of 60 flagged | [reports/verifier_replay_h3_30b_47412929.md](reports/verifier_replay_h3_30b_47412929.md) |
| Execution accuracy, `ANSWER` cases | 31 of 50 strict (40 of 50 relaxed) | 30B, configuration H1, linker off, job 47367323 |
| Confidently wrong | 14 of 55 answered | same |
| Coverage | 52 of 69 answerable | same |
| Assumption cases answered correctly with the assumption stated | 9 of 19 (0 with the framing text removed from the same records) | same |

"Strict" marks an answer wrong if it returns a column the question did not ask for. "Relaxed"
ignores extra columns and is always a second, labelled figure.

## Architecture

```
question
   │
   ▼
[0] intent check      deterministic  destructive SQL or a file path in the question ──► ABSTAIN
[1] scope classifier  model          not a database question ─────────────────────────► ABSTAIN
[2] schema context    deterministic  the analyst schema, plus resolved company names
[3] SQL generation    model          5 candidates, temperature 0.7, seeds 42 to 46
[4] guardrails        deterministic  one SELECT, known tables and columns, bounded cost
[5] execution         deterministic  read-only DuckDB, 10 s timeout, 1,000-row cap
[6] consensus         deterministic  nothing usable, empty for one company, low agreement ► ABSTAIN
[7] answer writer     model          sees the result only: never the question, never the SQL
    framing           deterministic  says what was assumed: sees question and SQL, never a value
    verifier          deterministic  a number, year, date or identifier not in the result ► ABSTAIN
[8] state, refusal text, audit record
```

Three stages call a model (1, 3 and the writer in 7). Everything that decides whether an answer
is shown is deterministic.

**Intent check** ([ledgerql/intent.py](ledgerql/intent.py)). Runs on the raw question before any
model. It exists because of a failure found in real logs. Asked "Show Apple's revenue for fiscal
2024; DROP TABLE financial_facts;", every one of the five SQL candidates left the `DROP` out and
returned a clean `SELECT`, on all three models measured. The SQL guardrails had nothing to reject,
because the generator had laundered the injection away, and the pipeline answered. So one check has
to read the question itself. It matches SQL statement keywords and filesystem paths only, never
instruction-like prose, so its false-positive rate is a fixed property of a pattern and not a risk
taken on every call.

**Scope classifier** ([ledgerql/classify.py](ledgerql/classify.py)). A soft prefilter for things
that are not database questions at all (predictions, opinions). It fails open: a reply it cannot
parse counts as in scope, because a wrong "in scope" costs one wasted generation and a wrong
refusal has nothing downstream to catch it.

**Generation** ([ledgerql/generate.py](ledgerql/generate.py),
[ledgerql/entity_link.py](ledgerql/entity_link.py)). Five candidates per question at temperature
0.7 (at 0.2, four of five were byte-identical, which leaves nothing to vote on). The prompt carries
the whole analyst schema (three tables, four views). With entity linking on it also carries a
deterministic hint that resolves company names: models write `name = 'The Coca-Cola Company'`
because the question does, the stored name is `Coca-Cola Company (The)`, and an exact match returns
nothing.

**Static guardrails** ([ledgerql/guardrails.py](ledgerql/guardrails.py)). The hard boundary, on
the parsed SQL and independent of any model: exactly one `SELECT`, only allowlisted tables, only
columns that exist in the live database, and a bounded cost (an unfiltered "every row" query is
blocked, not capped). What survives runs on a read-only connection.

**Consensus** ([ledgerql/consensus.py](ledgerql/consensus.py),
[ledgerql/result_shape.py](ledgerql/result_shape.py)). Candidates are grouped by the values they
return, not by SQL text or column names, so two phrasings that return the same rows agree.
Agreement is the winning group's share of all five requested, so a candidate that failed counts
against it; below 0.6 the pipeline abstains (`LOW_AGREEMENT`). Two structural rules sit beside the
vote. A generator that declines in SQL (`SELECT NULL ... WHERE 1 = 0`) is a `SCHEMA_MISMATCH`. An
empty result from a query pinned to one company is `NO_DATA`, while an empty result from a filter
question ("which companies had negative total assets") is a complete answer and is left alone.

**Answer writer** ([ledgerql/answer.py](ledgerql/answer.py)). The model sees the winning result's
column names and rows and nothing else. With no question to answer from memory, all it can do is
describe the table in front of it, which is what makes the verifier a meaningful check.

**Framing** ([ledgerql/frame.py](ledgerql/frame.py)). A writer that cannot see the question cannot
say which year "most recent" resolved to, or that "Google" was read as Alphabet. The framing adds
those sentences, and no model is involved. It gets the question, the winning SQL and the result's
shape (column names and row count), never a value. The labels it states (a fiscal year, the date a
period ended) come from the question, the SQL or a keyed lookup in the database. A framing that
states something the question did not fix is what makes the state `ANSWER_WITH_ASSUMPTION`.

**Verifier** ([ledgerql/verify.py](ledgerql/verify.py)). Runs on the writer's text plus the
framing. A number must match a result value at the precision the sentence states, whether it is
written in digits, with a magnitude word or abbreviation, or spelled out; a round number passes as
a rounding only when the sentence hedges it ("about"). A year must be in a result cell, be a
literal in the SQL that ran, or be a label the framing looked up. A filing identifier must be in
the result as the exact string. One ungrounded claim withholds the whole answer
(`UNGROUNDED_ANSWER`), and the blocked draft is kept in the audit record so the block can be judged
afterwards.

**Abstain templates** ([ledgerql/refusal.py](ledgerql/refusal.py),
[ledgerql/known_gaps.json](ledgerql/known_gaps.json)). A refusal is a reason code and a sentence.
The codes are `OUT_OF_SCOPE`, `SCHEMA_MISMATCH`, `AMBIGUOUS`, `NO_DATA`, `COST_LIMIT`,
`LOW_AGREEMENT`, `UNGROUNDED_ANSWER` and `EXEC_ERROR` (no stage emits `AMBIGUOUS` today: an
ambiguous question ends as an answer with a stated assumption, or under another code). The
sentence is not generated: one template
per code, filled only from the question and the entity linker, plus a registry of seven documented
data gaps (annual figures only, no segment breakdowns, companies with no standard revenue tag, and
so on), each tied to a quotation in [docs/schema.md](docs/schema.md) that a test looks up. Tests
also check that no template can emit a number that is not in the question or the linker's output,
and that the module imports no model client.

**Audit** ([ledgerql/audit.py](ledgerql/audit.py)). One JSON record per request, refusals
included: every candidate, the guardrail events, the result, the answer or the blocked draft.

Two things were built, measured and removed. A repair step that fed an execution error back to the
generator rescued five abstains on the 30B, of which one was correct and three turned a required
refusal into a wrong answer; it is off. A fitted confidence model was planned and never built: the
`confidence` in a response is the vote's agreement and nothing more.

## Evaluation design

**Frozen development gold.** 103 hand-written cases in twelve tiers (lookups, aggregations, ratios,
unit and period traps, ambiguous questions, out-of-scope requests, injection attempts, questions
about columns that do not exist): 50 expect an answer, 34 a refusal, 19 an answer with a stated
assumption. The gold was revised twice after reading model output (v2, v3). Each time the rules
were written and committed before anything was re-scored, applied to all 103 cases, and every
verdict that moved was reported in both directions. Then the set was frozen and pinned by hash,
which a test checks. Problems found since are listed in
[evals/KNOWN_GOLD_ISSUES.md](evals/KNOWN_GOLD_ISSUES.md) with what each does to a score. They are
not fixed and there is no v4, because a set revised with model output in view no longer measures
generalisation cleanly.

**Blind held-out set.** 80 questions in the same tier mix (40 answer, 16 assumption, 24 refuse).
Which companies get asked about, and in which naming style (brand, legal name, ticker, informal),
was drawn by a seeded shuffle from companies that are not in the development set, and committed
with its hash before any question existed, so neither writer chose them. The questions are written
by the author without looking at any model output or at which development questions models fail.
The gold SQL is written by Claude, the AI assistant this project was built with, from the question,
the schema and the database alone, with no model run and no report open; each gold query has a
second, independently written formulation that must return the same result, and the author reviews
all of it. Stated plainly: the gold writer has seen a great deal of model output on the development
set and cannot unsee it, and the safeguards against that are procedural. The set is then frozen by
hash. Only then may a model run on it; the evaluation scripts refuse a held-out file without a
matching hash. Each configuration is run once, and every run is logged whether or not it flatters.

**Pre-registration.** Fixed before any held-out run: the metrics; the four headline figures above
and the order they are produced in; the four comparisons and the test each must pass; and how the
auditor's verdicts are counted. The power is stated too: with 40 answer cases, about 34 of which
name a company, the set can confirm an entity-linking effect of about six cases and cannot confirm
a smaller one. One decision that could have been made on the held-out results was moved off them:
whether entity linking is on in the headline configuration was decided from development data, by a
rule fixed before that data was read, because choosing it from held-out results and then reporting
the headline on the same results is selection on the test set. Every amendment to the protocol is
dated and says what had and had not been seen when it was made.

**Frozen pipeline.** The headline configuration is a code state, not a description: a commit and
the git tree hash of `ledgerql/`, recorded in
[evals/heldout_config.json](evals/heldout_config.json), which is append-only (H1, H2, H3). A test
fails if `ledgerql/` differs from the active declaration, and the evaluation scripts refuse a
held-out run on any other tree. H3 is final. Until the held-out runs are done, a pipeline or
verifier problem is listed in [evals/KNOWN_PIPELINE_ISSUES.md](evals/KNOWN_PIPELINE_ISSUES.md) with
its effect on the figures, and is not fixed. The reason is the same as for the gold: every fix so
far followed reading more output, and a configuration that keeps being fixed until the day of the
run is one chosen with that output in view.

## What our metrics got wrong

### 1. "Abstain precision" was two metrics in one

For three phases the headline safety number sat at 27 to 29% on every model, below the 33.0% that
refusing every question would score. It looked as if the refusal layer carried no signal.

The documentation defined abstain precision as a question about the decision (was refusing the
right call). The harness computed decision and exact reason-code match. Split apart on the same
30B run: **71.0% of refusals were the right call, and 40.9% of those named the right reason**. The
blended 29.0% described a system that does not know when to refuse. The real one refuses correctly
most of the time and then explains itself badly, and those two failures have different fixes.

It came to light sideways: a diagnostic written to break refusals into categories disagreed with
the report it was diagnosing. The cause was two copies of one definition. Both now import a single
module, a bare "abstain precision" is never reported, and every precision figure is printed beside
the always-refuse baseline. The same review found recall dividing by 53 cases (the 34 that must be
refused plus the 19 where refusing is merely allowed), which scored the best possible outcome on
an assumption case as a missed refusal. Corrected, recall on that run went from a reported 41.5%
to 58.8%.

### 2. "0.0% hallucinated numbers" did not count years

The verifier skipped any number from 2000 to 2099, because years appear constantly in correct
answers, and its separate year check ran only when the result had a `fiscal_year` column. Counting
years, **17 of the 30B's 55 answers (31%) stated a fiscal year that was in no result cell**. All 17
were 2021, 2022 or 2023. The database covers fiscal 2024 to 2026, so none of them could have been
true. Apple's fiscal 2025 revenue was narrated as "fiscal year 2022".

The cause was the design itself. The writer is kept blind to the question so that it cannot invent
numbers; that left it to invent the one thing it could not see, the period. The verifier now
covers years. Applied to that run it removed 17 answers, and execution accuracy fell from 62.0% to
48.0%: nine of the 17 had the right value beside the invented year, seven of them on plain answer
cases. Getting those back took the deterministic framing and a writer prompt that says not to
state a period the table does not show. A looser verifier was not an option.

### 3. The gold standard was marking right answers wrong

In a nine-way bake-off (three models, three prompts, 2,250 candidates), eight of the 50 answer
cases were solved by no candidate at all, and the write-up concluded that generation was the
ceiling: "no model or prompt raises pass@N materially". Auditing the eight against their gold found
that **seven were gold errors**. The gold returned columns the question never asked for, or
multiplied by 100 where the question said "ratio" and no candidate did. One tolerance, meant as
half a percentage point, was applied as a relative 50% and credited nine answers of 48.96 against a
gold value of 94.6.

That conclusion was retracted: it had measured a scoring ceiling. Under the original gold the nine
cells solved 30 to 36 of 50 cases with at least one of five candidates; under the corrected rules,
34 to 48, and the cases solved by any cell went from 42 to 49. The remaining one is a real failure
(the Coca-Cola name above) and is the reason entity linking was built. The rules were derived from
each question's wording, committed before re-scoring, and applied to every case, and the verdicts
that moved against a model are reported with the ones that moved for it. The price was the
development set's standing as a clean test, which is why it was then frozen and a held-out set
commissioned.

### 4. "0% by construction"

The evaluator measured the hallucinated-number rate by running the pipeline's own verifier over
the answers the pipeline shipped. Any answer that shipped had already passed that verifier on the
same inputs. The rate is zero whatever the model does: it counts the pipeline's blocks and nothing
else.

This surfaced while fixing the opposite error. The evaluator had been verifying answers without
the labels the framing states, and reported 14.3% and 6.8% invented numbers on two runs where the
pipeline had verified the same text correctly. Making the evaluator agree with the pipeline (now a
test, and a live run that disagrees with its own pipeline exits as failed) is what made the figure
trivially zero.

So the headline is two other measurements. The **draft rate** counts what the verifier blocked,
and since a block is an invented number only if the verifier was right, each blocked draft is
stored and judged. The **audit of shipped answers** is done by a second implementation
([evals/number_audit.py](evals/number_audit.py)) written from a plain-language specification, which
imports nothing from `ledgerql/` (a test checks) and reports its rate as a range, because "cannot
tell" is neither "invented" nor "grounded". An earlier "independent" audit of years had imported
the verifier's own extraction code and so could only see what the verifier saw.

The second implementation earned its keep at once. On planted values the verifier caught 14 of 21
invented figures and accepted 9 of 14 correct restatements; the auditor, 21 and 14. The verifier
read digits only, so it passed every spelled-out number, and it refused `$416B`. It was fixed from
those findings. On the latest development run the two agree on every shipped answer, and of the
four drafts the verifier blocked, three were invented and one was a false positive (a correctly
quoted accession number read as three separate numbers), fixed in the final configuration.

## Limits

- **There is no held-out result yet.** Until the placeholders above are filled, nothing here says
  how the system does on questions it was not developed against.
- **The sets are small.** The held-out set has 80 questions, 40 of them answer cases. It can
  confirm an effect of about six cases and not a smaller one.
- **One run per configuration.** On the development set, two runs with the same model, prompts and
  seeds disagreed on the vote's pick in 10 of 50 cases. Each held-out configuration is run once, so
  its figures carry that noise and come with no run-to-run variance.
- **Grounded is not correct.** The verifier and the auditor check that a sentence matches the query
  result, not that the query answers the question. A wrong query restated faithfully passes both,
  which is why the confidently-wrong rate is reported beside them (14 of 55 on the development
  run above).
- **The auditor shares its evidence with the pipeline** (the result and the SQL). A number that
  happens to equal the row count or an unrelated cell is grounded by coincidence, and some period
  labels it cannot tie to a company at all, which is what the worst-case rate is for.
- **Stated assumptions are graded by patterns and a weak judge.** Regular expressions decide 22 of
  the 27 rubric items. A small local model decides the other five; on 20 constructed answers its
  recall was 0.60 and its precision 0.86. The 28 calibration labels were written by Claude. The
  author's blind second labelling covers 14 of them (the four marked as judgement calls and ten
  drawn at random). Blind, it agreed with the grader on 6 of the 14 and with the first labeller
  on 8. On re-reading, five of the author's eight disagreements with the grader were resolved in
  the grader's favour (in four the text does not contain the item at all); three stand, and are
  known false fails of the grader, whose patterns were left as they were. After adjudication the
  grader matches the final call on 11 of 14 (`reports/must_state_agreement.md`).
- **Development-set contamination.** The entity linker's alias handling, the framing's rules and
  the refusal registry were written with the development questions in view. How often a held-out
  question falls through to a generic refusal sentence, or gets no assumption stated, is unknown.
- **Known pipeline issues are frozen in**, not fixed. For example, an answer that repeats a filing
  identifier the user typed, where the query result does not contain it, is blocked. The list is
  [evals/KNOWN_PIPELINE_ISSUES.md](evals/KNOWN_PIPELINE_ISSUES.md).
- **The agree policy needs two 30B-class models per question.** It is a research result, not a
  default that runs on a laptop.
- **The data is narrow.** S&P 500 companies, eight quarters of filings (2024q3 to 2026q2), annual
  figures from 10-Ks only, no segment or geographic breakdowns. Fiscal-year labels are the filers'
  own and are not contiguous even within one company.
- **The prose is flat.** A writer that cannot see the question writes "The result shows a value of
  391,035,000,000.0." That is the cost of the design.
- **It is a library and an evaluation, not a product.** The pipeline is one Python function,
  `ask()`. There is no service and no interface.

## Running it

```bash
brew install uv
make setup        # dependencies and pre-commit
make test         # the test suite; needs no model and no download
make data         # builds data/ledgerql.duckdb from the SEC's Financial Statement Data Sets
```

With the database built and Ollama serving `qwen2.5-coder:7b`:

```python
from ledgerql.pipeline import ask

r = ask("What was Apple's revenue for 2024?")
r["state"]        # ANSWER, ANSWER_WITH_ASSUMPTION or ABSTAIN
r["answer"]       # the sentence, or None
r["assumptions"]  # what the answer assumed
r["reason_code"], r["refusal"]  # why not, when it abstains
```

`LEDGERQL_ENTITY_LINK=1` turns entity linking on. The 30B-class runs use the scripts in
[scripts/bridges2/](scripts/bridges2/) ([docs/bridges2.md](docs/bridges2.md)).

## Where things are

| | |
|---|---|
| [ledgerql/](ledgerql/) | the pipeline, frozen at configuration H3 |
| [evals/](evals/) | gold sets, scorers, the independent auditor, the held-out protocol and configuration |
| [evals/README.md](evals/README.md) | how every metric is defined and scored |
| [evals/HELDOUT_PROTOCOL.md](evals/HELDOUT_PROTOCOL.md) | the held-out set: roles, the freeze, the pre-registered analyses |
| [DECISIONS.md](DECISIONS.md) | the dated log of every decision, wrong turn and correction; the source for everything above |
| [reports/](reports/) | every committed run and the reports computed from them |
| [docs/schema.md](docs/schema.md) | the database the models see |

## License

MIT. See [LICENSE](LICENSE).
