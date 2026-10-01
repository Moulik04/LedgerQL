# Fixed-budget pool experiment

Budget: 5 candidates per case, 50 ANSWER cases. Expected cases solved (of 50). `vs mean single run` is the pooled figure minus the mean of the nine single runs, with a 95% bootstrap CI over cases; `vs best` uses the single run that scored best on pass@N in hindsight, so it is a conservative comparison. Method: `evals/pool_experiment.py`.

## v1

Best single run on pass@N (hindsight): single run|xiyan_32b/omnisql.

| pool | pass@N | vs mean single [95% CI] | vs best single [95% CI] | pass@1 (vote) | vs mean single [95% CI] | vs best single [95% CI] |
|---|---|---|---|---|---|---|
| single run (5 samples, one model, one prompt) | 34.1 (30.0-36.0) | +0.0 [+0.0, +0.0] | -1.9 [-4.8, +1.2] | 30.7 | +0.0 [+0.0, +0.0] | -0.3 [-4.4, +4.0] |
| 5 of the 15 from three models, one prompt | 37.9 (36.9-38.5) | +3.8 [+2.5, +5.4] | +1.9 [-0.9, +5.2] | 33.6 | +2.9 [+1.7, +4.2] | +2.6 [-1.9, +7.2] |
| 5 of the 15 from three prompts, one model | 38.8 (37.5-39.6) | +4.7 [+3.1, +6.4] | +2.8 [-0.2, +6.4] | 33.7 | +3.0 [+1.9, +4.2] | +2.7 [-1.5, +7.1] |
| 5 of all 45 (three models, three prompts) | 40.1 | +5.9 [+3.9, +8.1] | +4.1 [+0.8, +8.0] | 34.7 | +4.0 [+2.6, +5.6] | +3.7 [-0.7, +8.4] |
| one from each of 5 distinct runs | 40.6 | +6.5 [+4.2, +8.9] | +4.6 [+1.3, +8.7] | 35.3 | +4.7 [+3.1, +6.5] | +4.3 [-0.2, +9.2] |

## v2 strict

Best single run on pass@N (hindsight): single run|xiyan_32b/omnisql.

| pool | pass@N | vs mean single [95% CI] | vs best single [95% CI] | pass@1 (vote) | vs mean single [95% CI] | vs best single [95% CI] |
|---|---|---|---|---|---|---|
| single run (5 samples, one model, one prompt) | 38.8 (34.0-46.0) | +0.0 [+0.0, +0.0] | -7.2 [-10.9, -3.7] | 34.9 | +0.0 [+0.0, +0.0] | -5.1 [-9.8, -0.2] |
| 5 of the 15 from three models, one prompt | 44.4 (43.4-45.8) | +5.7 [+4.0, +7.5] | -1.6 [-4.9, +1.8] | 38.0 | +3.1 [+2.0, +4.3] | -2.0 [-6.7, +2.9] |
| 5 of the 15 from three prompts, one model | 44.3 (40.2-46.5) | +5.5 [+3.9, +7.2] | -1.7 [-4.7, +1.3] | 37.6 | +2.7 [+1.8, +3.6] | -2.4 [-7.2, +2.5] |
| 5 of all 45 (three models, three prompts) | 46.1 | +7.3 [+5.1, +9.6] | +0.1 [-3.0, +3.3] | 39.1 | +4.2 [+3.0, +5.4] | -0.9 [-5.6, +3.9] |
| one from each of 5 distinct runs | 46.8 | +8.0 [+5.5, +10.6] | +0.8 [-2.3, +4.1] | 39.7 | +4.8 [+3.5, +6.3] | -0.3 [-5.0, +4.7] |

## v3 strict

Best single run on pass@N (hindsight): single run|xiyan_32b/omnisql.

| pool | pass@N | vs mean single [95% CI] | vs best single [95% CI] | pass@1 (vote) | vs mean single [95% CI] | vs best single [95% CI] |
|---|---|---|---|---|---|---|
| single run (5 samples, one model, one prompt) | 39.9 (34.0-48.0) | +0.0 [+0.0, +0.0] | -8.1 [-11.6, -4.6] | 35.4 | +0.0 [+0.0, +0.0] | -4.6 [-9.3, +0.6] |
| 5 of the 15 from three models, one prompt | 45.4 (44.2-47.6) | +5.5 [+3.9, +7.2] | -2.6 [-5.7, +0.3] | 38.7 | +3.2 [+2.1, +4.4] | -1.3 [-6.2, +3.9] |
| 5 of the 15 from three prompts, one model | 45.4 (41.5-47.6) | +5.5 [+3.8, +7.3] | -2.6 [-5.4, +0.3] | 38.3 | +2.8 [+1.9, +3.8] | -1.7 [-6.6, +3.5] |
| 5 of all 45 (three models, three prompts) | 46.8 | +7.0 [+4.9, +9.1] | -1.2 [-3.8, +1.7] | 39.8 | +4.4 [+3.2, +5.6] | -0.2 [-5.0, +5.1] |
| one from each of 5 distinct runs | 47.4 | +7.5 [+5.2, +9.9] | -0.6 [-3.1, +2.2] | 40.5 | +5.1 [+3.7, +6.6] | +0.5 [-4.3, +5.8] |

## v3 relaxed

Best single run on pass@N (hindsight): single run|xiyan_32b/omnisql.

| pool | pass@N | vs mean single [95% CI] | vs best single [95% CI] | pass@1 (vote) | vs mean single [95% CI] | vs best single [95% CI] |
|---|---|---|---|---|---|---|
| single run (5 samples, one model, one prompt) | 43.7 (41.0-48.0) | +0.0 [+0.0, +0.0] | -4.3 [-6.7, -1.7] | 40.2 | +0.0 [+0.0, +0.0] | -0.8 [-4.8, +3.8] |
| 5 of the 15 from three models, one prompt | 47.9 (47.1-48.6) | +4.3 [+2.9, +5.8] | -0.1 [-1.6, +2.2] | 42.7 | +2.5 [+1.4, +3.7] | +1.7 [-2.5, +6.4] |
| 5 of the 15 from three prompts, one model | 47.7 (46.1-48.7) | +4.1 [+2.6, +5.5] | -0.3 [-2.0, +2.2] | 42.7 | +2.5 [+1.5, +3.5] | +1.7 [-2.4, +6.3] |
| 5 of all 45 (three models, three prompts) | 48.6 | +4.9 [+3.3, +6.6] | +0.6 [-0.7, +2.8] | 43.5 | +3.2 [+2.0, +4.6] | +2.5 [-1.7, +7.1] |
| one from each of 5 distinct runs | 48.8 | +5.1 [+3.4, +6.9] | +0.8 [-0.4, +2.9] | 43.7 | +3.5 [+2.0, +5.0] | +2.7 [-1.5, +7.3] |
