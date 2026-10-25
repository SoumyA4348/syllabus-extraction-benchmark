# Router sweep (offline) — model `gemini-3.1-flash-lite`, 16 syllabi × repeats

| Router | F1 full | F1 month-day | Mean tokens | LLM-call rate |
|---|---|---|---|---|
| k = 1 | 0.246 | 0.423 | 1151 | 19% |
| k = 2 | 0.307 | 0.484 | 1284 | 25% |
| k = 3 (GRYPH-style D) | 0.369 | 0.522 | 1514 | 31% |
| k = 5 | 0.441 | 0.574 | 2407 | 50% |
| k = 8 | 0.572 | 0.606 | 2877 | 75% |
| k = 12 | 0.581 | 0.611 | 3146 | 81% |
| k = 20 | 0.594 | 0.645 | 3474 | 94% |
| never trust regex (= B) | 0.657 | 0.678 | 3593 | 100% |
| k = 3 + single-year check | 0.441 | 0.531 | 1963 | 44% |