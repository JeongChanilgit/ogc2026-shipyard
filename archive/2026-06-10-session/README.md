# archive/2026-06-10-session — authoritative snapshot

Current `src/` after the 2026-06-10 session. **This is what `submissions/v08-adaptive-raster-20260610-034634.zip` was built from** (sha256 cd93cc23e7481774…). myalgorithm.py md5 = 77f3725d26e45046909df4b80221b43c.

Supersedes `archive/2026-06-09-adaptive-raster/` (that snapshot predates the best-of-N edit). utils.py / baseline/ untouched. AST OK.

## Shipped change (active by default)
- **Adaptive raster floor gate** (`src/myalgorithm.py`, `if _fast_floor:` branch only):
  when the fast floor triggers (short tl relative to n), default to raster floor
  (`OGC_FLOOR_RASTER`) + `pos_k=3`, env-scoped and restored in `finally`. Kill-switches
  intact (`OGC_FLOOR_RASTER=0` reproduces the exact prior shipped behaviour). Non-fast-floor
  path untouched. **Verified**: tl=100 full-20 all feasible, max z1=7 (no −1, no catastrophe);
  tl=300 provably + empirically inert (max est=108 < trigger 120). Converts short-tl z1
  catastrophes (obj 6.5M–46M → 208K–669K).

## Gated experiments (default OFF → inert; NOT shipped, kept as infrastructure)
- `OGC_PP_MULTISTART` (myalgorithm.py ~L5093): cold best-of-N postprocess restart from the
  floor, keep best. **NEGATIVE result** — the postprocess expands to fill the budget, so the
  self-calibrating restart rarely triggers; harvest is inconsistent (prob_6 ✓, prob_19 ✗).
  Default OFF = byte-identical. See [[ogc2026-z3-variance-2026-06-10]].
- `OGC_FRONTB_TRIES/SWAP_TOP/STALL` (Front B strength): tuning gives ~1.5% net but buried under
  ±15–27% run-to-run variance → NOT shipped (defaults kept 24/40/2).

## Key findings this session (why no further default change)
1. **Long-tl obj is z3-dominated** (z3 = 84–99% of obj on z1=0 instances), but **z3 is
   packing-blocked (z1↔z3 Pareto frontier).** Decode test (`notes/_z3_pack_test.py`): forcing
   blocks to preferred bays (z3→0) overloads bays → z1 explodes → obj 20–180× worse. The
   z3-minimizing CP-SAT seed (`_cpsat_assignment`, minimizes z2+z3) ALREADY exists and is
   correctly rejected by the gate. **CP-SAT global reassignment is not worth building.**
2. **Run-to-run variance dominates** the remaining differences (intrinsic CP-SAT
   num_search_workers=4 + wall-clock non-determinism; prob_12 obj 118–150K across runs).
   Single captures (e.g. v7) must not be trusted for ranking — use distributions.
3. Conclusion: algorithm is mature. z1 solved (eval long-tl), z3 near practical floor (Pareto),
   z2 tiny weight. Session win = the adaptive raster gate.

## Reproduce / data
- Drivers: `notes/_capture20.py`, `notes/_z3probe.py`, `notes/_cmp_caps.py`,
  `notes/_z3_lb_probe.py`, `notes/_z3_pack_test.py`.
- Data: `results/capture/{adaptive100,default100,raster_k2_100,v7,fbstrong300,vd*,vs*,plateau600,off900,ms900*,robust100,robust300chk}`.
- Handoff: `notes/SESSION-HANDOFF-2026-06-09-z3-mainline.md`. HTML: `notes/progress-2026-06-10.html`.
- Memory: ogc2026-adaptive-raster-2026-06-09, ogc2026-z3-variance-2026-06-10, ogc2026-shorttl-robustness-2026-06-09 (PM #6).
