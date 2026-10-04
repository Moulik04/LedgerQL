# Known pipeline issues (`ledgerql/`, frozen at configuration H3)

`ledgerql/` is frozen at configuration **H3** (`evals/heldout_config.json`, `evals/HELDOUT_PROTOCOL.md`
6a) from 2026-10-04 until the held-out runs are done. H3 is the final configuration: **a verifier or
pipeline issue found from now on is listed here. It is not fixed, and there is no H4** before the
held-out runs. This is the same rule as the gold freeze (`evals/KNOWN_GOLD_ISSUES.md`): a fix made
after looking at more output is a configuration chosen with that output in view. Each entry says what
it does to a figure so a reader can discount it. An issue found in a held-out run is listed here too,
and the figures are not restated.

The freeze covers `ledgerql/` only. The evaluator, the auditor and the reports (`evals/`) are not
under it; their rules for figure 1 are fixed separately in the protocol.

| where | issue | effect on the figures |
|---|---|---|
| `verify.py`, identifiers | An identifier is grounded only by the exact string in the result, never by the SQL. An answer that repeats an accession number found only in the query's filter (`WHERE adsh = '...'`, result a form type) is blocked. The rule followed the wording "only if the exact string appears in the result"; restating an identifier the user supplied is not an invention (MJ, 2026-10-04). It stays here and is not fixed. | A true statement is blocked: a block in figure 1(a) that is a verifier false positive. **The auditor does not say so:** it reads an identifier that is not in the result as three ungrounded numbers, so figure 1(a)'s split files this block under `invented` (checked 2026-10-04 on a constructed answer). If it happens, the split overstates inventions and understates verifier false positives by one per such block, and the block has to be read by hand. Not observed on dev. |
| `verify.py`, identifiers | Only three or more hyphen-joined digit groups are an identifier. Two groups (a ZIP+4 such as `94043-1351`) are read as two numbers, and an accession number written without its hyphens (`000003799626000015`) is read as one number; each is refused even when the result holds that string. | A true statement in either form is blocked: a verifier false positive in figure 1(a)'s split. Unchanged from H2. Not observed on dev; the database's only hyphenated identifier is `adsh`. |
| `verify.py`, identifiers | A hyphen that is not the ASCII `-` (U+2011, an en dash) does not join an identifier: `0000037996‑26‑000015` is read as three numbers and refused. | As above: a verifier false positive in figure 1(a)'s split if a model writes one. Unchanged from H2. Not observed on dev. |

All three were found on 2026-10-04 while writing H3's identifier rule, by trying the forms, not from
a model's output. Checked against every stored dev draft (594 in 12 report files, 301 distinct): one
draft states an identifier (`L11`, job 47412929), and it is the case H3 fixes.
