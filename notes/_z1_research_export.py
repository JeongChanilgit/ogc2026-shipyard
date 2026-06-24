# -*- coding: utf-8 -*-
"""Export the Z1 literature research into a dedicated research/ folder:
copies HTML + JSON, and generates a readable markdown bibliography + README index."""
import json, re, sys, shutil
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(r"C:\claude-develop\OGC2026")
RES = ROOT / "research"
RES.mkdir(exist_ok=True)
SUB = RES / "z1-tardiness"
SUB.mkdir(exist_ok=True)

DATA = ROOT / "notes" / "z1-papers-data.json"
HTML = ROOT / "notes" / "z1-literature-2026-06-06.html"

# copy primary artifacts
shutil.copy2(DATA, SUB / "z1-papers-data.json")
shutil.copy2(HTML, SUB / "z1-literature-2026-06-06.html")

d = json.loads(DATA.read_text(encoding="utf-8"))
topics = d["topics"]
total = d["total"]

CAT_NAMES = [
    "Shipyard Block Spatial Scheduling (SSP)",
    "Shipbuilding Block Stockyard & Stacking",
    "Crane Scheduling — Non-Crossing / Interference",
    "Container Pre-Marshalling & Block Relocation (j>=k analog)",
    "Single-Machine Total / Weighted Tardiness",
    "Parallel-Machine Total Weighted Tardiness",
    "RCPSP with Spatial / 2D Resources",
    "Temporal / Dynamic 2D Bin Packing with Due Dates",
    "Irregular Strip Packing / Nesting (NFP)",
    "Large Neighborhood Search (LNS / ALNS)",
    "Constraint Programming (CP-SAT / OR-Tools)",
    "Berth Allocation (space-time packing)",
    "Just-in-Time / Due-Date Scheduling & Timing DP",
    "Matheuristics & Logic-Based Benders Decomposition",
    "GA / Metaheuristics for Shipyard",
    "Time-Space Network & Dynamic Facility Layout",
    "Blocking Job-Shop / No-Wait (crane-hold analog)",
    "Combined 2D Packing + Scheduling (AM nesting)",
]

def norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:55]

displayed = set()
n = 0
lines = []
lines.append("# OGC 2026 — Z1 (Tardiness) → 0 : Literature Bibliography\n")
lines.append(f"> {total} unique papers · 18 themes · collected via 18 parallel `haiku` web-researchers, synthesized by `opus` · 2026-06-06\n")
lines.append("Companion files in this folder:\n")
lines.append("- **`z1-literature-2026-06-06.html`** — full report with the 8 application insights, roadmap, and Method→our-code mapping (open in a browser).\n")
lines.append("- **`z1-papers-data.json`** — machine-readable source data (title/authors/venue/url/method/relevance).\n")
lines.append("\n**Core framing:** the crane vertical-access rule (j>=k) is structurally a *Blocking Job-Shop* (zero-buffer) + *Container Block-Relocation* (clear-above) constraint. Packing density is not the lever; crane serialization is. See the HTML report for the full insight write-up.\n")
lines.append("\n---\n")

for i, tp in enumerate(topics):
    name = CAT_NAMES[i] if i < len(CAT_NAMES) else tp.get("topic", "")[:60]
    bucket = []
    for p in tp.get("papers", []):
        k = norm(p.get("title", ""))
        if not k or k in displayed:
            continue
        displayed.add(k)
        n += 1
        bucket.append((n, p))
    if not bucket:
        continue
    lines.append(f"\n## {i+1}. {name}  ({len(bucket)})\n")
    for num, p in bucket:
        title = p.get("title", "")
        url = p.get("url", "")
        yr = p.get("year", "")
        auth = p.get("authors", "")
        ven = p.get("venue", "")
        meth = p.get("method", "")
        rel = p.get("relevance", "")
        head = f"**{num}.** "
        head += f"[{title}]({url})" if url else f"**{title}**"
        if yr:
            head += f" ({yr})"
        lines.append(head + "  ")
        meta = " · ".join(x for x in [auth, ven] if x)
        if meta:
            lines.append(f"*{meta}*  ")
        if meth:
            lines.append(f"- **Method:** {meth}  ")
        if rel:
            lines.append(f"- **→ Z1 relevance:** {rel}  ")
        lines.append("")

md = "\n".join(lines)
(SUB / "z1-tardiness-bibliography.md").write_text(md, encoding="utf-8")

# README index for the research folder
readme = f"""# research/

Dedicated store for literature research backing the OGC 2026 solver work.

## z1-tardiness/  —  Driving Z1 (total tardiness) toward zero  ({total} papers, 2026-06-06)

| File | What |
|---|---|
| `z1-literature-2026-06-06.html` | **Main deliverable** — {total} papers by theme + 8 application insights (①–⑧) + implementation roadmap + Method→our-code mapping. Open in a browser. |
| `z1-tardiness-bibliography.md` | Readable markdown bibliography of all {total} papers (links, method, Z1-relevance), grouped by the 18 search themes. |
| `z1-papers-data.json` | Machine-readable source data (one record per paper). |

**One-line takeaway:** crane vertical-access (j>=k) = Blocking Job-Shop + Container Block-Relocation; the lever is crane *serialization order + layer placement + timing*, not packing density. Top insight = separate **sequence** from **timing** and recompute optimal ENTRY/EXIT with an exact O(n^2) timing DP (objective-safe, geometry unchanged).

Method: 18 parallel `haiku` web-researchers (177 hits → {total} unique after dedup) synthesized by `opus`. Generators: `notes/_z1_litpack.py`, `notes/_z1_html.py`, `notes/_z1_research_export.py`.
"""
(RES / "README.md").write_text(readme, encoding="utf-8")

print("research/ dir:", RES)
for f in sorted(RES.rglob("*")):
    print("  ", f.relative_to(ROOT), f"({f.stat().st_size} bytes)" if f.is_file() else "(dir)")
