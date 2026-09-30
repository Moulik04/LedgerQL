# Entity linking on the local 7B (qwen2.5-coder:7b, `current` prompt)

29 cases where the linker adds a hint (elsewhere the prompts are identical); N=5, temperature 0.7, seeds 42-46 in both conditions; `evals/entity_link_eval.py`. Linked minus baseline.

| gold | pass@1 base -> linked | cases gained / lost | pass@N base -> linked | cases gained / lost | correct candidates base -> linked (of 5 per case) | gained / lost |
|---|---|---|---|---|---|---|
| v1 | 16 -> 19 of 29 | +3 / -0 | 18 -> 20 | +2 / -0 | 69 -> 86 of 145 | +22 / -5 |
| v2 strict | 19 -> 23 of 29 | +4 / -0 | 20 -> 23 | +3 / -0 | 80 -> 100 of 145 | +29 / -9 |
| v2 relaxed | 20 -> 24 of 29 | +4 / -0 | 21 -> 24 | +3 / -0 | 93 -> 109 of 145 | +23 / -7 |

Candidates returning no rows (the name-literal failure): 5 -> 1 of 145.

v2 strict pass@1 gained: ['G01', 'J05', 'L11', 'L12']; lost: [].
v2 strict pass@N gained: ['J05', 'L11', 'L12']; lost: [].
