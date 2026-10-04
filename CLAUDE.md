# Working rules for this repository

## CI is part of "pushed"

After every push to `main`, check the GitHub Actions run **for that commit** and wait for it to finish.
Do not report "pushed", "done" or "fixed" until it is green. If it is red, say so, read the failing job's
log (the whole comparison, not just its first failing line), and fix it before anything else, or report
it as red.

Why this is here: CI was red on every push from 2026-09-22 to 2026-10-01 and nobody looked for nine days.
The cause was tests that need a gitignored 185 MB database; they had been failing loudly since the
"a missing fixture fails, it does not skip" change, and the red runs were never read (`DECISIONS.md`,
2026-10-01). A fresh clone of HEAD reproduces CI exactly, so run the suite there before pushing.

```bash
gh run list --limit 3 --json databaseId,headSha,conclusion,displayTitle
gh run watch <id> --exit-status
```

## Held-out material

No model runs on held-out questions until the set is frozen and committed (`evals/HELDOUT_PROTOCOL.md`).
The pipeline configuration H is pinned (`evals/heldout_config.json`), and since 2026-10-04 it is **H3,
final: `ledgerql/` is frozen until the held-out runs are done**. Do not change anything under `ledgerql/`
and do not declare an H4. A verifier or pipeline issue found meanwhile goes on
`evals/KNOWN_PIPELINE_ISSUES.md` with its effect on the figures, exactly like a gold issue after the gold
freeze (`evals/KNOWN_GOLD_ISSUES.md`). The freeze is lifted only by MJ, by setting `frozen.lifted` on H3.
