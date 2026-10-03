# Independent number audit beside the verifier (dev runs only)

`evals/number_audit.py` (spec: `evals/NUMBER_AUDIT_SPEC.md`) against `ledgerql/verify.py`, on every
answered record of the committed dev pipeline runs. A shipped answer has passed the verifier, so
every disagreement is the auditor flagging something the verifier let through.

| run | answered | auditor flags | weak | derived |
|---|---|---|---|---|
| 30B rerun 47367323 | 55 | 0 | 0 | 0 |
| 30B partial 47314853 | 42 | 0 | 0 | 0 |
| 32B 47314855 | 44 | 0 | 0 | 0 |

Disagreements: 0 of 141 answered records.

## Planted invented values, both implementations

The true value is 416,161,000,000 (fiscal 2025, AAPL). Each text states something invented.

| form | text | verifier catches | auditor catches | verdict |
|---|---|---|---|---|
| digits | Revenue was 417,500,000,000.0. | **no** | yes | verifier blind spot |
| decimal | Revenue was 417500000000.5. | **no** | yes | verifier blind spot |
| magnitude word | Revenue was $417.5 billion. | **no** | yes | verifier blind spot |
| mis-scaled word | Revenue was 416.161 million. | yes | yes | agree |
| abbreviation B | Revenue was $417.5B. | yes | yes | agree |
| abbreviation bn | Revenue was 417.5 bn. | yes | yes | agree |
| abbreviation T | Revenue was 0.45T. | yes | yes | agree |
| abbreviation K | Revenue was 417500K. | yes | yes | agree |
| percent sign | Growth was 38%. | yes | yes | agree |
| percent word | Growth was 38 percent. | yes | yes | agree |
| spelled-out integer | There were forty-two. | **no** | yes | verifier blind spot |
| spelled-out scale | Revenue was four hundred seventeen billion. | **no** | yes | verifier blind spot |
| spelled-out decimal | Growth was two point five percent. | **no** | yes | verifier blind spot |
| small digit count | There were 7 filings. | yes | yes | agree |
| year, wrong | For fiscal year 2022. | yes | yes | agree |
| year, FY form | For FY22. | yes | yes | agree |
| date, long | The period ended June 30, 2022. | yes | yes | agree |
| date, ISO | The period ended 2022-06-30. | yes | yes | agree |
| date, US numeric | The period ended 6/30/2022. | yes | yes | agree |
| quarter label | In the quarter Q2. | yes | yes | agree |
| form code lookalike | Filed a 391-K. | **no** | yes | verifier blind spot |

## Correct restatements of the same fact, both implementations

Every row is true, so the right verdict is to accept.

| form | text | verifier accepts | auditor accepts | verdict |
|---|---|---|---|---|
| exact digits | Revenue was 416,161,000,000.0. | yes | yes | agree |
| magnitude word, exact | Revenue was $416.161 billion. | yes | yes | agree |
| rounded to the billion | Revenue was about 416 billion. | yes | yes | agree |
| rounded to a tenth of a billion | Revenue was 416.2 billion. | yes | yes | agree |
| rounded to ten billion | Revenue was roughly 420 billion. | yes | yes | agree |
| abbreviation B | Revenue was $416B. | **no** | yes | verifier too strict |
| abbreviation bn | Revenue was 416 bn. | **no** | yes | verifier too strict |
| abbreviation T | Revenue was $0.4T. | **no** | yes | verifier too strict |
| in millions | Revenue was 416,161 million. | yes | yes | agree |
| spelled out | Revenue was four hundred sixteen billion. | yes | yes | agree |
| fiscal year, long | For fiscal year 2025. | yes | yes | agree |
| fiscal year, FY form | For FY25. | **no** | yes | verifier too strict |
| form code | Per the 10-K for fiscal 2025. | yes | yes | agree |
| ordinal | The 3rd largest filer. | **no** | yes | verifier too strict |
