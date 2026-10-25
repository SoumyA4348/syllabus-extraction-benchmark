# Vendored: GRYPH OS extraction code

`gemini_service.py` is copied **unchanged** from [GRYPH OS](https://github.com/SoumyA4348/GryphOS), `backend/gemini_service.py`, commit `8a49b735a3293e2586ce4aa6d5b7f1eb052deca1` (2026-09-20).

MIT License, Copyright (c) 2026 Soumya Patel, Manas Verma.

The benchmark imports `_extract_pdf_text`, `_regex_fallback`, `_parse_json`, `_EVENT_KEYWORDS` and `_SYSTEM_EXTRACT` so strategies B and C measure the real system. Its default model (`gemini-2.0-flash`) has been retired; the benchmark sets the model via `GEMINI_MODEL`.
