"""Figures + error analysis for one or more merged runs.

  python analyze.py <run_id> [<run_id> ...]
Writes into ../figures/:  fig_tradeoff.png, fig_perfile.png, error_analysis.md
"""
import random
import statistics as st
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from rescore import load  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)
NAMES = {"A": "A: PDF→LLM", "B": "B: text→LLM (GRYPH)", "C": "C: regex", "D": "D: regex→LLM", "E": "E: dateparser"}

run_dirs, metas, cell = load(sys.argv[1:])
strategies = sorted({k[0] for k in cell})
files = sorted({k[1] for k in cell})


def per_file(s, key):
    return [st.mean(x[key] for x in cell[(s, f)]) for f in files if (s, f) in cell]


# ── Figure 1: cost vs accuracy trade-off ──────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
for ax, metric, title in ((axes[0], "f1", "F1, full date"), (axes[1], "f1_md", "F1, month-day only")):
    for s in strategies:
        tok = [a + b for a, b in zip(per_file(s, "i"), per_file(s, "o"))]
        f1 = per_file(s, metric)
        ax.errorbar(st.mean(tok), st.mean(f1), yerr=st.stdev(f1) / len(f1) ** 0.5 if len(f1) > 1 else 0,
                    fmt="o", capsize=4, label=NAMES.get(s, s))
        ax.annotate(s, (st.mean(tok), st.mean(f1)), textcoords="offset points", xytext=(6, 6))
    ax.set_title(title)
    ax.set_xlabel("Mean tokens per syllabus (input + output)")
    ax.grid(alpha=0.3)
axes[0].set_ylabel("Mean F1 (± SE across syllabi)")
axes[1].legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "fig_tradeoff.png", dpi=200)

# ── Figure 2: per-syllabus F1 heatmap (month-day) ─────────────────────────────
grid = [[st.mean(x["f1_md"] for x in cell[(s, f)]) if (s, f) in cell else float("nan") for s in strategies] for f in files]
fig, ax = plt.subplots(figsize=(6, 0.4 * len(files) + 1.5))
im = ax.imshow(grid, cmap="viridis", vmin=0, vmax=1, aspect="auto")
ax.set_xticks(range(len(strategies)), strategies)
ax.set_yticks(range(len(files)), files, fontsize=7)
for i, row in enumerate(grid):
    for j, v in enumerate(row):
        if v == v:
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6, color="white" if v < 0.6 else "black")
fig.colorbar(im, ax=ax, label="F1 (month-day)")
ax.set_title("Per-syllabus F1 by strategy")
fig.tight_layout()
fig.savefig(OUT / "fig_perfile.png", dpi=200)

# ── Error analysis ────────────────────────────────────────────────────────────
out = [f"# Error analysis — runs {', '.join(d.name for d in run_dirs)}", f"Model `{metas[0]['model']}`", ""]

out += ["## 1. Hallucination on the no-deadline syllabus (carleton_comp2402a_f26, gold = [])", ""]
for s in strategies:
    reps = cell.get((s, "carleton_comp2402a_f26"), [])
    if reps:
        counts = [len({e.get("dueDateISO") for e in x["events"]}) for x in reps]
        out.append(f"- {s}: predicted dates per repeat = {counts}")

out += ["", "## 2. Grid-layout syllabi (dates only in a calendar image) — recall", ""]
for f in ("carleton_comp1405a_w25", "carleton_comp1405b_f25"):
    vals = [f"{s} {st.mean(x['r'] for x in cell[(s, f)]):.2f}" for s in strategies if (s, f) in cell]
    out.append(f"- {f}: " + " · ".join(vals))

out += ["", "## 3. Wrong-year errors (predicted MM-DD is in the gold set, but the year differs)", ""]
for s in strategies:
    wrong = right = 0
    for f in files:
        for x in cell.get((s, f), []):
            gold_full = {g["dueDateISO"] for g in x["gold"]}
            gold_md = {d[5:] for d in gold_full}
            for d in {e.get("dueDateISO") for e in x["events"] if e.get("dueDateISO")}:
                if d in gold_full:
                    right += 1
                elif d[5:] in gold_md:
                    wrong += 1
    if right + wrong:
        out.append(f"- {s}: {wrong} of {right + wrong} date matches had the wrong year ({wrong / (right + wrong):.0%})")

out += ["", "## 4. Hybrid routing (D): F1 when regex was trusted vs when the LLM was called", ""]
skipped = [x for f in files for x in cell.get(("D", f), []) if not x["llm"]]
called = [x for f in files for x in cell.get(("D", f), []) if x["llm"]]
for name, xs in (("regex trusted (no LLM)", skipped), ("LLM called", called)):
    if xs:
        out.append(f"- {name}: n={len(xs)}, F1 full {st.mean(x['f1'] for x in xs):.3f}, "
                   f"month-day {st.mean(x['f1_md'] for x in xs):.3f}")

out += ["", "## 5. Run-to-run variation in number of events (LLM strategies)", ""]
for s in strategies:
    sds = [st.stdev(len(x["events"]) for x in cell[(s, f)]) for f in files if len(cell.get((s, f), [])) > 1]
    if sds and any(sds):
        out.append(f"- {s}: mean SD of event count across repeats = {st.mean(sds):.2f}")

out += ["", "## 6. Significance: paired differences in per-syllabus F1 (full date)", "",
        "Paired sign-flip permutation test (two-sided, 20,000 permutations) and bootstrap 95% CI of the mean "
        "difference (10,000 resamples), seed 0. Unit = syllabus (mean over repeats).", "",
        "| Comparison | n | Mean diff | 95% CI | p |", "|---|---|---|---|---|"]
rng = random.Random(0)
for a, b in (("A", "B"), ("B", "D"), ("D", "C"), ("C", "E"), ("A", "D")):
    common = [f for f in files if (a, f) in cell and (b, f) in cell]
    d = [st.mean(x["f1"] for x in cell[(a, f)]) - st.mean(x["f1"] for x in cell[(b, f)]) for f in common]
    if not d:
        continue
    obs = abs(st.mean(d))
    perm = sum(abs(st.mean(x if rng.random() < 0.5 else -x for x in d)) >= obs - 1e-12 for _ in range(20000))
    boots = sorted(st.mean(rng.choice(d) for _ in d) for _ in range(10000))
    out.append(f"| {a} − {b} | {len(d)} | {st.mean(d):+.3f} | [{boots[250]:+.3f}, {boots[9749]:+.3f}] | "
               f"{(perm + 1) / 20001:.4f} |")

(OUT / "error_analysis.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
print(f"\nFigures in {OUT}")
