# Independent number audit beside the verifier (dev runs only)

`evals/number_audit.py` (spec: `evals/NUMBER_AUDIT_SPEC.md`) against `ledgerql/verify.py`, on every
answered record of the committed dev pipeline runs. A shipped answer has passed the verifier, so
every disagreement is the auditor flagging something the verifier let through.

| run | answered | auditor flags | unresolved | weak | derived |
|---|---|---|---|---|---|
| 30B rerun 47367323 | 55 | 0 | 0 | 0 | 0 |
| 30B partial 47314853 | 42 | 0 | 0 | 0 | 0 |
| 32B 47314855 | 44 | 0 | 0 | 0 | 0 |

Disagreements: 0 of 141 answered records.

## Figure 1(b) as a range

The point rate is the shipped answers with an ungrounded claim over all shipped answers. The
worst case adds every shipped answer with a claim the auditor cannot resolve, as if each such
claim were invented; an answer with both is counted once.

| run | shipped | point rate | worst case |
|---|---|---|---|
| 30B rerun 47367323 | 55 | 0 of 55 (0.0%) | 0 of 55 (0.0%) |
| 30B partial 47314853 | 42 | 0 of 42 (0.0%) | 0 of 42 (0.0%) |
| 32B 47314855 | 44 | 0 of 44 (0.0%) | 0 of 44 (0.0%) |

## Unresolved claims in shipped answers: 0

A year or date some company in the database has, under SQL that restricts the company in a way
the auditor cannot resolve (a pattern, a range, a negation, a subquery that names none). It can
neither be tied to the answer nor ruled out: reported here, never counted as ungrounded.

## Blocked drafts (figure 1a): an invented number, or the verifier being wrong?

Of the answers the pipeline drafted (shipped plus blocked), the ones the verifier blocked, each
judged by the auditor on the stored draft. A block the auditor also flags is an invented number;
a block the auditor grounds completely is a verifier false positive. A block with no ungrounded
claim but one the auditor cannot resolve is unresolved: counted on neither side. Runs from before
2026-10-03 did not store the draft, so their blocks cannot be judged.

| run | drafted | blocked | invented | verifier false positive | unresolved | draft not stored |
|---|---|---|---|---|---|---|
| 30B rerun 47367323 | 59 | 4 | 0 | 0 | 0 | 4 |
| 30B partial 47314853 | 46 | 4 | 0 | 0 | 0 | 4 |
| 32B 47314855 | 47 | 3 | 0 | 0 | 0 | 3 |

## Planted invented values, both implementations

The true value is 416,161,000,000 (fiscal 2025, AAPL). Each text states something invented.

| form | text | verifier catches | auditor catches | verdict |
|---|---|---|---|---|
| digits | Revenue was 417,500,000,000.0. | yes | yes | agree |
| decimal | Revenue was 417500000000.5. | yes | yes | agree |
| magnitude word | Revenue was $417.5 billion. | yes | yes | agree |
| mis-scaled word | Revenue was 416.161 million. | yes | yes | agree |
| abbreviation B | Revenue was $417.5B. | yes | yes | agree |
| abbreviation bn | Revenue was 417.5 bn. | yes | yes | agree |
| abbreviation T | Revenue was 0.45T. | yes | yes | agree |
| abbreviation K | Revenue was 417500K. | yes | yes | agree |
| percent sign | Growth was 38%. | yes | yes | agree |
| percent word | Growth was 38 percent. | yes | yes | agree |
| spelled-out integer | There were forty-two. | yes | yes | agree |
| spelled-out scale | Revenue was four hundred seventeen billion. | yes | yes | agree |
| spelled-out decimal | Growth was two point five percent. | yes | yes | agree |
| small digit count | There were 7 filings. | yes | yes | agree |
| year, wrong | For fiscal year 2022. | yes | yes | agree |
| year, FY form | For FY22. | yes | yes | agree |
| date, long | The period ended June 30, 2022. | yes | yes | agree |
| date, ISO | The period ended 2022-06-30. | yes | yes | agree |
| date, US numeric | The period ended 6/30/2022. | yes | yes | agree |
| quarter label | In the quarter Q2. | yes | yes | agree |
| form code lookalike | Filed a 391-K. | yes | yes | agree |
| round number, no hedge | Revenue was 420 billion. | yes | yes | agree |

## Correct restatements of the same fact, both implementations

Every row is true, so the right verdict is to accept.

| form | text | verifier accepts | auditor accepts | verdict |
|---|---|---|---|---|
| exact digits | Revenue was 416,161,000,000.0. | yes | yes | agree |
| magnitude word, exact | Revenue was $416.161 billion. | yes | yes | agree |
| rounded to the billion | Revenue was about 416 billion. | yes | yes | agree |
| rounded to a tenth of a billion | Revenue was 416.2 billion. | yes | yes | agree |
| rounded to ten billion | Revenue was roughly 420 billion. | yes | yes | agree |
| abbreviation B | Revenue was $416B. | yes | yes | agree |
| abbreviation bn | Revenue was 416 bn. | yes | yes | agree |
| abbreviation T | Revenue was $0.4T. | yes | yes | agree |
| in millions | Revenue was 416,161 million. | yes | yes | agree |
| spelled out | Revenue was four hundred sixteen billion. | yes | yes | agree |
| fiscal year, long | For fiscal year 2025. | yes | yes | agree |
| fiscal year, FY form | For FY25. | yes | yes | agree |
| form code | Per the 10-K for fiscal 2025. | yes | yes | agree |
| ordinal | The 3rd largest filer. | yes | yes | agree |
