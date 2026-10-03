# Entity linking: the offline upper bound

Every candidate's company-name predicates are rewritten to the correct ticker (the case's companies are read from its gold SQL, so the link is always right), re-executed and re-scored. This is what *perfect* linking could gain, **at least** (the name matcher cannot connect `Exxon Mobil Corp.` to the stored `ExxonMobil`, so some candidates are not rewritten; DECISIONS 2026-10-02); it is not an estimate of what a linker will. `evals/entity_upper_bound.py`.

Candidates: 2250; changed by the rewrite: 590.

## pass@1 -> pass@N, before | after linking

| model | prompt | v1 before | v1 after | v2 strict before | v2 strict after | v3 strict before | v3 strict after | v3 relaxed before | v3 relaxed after |
|---|---|---|---|---|---|---|---|---|---|
| Qwen2.5-32B AWQ | current | 27 -> 30 | 29 -> 32 | 30 -> 35 | 34 -> 38 | 31 -> 37 | 35 -> 40 | 39 -> 42 | 43 -> 45 |
| Qwen2.5-32B AWQ | omnisql | 31 -> 35 | 37 -> 38 | 35 -> 39 | 42 -> 43 | 35 -> 40 | 44 -> 45 | 38 -> 43 | 47 -> 48 |
| Qwen2.5-32B AWQ | xiyan | 30 -> 35 | 35 -> 39 | 30 -> 36 | 36 -> 41 | 30 -> 36 | 38 -> 43 | 38 -> 41 | 47 -> 48 |
| Qwen3-30B | current | 31 -> 33 | 32 -> 34 | 32 -> 34 | 33 -> 35 | 32 -> 34 | 33 -> 35 | 43 -> 44 | 44 -> 45 |
| Qwen3-30B | omnisql | 26 -> 34 | 35 -> 38 | 33 -> 42 | 44 -> 47 | 34 -> 44 | 46 -> 49 | 34 -> 44 | 46 -> 49 |
| Qwen3-30B | xiyan | 35 -> 35 | 38 -> 38 | 39 -> 40 | 42 -> 43 | 40 -> 41 | 43 -> 44 | 44 -> 44 | 48 -> 48 |
| XiYanSQL-32B | current | 34 -> 35 | 37 -> 38 | 40 -> 40 | 43 -> 43 | 41 -> 41 | 44 -> 44 | 46 -> 46 | 49 -> 49 |
| XiYanSQL-32B | omnisql | 31 -> 36 | 36 -> 38 | 40 -> 46 | 46 -> 48 | 40 -> 48 | 48 -> 50 | 41 -> 48 | 49 -> 50 |
| XiYanSQL-32B | xiyan | 31 -> 34 | 38 -> 39 | 35 -> 37 | 44 -> 44 | 36 -> 38 | 46 -> 46 | 39 -> 41 | 49 -> 49 |

## Union over all nine runs

- v1: 42 -> 43 of 50; newly solved ['L12']; never solved after: ['A09', 'J04', 'J05', 'R02', 'R04', 'R05', 'T02']
- v2 strict: 49 -> 50 of 50; newly solved ['L12']; never solved after: []
- v3 strict: 49 -> 50 of 50; newly solved ['L12']; never solved after: []
- v3 relaxed: 49 -> 50 of 50; newly solved ['L12']; never solved after: []

## Candidates that flip, by case (v3 strict)

| case | wrong -> right | right -> wrong |
|---|---|---|
| C01 | 4 | 0 |
| C02 | 1 | 0 |
| C05 | 6 | 0 |
| C06 | 7 | 0 |
| G01 | 2 | 0 |
| J01 | 1 | 0 |
| J05 | 4 | 0 |
| J07 | 17 | 0 |
| L01 | 4 | 0 |
| L02 | 1 | 0 |
| L05 | 17 | 0 |
| L06 | 19 | 0 |
| L07 | 15 | 0 |
| L08 | 6 | 0 |
| L10 | 6 | 0 |
| L11 | 14 | 0 |
| L12 | 45 | 0 |
| R01 | 5 | 0 |
| R02 | 18 | 0 |
| R03 | 3 | 0 |
| R05 | 13 | 0 |
| R06 | 7 | 0 |
| S09 | 2 | 0 |
| S10 | 5 | 0 |
| T01 | 2 | 0 |
| T03 | 17 | 0 |
| T04 | 17 | 0 |
| U01 | 3 | 0 |

Total: 261 candidates gained, 0 lost, of 2250.
