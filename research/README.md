# research/

Dedicated store for literature research backing the OGC 2026 solver work.

## z1-tardiness/  —  Driving Z1 (total tardiness) toward zero  (147 papers, 2026-06-06)

| File | What |
|---|---|
| `z1-literature-2026-06-06.html` | **Main deliverable** — 147 papers by theme + 8 application insights (①–⑧) + implementation roadmap + Method→our-code mapping. Open in a browser. |
| `z1-tardiness-bibliography.md` | Readable markdown bibliography of all 147 papers (links, method, Z1-relevance), grouped by the 18 search themes. |
| `z1-papers-data.json` | Machine-readable source data (one record per paper). |

**One-line takeaway:** crane vertical-access (j>=k) = Blocking Job-Shop + Container Block-Relocation; the lever is crane *serialization order + layer placement + timing*, not packing density. Top insight = separate **sequence** from **timing** and recompute optimal ENTRY/EXIT with an exact O(n^2) timing DP (objective-safe, geometry unchanged).

Method: 18 parallel `haiku` web-researchers (177 hits → 147 unique after dedup) synthesized by `opus`. Generators: `notes/_z1_litpack.py`, `notes/_z1_html.py`, `notes/_z1_research_export.py`.
