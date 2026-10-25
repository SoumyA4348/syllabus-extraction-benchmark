"""Re-score saved predictions against labels/ without calling Gemini again.

  python rescore.py <run_id>                 # e.g. 20261025-213000 (folder under runs/)
  python rescore.py <run_id> <run_id> ...    # merge runs (same model), e.g. main run + new-files run
  python rescore.py                          # latest run
Writes summary.md into the first run's folder
"""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

from bench import score

HERE = Path(__file__).parent


def load(run_ids):
    """Returns (run_dirs, metas, cell) where cell[(strategy, stem)] = list of per-repeat dicts."""
    runs = sorted(p for p in (HERE / "runs").iterdir() if p.is_dir())
    run_dirs = [HERE / "runs" / r for r in run_ids] or [runs[-1]]
    metas = [json.loads((d / "meta.json").read_text(encoding="utf-8")) for d in run_dirs]
    if len({m["model"] for m in metas}) > 1 or len({m["pypdf"] for m in metas}) > 1:
        sys.exit("Refusing to merge runs with different model or pypdf versions: "
                 + str([(m["run_id"], m["model"], m["pypdf"]) for m in metas]))

    latest = {}  # later runs override earlier ones for the same file/strategy/repeat
    for d in run_dirs:
        for f in (d / "preds").glob("*.json"):
            latest[f.name] = f
    cell = defaultdict(list)
    md = lambda evs: [{**e, "dueDateISO": e["dueDateISO"][5:]} for e in evs if e.get("dueDateISO")]
    for f in sorted(latest.values(), key=lambda p: p.name):
        stem, strategy, rep = f.stem.rsplit("__", 2)
        label = HERE / "labels" / f"{stem}.json"
        if not label.exists():
            continue
        pred = json.loads(f.read_text(encoding="utf-8"))
        gold = json.loads(label.read_text(encoding="utf-8"))
        p, r, f1, typed = score(pred["events"], gold)
        # Year-agnostic match (MM-DD): GRYPH's prompt and regex both guess the year, which penalises past syllabi
        _, _, f1_md, _ = score(md(pred["events"]), md(gold))
        cell[(strategy, stem)].append(dict(p=p, r=r, f1=f1, f1_md=f1_md, typed=typed, i=pred["in_tok"],
                                           o=pred["out_tok"], s=pred["seconds"], llm=pred["llm_called"],
                                           events=pred["events"], gold=gold))
    return run_dirs, metas, cell


def ms(xs):
    return f"{st.mean(xs):.3f} ± {st.stdev(xs):.3f}" if len(xs) > 1 else f"{xs[0]:.3f}"


def main():
    run_dirs, metas, cell = load(sys.argv[1:])
    meta = metas[0]
    strategies = sorted({k[0] for k in cell})
    files = sorted({k[1] for k in cell})
    out = [f"# Runs {', '.join(d.name for d in run_dirs)}",
           f"Model: `{meta['model']}` · pypdf {meta['pypdf']} · repeats: {max(m['repeats'] for m in metas)} · "
           f"files scored: {len(files)}", "",
           "## Per strategy (mean over files of per-file means; ± = SD across files)", "",
           "| Strategy | n files | Precision | Recall | F1 (full date) | F1 (month-day) | Type acc | In tokens | Out tokens | Seconds | LLM called |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in strategies:
        per_file = [cell[(s, f)] for f in files if (s, f) in cell]
        avg = lambda k: [st.mean(x[k] for x in reps) for reps in per_file]
        out.append(f"| {s} | {len(per_file)} | {ms(avg('p'))} | {ms(avg('r'))} | {ms(avg('f1'))} | {ms(avg('f1_md'))} | "
                   f"{ms(avg('typed'))} | {st.mean(avg('i')):.0f} | {st.mean(avg('o')):.0f} | {st.mean(avg('s')):.1f} | "
                   f"{st.mean(avg('llm')):.0%} |")

    out += ["", "## Paired token savings (total input+output tokens, same files)", ""]
    for a, b in (("A", "B"), ("B", "D"), ("A", "D")):
        common = [f for f in files if (a, f) in cell and (b, f) in cell]
        if not common:
            continue
        tot = lambda s: sum(st.mean(x["i"] + x["o"] for x in cell[(s, f)]) for f in common)
        ta, tb = tot(a), tot(b)
        out.append(f"- {b} vs {a}: {tb:.0f} vs {ta:.0f} tokens → **{(1 - tb / ta):.1%} fewer** (n={len(common)} files)"
                   if ta else f"- {b} vs {a}: no tokens")

    out += ["", "## Run-to-run stability (mean SD of F1 across repeats)", ""]
    for s in strategies:
        sds = [st.stdev(x["f1"] for x in cell[(s, f)]) for f in files if len(cell.get((s, f), [])) > 1]
        out.append(f"- {s}: {st.mean(sds):.3f}" if sds else f"- {s}: n/a (1 repeat)")

    out += ["", "## Per file (F1 full date / month-day, mean over repeats)", "",
            "| File | " + " | ".join(strategies) + " |", "|---|" + "---|" * len(strategies)]
    for f in files:
        vals = [f"{st.mean(x['f1'] for x in cell[(s, f)]):.2f} / {st.mean(x['f1_md'] for x in cell[(s, f)]):.2f}"
                if (s, f) in cell else "–" for s in strategies]
        out.append(f"| {f} | " + " | ".join(vals) + " |")

    text = "\n".join(out)
    (run_dirs[0] / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
