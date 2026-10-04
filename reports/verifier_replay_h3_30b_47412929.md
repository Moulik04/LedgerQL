# Two versions of the verifier, replayed on the same drafts (eval_bridges2_qwen3_30b_pipeline_47412929.jsonl)

`verifier at 590188e` and `verifier at 458478a` are two versions of `ledgerql/verify.py`, replayed on the drafts this run
stored. The drafts are identical on both sides (the verifier runs after the answer is written),
so every difference below is the verifier's. The auditor is `evals/number_audit.py`.

| | verifier at 590188e | verifier at 458478a |
|---|---|---|
| drafted, with the draft's text stored | 63 | 63 |
| **draft rate** (blocked / drafted) | 4 of 63 (6.3%) | 3 of 63 (4.8%) |
| blocked, and the auditor also finds an invented number | 3 | 3 |
| **false abstains** (blocked, but the auditor grounds every claim) | 1 | 0 |
| blocked, nothing ungrounded, but a claim the auditor cannot resolve (counted as neither) | 0 | 0 |
| shipped | 59 | 60 |
| **shipped, and the auditor flags an invented number** | 0 | 0 |
| shipped with an unresolved claim (reported, not counted) | 0 | 0 |
| shipped with a weak claim (reported, not counted) | 0 | 0 |
| shipped with a derived claim | 0 | 0 |

## Drafts whose verdict changed: 1

### L11: blocked -> shipped

- draft: The data shows a single filing with accession number 0000037996-26-000015. There are no other values provided in the table to describe additional information about this filing.
- verifier at 590188e: answer states unsupported number(s): [37996.0, 26.0, 15.0]
- verifier at 458478a: accepted
- auditor: ungrounded []; unresolved []; weak []; derived []

## Drafts blocked by both: 3

### L08: invented

- draft: The table shows JPMorgan Chase's financial data with total assets of 3,460,750 million USD and total liabilities of 2,981,100 million USD. The data represents the company's balance sheet information as of a specific period.
- verifier at 458478a: answer states unsupported number(s): [3460750000000.0, 2981100000000.0]
- auditor: ungrounded [('number', '3,460,750 million'), ('number', '2,981,100 million')]; unresolved []; weak []; derived []

### L12: invented

- draft: The data shows information for the stock ticker "KO" which represents The Coca-Cola Company. The table contains financial metrics including operating cash flow of $10,894 million, capital expenditures of $2,563 million, and free cash flow of $8,331 million. All values are presented in millions of US dollars.
- verifier at 458478a: answer states unsupported number(s): [10894000000.0, 2563000000.0, 8331000000.0]
- auditor: ungrounded [('number', '$10,894 million'), ('number', '$2,563 million'), ('number', '$8,331 million')]; unresolved []; weak []; derived []

### T07: invented

- draft: The table lists 29 company tickers and their corresponding names, with Federal Realty Investment Trust appearing twice. All entries are presented as stock ticker symbols paired with full company names.
- verifier at 458478a: answer states unsupported number(s): [29.0]
- auditor: ungrounded [('number', '29')]; unresolved []; weak []; derived []

## Shipped with an unresolved claim: 0
