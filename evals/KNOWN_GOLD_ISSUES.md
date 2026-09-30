# Known gold issues (the 103 dev cases, frozen at gold v3)

`evals/gold_v3.jsonl` is frozen and pinned by `evals/gold_v3.sha256`. The 103 cases were revised
twice after inspecting model outputs (v2, v3), so their scores no longer cleanly measure
generalisation. **Issues found from now on are listed here. They are not fixed, and there is no
v4.** Headline claims come from the held-out set (`evals/HELDOUT_PROTOCOL.md`). Each entry says
what it does to a score so a reader can discount it.

| case | issue | effect on scores |
|---|---|---|
| R06 | Entity labels are compared by exact resolution (V2: cik, exact ticker, exact stored name). A candidate that labels rows with a brand literal that is not the stored name (`'Apple'`, stored `Apple Inc.`) does not resolve. | 2 of 45 bake-off candidates score wrong on a right answer. Under-credits. |
| C04 | The gold counts distinct companies with a revenue row; a candidate that counts revenue rows returns 15.23 against 15.43. The absolute tolerance of 0.5 percentage points admits it. | Accepts a differently-defined denominator (about 30 of 45 candidates). Over-credits. |
| U03 | "across fiscal years 2024 and 2025 combined" can be read as a sum; gold is the series and the case expects a stated assumption that a balance is not summed (`answer_must_state`). | The SQL comparator accepts the series only; whether the answer states why is the prose grader's. |
| R07 | JPMorgan reports no revenue tag, so the margin is not computable. v3 accepts a NULL margin or (net income, NULL revenue). | Either shape passes; whether the *reason* is stated is the prose grader's (`evals/must_state.py`), not the SQL comparator's. |
| A01, A11, R04 | Strict scoring marks a correct answer wrong when it adds a column the question did not ask for (the average beside the sector, the value beside the company). | By design (V1). Relaxed scoring shows the size: A01 10 vs 42 of 45 candidates, A11 21 vs 38, R04 2 vs 33. |
| L12 | No candidate from any model resolves `The Coca-Cola Company` to the stored `Coca-Cola Company (The)`. | A genuine entity-linking test, not a gold error; kept because it is the case linking must fix. |
| U01, U05, U07 | V8 (raw or scaled both match) changed no verdict in the bake-off (U01) or the Phase 5 runs (all three): every candidate already scaled as asked. | None measured; the rule is untested against real raw-value answers. |
| first-run Phase 5 files | `eval_bridges2_qwen3_30b.jsonl` and `eval_bridges2_qwen25_32b.jsonl` predate later comparator fixes: M06, M08, H06 (30B) and H06 (32B) have recorded verdicts that differ from v1 recomputed. | Historical only; the `_measured` files are the reference and match exactly. |
| dev-set contamination | The entity linker's alias list and heuristics were checked against these questions; the XiYan + DDL configuration was chosen from results on them. | Figures on these 103 cases are optimistic for both. The held-out set is the fair test. |
