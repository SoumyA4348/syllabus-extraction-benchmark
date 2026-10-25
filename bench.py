"""
Benchmark: four ways to extract deadlines from a syllabus PDF.

  A  pdf_to_llm   send the binary PDF to Gemini
  B  text_to_llm  extract text with pypdf, send the text to Gemini (what GRYPH OS ships)
  C  regex_only   pypdf text + regex rules, no LLM
  D  hybrid       regex first; call Gemini (B) only if regex finds fewer than MIN_EVENTS

Reuses GRYPH OS's own extraction code so the numbers describe the real system.

  python bench.py                                # all PDFs in syllabi/, all strategies, 1 repeat
  python bench.py --repeats 3 --workers 6        # parallel LLM calls, 3 repeats for variance
  python bench.py --strategies C                 # no API key needed
Needs GEMINI_API_KEY in the environment (or .env) for A, B, D.
Every prediction is saved to runs/<run_id>/preds/ so rescore.py can re-score without new API calls.
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
GRYPH_BACKEND = HERE / "vendor" / "gryph_os"  # GRYPH OS extraction code, unchanged (see vendor/gryph_os/README.md)
sys.path.insert(0, str(GRYPH_BACKEND))

import gemini_service as gs  # noqa: E402  (GRYPH OS code, imported unchanged)

try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
except ImportError:
    pass

MIN_EVENTS = 3  # hybrid: below this, regex output is treated as a failure and the LLM is called
MODEL = os.environ.get("GEMINI_MODEL", gs.GEMINI_MODEL)
API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
RETRIES = 4  # transient 503/429 errors: retry with backoff, and record how many retries were needed

_CLIENT = None
_CLIENT_LOCK = threading.Lock()


def _client():
    # Exactly one client for the whole process: the SDK closes a client once it is garbage-collected,
    # so a second client created by a racing thread would be closed mid-request.
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from google import genai
            _CLIENT = genai.Client(api_key=API_KEY)
    return _CLIENT


def _gemini(contents):
    """One Gemini call with retry. Returns (parsed_json, input_tokens, output_tokens, seconds, retries)."""
    from google.genai import types
    for attempt in range(RETRIES + 1):
        start = time.perf_counter()
        try:
            resp = _client().models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=gs._SYSTEM_EXTRACT),
            )
        except Exception as e:
            transient = any(code in str(e) for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if transient and attempt < RETRIES:
                time.sleep(10 * 2 ** attempt)
                continue
            raise
        meta = resp.usage_metadata
        return (gs._parse_json(resp.text), meta.prompt_token_count, meta.candidates_token_count,
                time.perf_counter() - start, attempt)


_TYPE_RULES = [("final", "final"), ("midterm", "midterm"), ("exam", "midterm"), ("test", "midterm"),
               ("quiz", "quiz"), ("project", "project"), ("presentation", "project"), ("reading", "reading")]


def _dateparser_events(text):
    """Strategy E: established date library (dateparser.search_dates) on lines that mention an assessment.

    Mirrors GRYPH's regex loop: every line is scanned for dates, and an assessment keyword on the line only
    sets the type ("other" if none), so the only difference from strategy C is how dates are found.
    Requires both day and month; a missing year defaults to the current year, as GRYPH's regex does.
    """
    from dateparser.search import search_dates
    events, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        found = search_dates(line, languages=["en"], settings={"REQUIRE_PARTS": ["day", "month"]}) or []
        low = line.lower()
        ev_type = (next((t for k, t in _TYPE_RULES if k in low), "assignment")
                   if gs._EVENT_KEYWORDS.search(line) else "other")
        for _, dt in found:
            iso = dt.strftime("%Y-%m-%d")
            if (iso, ev_type) not in seen:
                seen.add((iso, ev_type))
                events.append({"title": line[:80], "type": ev_type, "dueDateISO": iso, "notes": None})
    return events


def run_strategy(name, pdf_path):
    """Returns dict(events, in_tok, out_tok, seconds, llm_called, retries)."""
    text = gs._extract_pdf_text(str(pdf_path))
    t0 = time.perf_counter()

    if name in ("C", "D"):
        out = gs._regex_fallback(text, pdf_path.name)
        if name == "C" or len(out["events"]) >= MIN_EVENTS:
            return dict(events=out["events"], in_tok=0, out_tok=0, seconds=time.perf_counter() - t0,
                        llm_called=False, retries=0)

    if name == "E":
        return dict(events=_dateparser_events(text), in_tok=0, out_tok=0, seconds=time.perf_counter() - t0,
                    llm_called=False, retries=0)

    from google.genai import types  # only the LLM strategies need the SDK
    if name == "A":
        part = types.Part.from_bytes(data=pdf_path.read_bytes(), mime_type="application/pdf")
        contents = [types.Content(role="user", parts=[part])]
    else:  # B, or D falling back
        prompt = f"Syllabus text:\n\n{text[:30000]}"  # same cap as GRYPH OS
        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    data, i, o, s, retries = _gemini(contents)
    return dict(events=data.get("events", []), in_tok=i, out_tok=o, seconds=time.perf_counter() - t0,
                llm_called=True, retries=retries)


def score(pred_events, gold):
    """Precision/recall/F1 on due dates, plus the share of gold events whose type is also right."""
    pred = {e["dueDateISO"]: e.get("type") for e in pred_events if e.get("dueDateISO")}
    gold_map = {g["dueDateISO"]: g.get("type") for g in gold}
    if not gold_map:  # syllabus with no dated deadlines: perfect only if nothing is predicted
        return (1.0, 1.0, 1.0, 1.0) if not pred else (0.0, 1.0, 0.0, 1.0)
    tp = len(pred.keys() & gold_map.keys())
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold_map) if gold_map else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    typed = sum(1 for d in pred.keys() & gold_map.keys() if pred[d] == gold_map[d])
    return p, r, f1, (typed / len(gold_map) if gold_map else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default="ABCD")
    ap.add_argument("--syllabi", default=str(HERE / "syllabi"))
    ap.add_argument("--labels", default=str(HERE / "labels"))
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume", help="run_id to continue: only jobs without a saved prediction are run")
    args = ap.parse_args()

    strategies = list(args.strategies.upper())
    if any(s in "ABD" for s in strategies) and not API_KEY:
        sys.exit("GEMINI_API_KEY is not set. Run with --strategies C, or add the key to benchmark/.env")
    pdfs = sorted(Path(args.syllabi).glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDFs in {args.syllabi}")

    if args.resume:
        run_id = args.resume
        run_dir = HERE / "runs" / run_id
        old = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        if old["model"] != MODEL or old["pypdf"] != __import__("pypdf").__version__:
            sys.exit(f"Cannot resume {run_id}: it used {old['model']} / pypdf {old['pypdf']}")
    else:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = HERE / "runs" / run_id
        (run_dir / "preds").mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({
            "run_id": run_id, "model": MODEL, "min_events": MIN_EVENTS, "repeats": args.repeats,
            "strategies": strategies, "files": [p.name for p in pdfs],
            "pypdf": __import__("pypdf").__version__,
        }, indent=1), encoding="utf-8")

    jobs = [(pdf, s, rep) for rep in range(1, args.repeats + 1) for pdf in pdfs for s in strategies
            if not (run_dir / "preds" / f"{pdf.stem}__{s}__r{rep}.json").exists()]
    print(f"{len(jobs)} jobs to run in {run_id}", flush=True)
    rows = []

    def do(job):
        pdf, s, rep = job
        try:
            return job, run_strategy(s, pdf), None
        except Exception as e:  # failures are data too
            return job, None, str(e)[:160]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed(pool.submit(do, j) for j in jobs):
            (pdf, s, rep), r, err = fut.result()
            row = dict(run_id=run_id, model=MODEL, file=pdf.name, strategy=s, repeat=rep, error=err or "")
            if r:
                (run_dir / "preds" / f"{pdf.stem}__{s}__r{rep}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
                row.update(events=len(r["events"]), in_tokens=r["in_tok"], out_tokens=r["out_tok"],
                           seconds=round(r["seconds"], 2), llm_called=r["llm_called"], retries=r["retries"])
                label_file = Path(args.labels) / (pdf.stem + ".json")
                if label_file.exists():
                    p, rec, f1, typed = score(r["events"], json.loads(label_file.read_text(encoding="utf-8")))
                    row.update(precision=round(p, 3), recall=round(rec, 3), f1=round(f1, 3), type_acc=round(typed, 3))
            rows.append(row)
            print(f"[{len(rows)}/{len(jobs)}] {pdf.stem[:26]:26} {s} r{rep}  "
                  + (f"ERROR {err[:60]}" if err else f"in={row['in_tokens']:5} f1={row.get('f1', 'n/a')}"), flush=True)

    fields = ["run_id", "model", "file", "strategy", "repeat", "events", "in_tokens", "out_tokens", "seconds",
              "llm_called", "retries", "precision", "recall", "f1", "type_acc", "error"]
    csv_name = f"results_{datetime.now():%H%M%S}.csv" if args.resume else "results.csv"
    with open(run_dir / csv_name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["file"], r["strategy"], r["repeat"])))
    print(f"\nWrote {run_dir / 'results.csv'}  — summarise with: python rescore.py {run_id}")


if __name__ == "__main__":
    main()
