"""Offline sensitivity analysis of the hybrid router (strategy D) — no API calls.

D(k) = regex output (C) if regex finds >= k events, else the LLM text output (B).
D's LLM branch is identical to B (same prompt and input), so saved C and B predictions simulate any k.
Also tests a stricter router: trust regex only if it found >= 3 events AND all its dates fall in one calendar
year (a cheap sanity check against the wrong-year failure).
Validation: k = 3 reproduces the real D run (F1 0.369 simulated vs 0.370 measured, run 20261025-060628).

  python sweep.py <run_id>
Writes ../figures/fig_router_sweep.png and router_sweep.md
"""
import statistics as st
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from bench import score  # noqa: E402
from rescore import load  # noqa: E402

OUT = Path(__file__).parent / "figures"
_, metas, cell = load(sys.argv[1:])
files = sorted({f for s, f in cell if s in ("B", "C")})
md = lambda evs: [{**e, "dueDateISO": e["dueDateISO"][5:]} for e in evs if e.get("dueDateISO")]


def simulate(trust):
    """trust(regex_events) -> bool. Returns (mean F1 full, mean F1 month-day, mean tokens, LLM-call rate)."""
    f1s, mds, toks, calls = [], [], [], []
    for f in files:
        for c, b in zip(cell[("C", f)], cell[("B", f)]):  # pair repeats
            use_regex = trust(c["events"])
            pick = c if use_regex else b
            p, r, f1, _ = score(pick["events"], pick["gold"])
            f1s.append(f1)
            mds.append(score(md(pick["events"]), md(pick["gold"]))[2])
            toks.append(0 if use_regex else b["i"] + b["o"])
            calls.append(0 if use_regex else 1)
    return st.mean(f1s), st.mean(mds), st.mean(toks), st.mean(calls)


rows = []
for k in [1, 2, 3, 5, 8, 12, 20, 10 ** 9]:
    label = "never trust regex (= B)" if k == 10 ** 9 else f"k = {k}" + (" (GRYPH-style D)" if k == 3 else "")
    rows.append((label, *simulate(lambda ev, k=k: len(ev) >= k)))
# year-sanity router: trust regex only if >= 3 events AND all regex dates fall in one calendar year
rows.append(("k = 3 + single-year check", *simulate(
    lambda ev: len(ev) >= 3 and len({e["dueDateISO"][:4] for e in ev}) == 1)))

out = [f"# Router sweep (offline) — model `{metas[0]['model']}`, {len(files)} syllabi × repeats", "",
       "| Router | F1 full | F1 month-day | Mean tokens | LLM-call rate |", "|---|---|---|---|---|"]
out += [f"| {n} | {a:.3f} | {b:.3f} | {t:.0f} | {c:.0%} |" for n, a, b, t, c in rows]
(OUT / "router_sweep.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))

fig, ax = plt.subplots(figsize=(5.5, 4))
ks = [r for r in rows if r[0].startswith("k =") and "check" not in r[0]]
ax.plot([r[3] for r in ks], [r[1] for r in ks], "o-", label="regex if ≥ k events, else LLM")
for r in ks:
    ax.annotate(r[0].split(" (")[0], (r[3], r[1]), textcoords="offset points", xytext=(5, -10), fontsize=7)
b = rows[[r[0] for r in rows].index("never trust regex (= B)")]
ax.plot(b[3], b[1], "s", label="always LLM (B)")
y = rows[-1]
ax.plot(y[3], y[1], "^", label="k=3 + single-year check")
ax.set_xlabel("Mean tokens per syllabus")
ax.set_ylabel("Mean F1 (full date)")
ax.set_title("Hybrid router: cost vs accuracy")
ax.grid(alpha=0.3)
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig(OUT / "fig_router_sweep.png", dpi=200)
