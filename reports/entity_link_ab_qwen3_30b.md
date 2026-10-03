# Entity linking A/B: qwen3_30b, `omnisql` prompt

50 ANSWER cases, N=5, temperature 0.7, seeds 42-46, one server session, both conditions; the linker adds a hint to 29 of them (elsewhere the prompts are identical). Scored against the frozen gold. Linked minus baseline.

| gold | pass@1 base -> linked | cases gained / lost | pass@N base -> linked | cases gained / lost | correct candidates base -> linked (of 5 per case) | gained / lost |
|---|---|---|---|---|---|---|
| v1 | 27 -> 37 of 50 | +11 / -1 | 33 -> 39 | +6 / -0 | 136 -> 181 of 250 | +48 / -3 |
| v2 strict | 31 -> 46 of 50 | +15 / -0 | 42 -> 47 | +5 / -0 | 163 -> 224 of 250 | +63 / -2 |
| v3 strict | 32 -> 47 of 50 | +15 / -0 | 44 -> 48 | +5 / -1 | 168 -> 229 of 250 | +64 / -3 |
| v3 relaxed | 33 -> 48 of 50 | +15 / -0 | 44 -> 49 | +5 / -0 | 169 -> 233 of 250 | +66 / -2 |

Candidates returning no rows (the name-literal failure): 57 -> 6 of 250.

v3 strict pass@1 gained: ['C01', 'C05', 'C06', 'J03', 'J05', 'L05', 'L12', 'R01', 'R02', 'R03', 'R05', 'S09', 'S10', 'T04', 'U01']; lost: [].
v3 strict pass@N gained: ['J03', 'L05', 'L12', 'R03', 'S10']; lost: ['R06'].
