# Entity linking A/B: xiyan_32b, `omnisql` prompt

50 ANSWER cases, N=5, temperature 0.7, seeds 42-46, one server session, both conditions; the linker adds a hint to 29 of them (elsewhere the prompts are identical). Scored against the frozen gold. Linked minus baseline.

| gold | pass@1 base -> linked | cases gained / lost | pass@N base -> linked | cases gained / lost | correct candidates base -> linked (of 5 per case) | gained / lost |
|---|---|---|---|---|---|---|
| v1 | 33 -> 38 of 50 | +6 / -1 | 37 -> 40 | +3 / -0 | 158 -> 184 of 250 | +30 / -4 |
| v2 strict | 43 -> 45 of 50 | +4 / -2 | 47 -> 50 | +3 / -0 | 196 -> 220 of 250 | +33 / -9 |
| v3 strict | 44 -> 47 of 50 | +5 / -2 | 49 -> 50 | +1 / -0 | 199 -> 227 of 250 | +37 / -9 |
| v3 relaxed | 44 -> 48 of 50 | +5 / -1 | 49 -> 50 | +1 / -0 | 205 -> 233 of 250 | +35 / -7 |

Candidates returning no rows (the name-literal failure): 29 -> 5 of 250.

v3 strict pass@1 gained: ['L05', 'L07', 'L12', 'R05', 'T03']; lost: ['J03', 'R04'].
v3 strict pass@N gained: ['L12']; lost: [].
