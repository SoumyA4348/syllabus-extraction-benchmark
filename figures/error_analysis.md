# Error analysis — runs 20261025-060628
Model `gemini-3.1-flash-lite`

## 1. Hallucination on the no-deadline syllabus (carleton_comp2402a_f26, gold = [])

- A: predicted dates per repeat = [3, 3, 3]
- B: predicted dates per repeat = [3, 3, 3]
- C: predicted dates per repeat = [0, 0, 0]
- D: predicted dates per repeat = [3, 3, 3]
- E: predicted dates per repeat = [2, 2, 2]

## 2. Grid-layout syllabi (dates only in a calendar image) — recall

- carleton_comp1405a_w25: A 0.78 · B 0.52 · C 0.00 · D 0.00 · E 0.00
- carleton_comp1405b_f25: A 0.78 · B 0.11 · C 0.00 · D 0.00 · E 0.00

## 3. Wrong-year errors (predicted MM-DD is in the gold set, but the year differs)

- A: 9 of 415 date matches had the wrong year (2%)
- B: 9 of 385 date matches had the wrong year (2%)
- C: 66 of 114 date matches had the wrong year (58%)
- D: 63 of 343 date matches had the wrong year (18%)
- E: 261 of 306 date matches had the wrong year (85%)

## 4. Hybrid routing (D): F1 when regex was trusted vs when the LLM was called

- regex trusted (no LLM): n=33, F1 full 0.179, month-day 0.401
- LLM called: n=15, F1 full 0.789, month-day 0.789

## 5. Run-to-run variation in number of events (LLM strategies)

- A: mean SD of event count across repeats = 0.24
- B: mean SD of event count across repeats = 0.54
- D: mean SD of event count across repeats = 0.07

## 6. Significance: paired differences in per-syllabus F1 (full date)

Paired sign-flip permutation test (two-sided, 20,000 permutations) and bootstrap 95% CI of the mean difference (10,000 resamples), seed 0. Unit = syllabus (mean over repeats).

| Comparison | n | Mean diff | 95% CI | p |
|---|---|---|---|---|
| A − B | 16 | +0.051 | [+0.002, +0.137] | 0.1258 |
| B − D | 16 | +0.287 | [+0.141, +0.462] | 0.0018 |
| D − C | 16 | +0.184 | [-0.064, +0.432] | 0.3765 |
| C − E | 16 | +0.115 | [+0.018, +0.257] | 0.1255 |
| A − D | 16 | +0.339 | [+0.170, +0.521] | 0.0008 |