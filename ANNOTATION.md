# Annotation guidelines

Gold labels in `labels/<id>.json` are lists of `{"dueDateISO": "YYYY-MM-DD", "type": "..."}`.
Types: `assignment`, `quiz`, `midterm`, `final`, `project`, `reading`, `other`.

**Process.** Labels were pre-annotated by an LLM that is not under test (Anthropic Claude), then checked line by line against each PDF and corrected by the author. Single annotator.

## Rules
1. **Graded items with a specific date only.** Excluded: readings, lectures, review classes, office hours, withdrawal/refund dates, "no late work after X" cut-offs, items marked TBD or "scheduled by the registrar", and implicit recurring deadlines ("due every Sunday").
2. **Windows use the close date** (e.g. "opens Feb 17, closes Feb 23" → Feb 23).
3. **Year inferred from the term** stated in the document.
4. **Optional work excluded** (e.g. "optional HW0", extra-credit discussions).
5. **Types:** non-final exams and tests → `midterm`; the exam in finals week or named "final" → `final`.

## Document-specific decisions
- `utexas_cs303e_s25`: Project 3 "Wednesday, 4/21" — 2025-04-21 is a Monday; labelled as written.
- `uwo_cs1033_s26`: two lab sections with different quiz dates — both sections' dates included. Peer-marking end and feedback dates labelled `other`.
- `carleton_comp1405a_w25`, `carleton_comp1405b_f25`: assignment dates appear only in a calendar grid ("← Due Friday"); read from the page image. pypdf text does not contain them.
- `msutexas_schedule_f25`: headed "Spring 2025" but all dates are Aug–Dec → labelled Fall 2025. "9/30/1" typo → Sep 30. Conflicting 11/25 vs 11/26 → both included.
- `carleton_comp2402a_f26`: no fixed dates (tests "TBD between Oct 16–18", "Nov 27–29"; final "TBD Dec 12–23") → empty label. Any prediction is a false positive.
- `richland_m121_f24`, `richland_m122_s25`: only the final exam is dated. Note: LLM strategies also extract withdrawal/refund dates, which rule 1 excludes — scores are sensitive to this definition.

## Scoring
- Precision / recall / F1 on the set of due dates (one event per date; same-day items count once).
- Month-day F1 ignores the year, because both the regex and GRYPH OS's prompt ("infer the most likely upcoming year") guess years, which penalises past syllabi.
- Empty gold: F1 = 1 if nothing is predicted, else 0.
