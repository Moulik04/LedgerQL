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

## v2 relaxed

Best single run on pass@N (hindsight): single run|xiyan_32b/omnisql.

| pool | pass@N | vs mean single [95% CI] | vs best single [95% CI] | pass@1 (vote) | vs mean single [95% CI] | vs best single [95% CI] |
|---|---|---|---|---|---|---|
| single run (5 samples, one model, one prompt) | 42.6 (40.0-46.0) | +0.0 [+0.0, +0.0] | -3.4 [-5.9, -0.7] | 39.7 | +0.0 [+0.0, +0.0] | -1.3 [-5.1, +3.0] |
| 5 of the 15 from three models, one prompt | 47.0 (46.2-48.6) | +4.5 [+2.9, +6.0] | +1.0 [-0.9, +3.7] | 42.0 | +2.4 [+1.3, +3.6] | +1.0 [-3.0, +5.4] |
| 5 of the 15 from three prompts, one model | 46.9 (44.8-48.2) | +4.4 [+2.8, +6.0] | +0.9 [-1.2, +3.6] | 42.0 | +2.3 [+1.4, +3.3] | +1.0 [-2.7, +5.1] |
| 5 of all 45 (three models, three prompts) | 48.1 | +5.5 [+3.5, +7.6] | +2.1 [-0.4, +5.0] | 42.7 | +3.0 [+1.8, +4.3] | +1.7 [-2.2, +6.0] |
| one from each of 5 distinct runs | 48.5 | +5.9 [+3.7, +8.2] | +2.5 [-0.2, +5.5] | 42.9 | +3.2 [+1.8, +4.8] | +1.9 [-2.1, +6.2] |
