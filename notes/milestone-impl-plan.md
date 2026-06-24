# Milestone Integration Plan — OGC 2026 (`src/myalgorithm.py`)

> Author: integration planner. Date 2026-05-29. SSOT for serializing the perf-fix track
> + M2/M4/M5/M6 into `src/myalgorithm.py`. This is NOT a git repo — there is no worktree
> isolation, so any two edits to the **same function** MUST be applied **sequentially**.
> The specs' line references were verified against the live file and are accurate.

---

## 1. Status recap

**Done (M0–M3).** M0: `tools/gen_instance.py` + `tools/bench.py` + 17 fixed-seed instances in
`instances/gen/` (n10/n40/n120 × loose/tight × w1/w2/w3-dom). M1: function boundaries are
clean inside the single `myalgorithm.py` (decode / assign / search / orchestrator), `geom_kernel.py`
+ `regime.py` are bare-importable helpers. M2: `geom_kernel.py` is **written and already wired**
as a Shapely *prefilter* inside `baseline_greedy._find_earliest_slot` (lines 229/239/255), which
`_decode_bay` calls — so the kernel already accelerates the decode; what is *missing* is the
per-call mask-rebuild fix + the verdict-agreement regression test. M3: `_local_search` already has
op_shift/op_swap/op_destroy_repair with adaptive roulette + SA acceptance + stagnation stop.

**These specs add.** **M2** closes the geometry-kernel gap (mask rebuilt every candidate → throughput
loss on dense bays; ship a `geom_kernel`-only fast-path guard + 2 agreement tests). **M4** adds the
no-good-cut "seam": a `BayCert` certificate from the decoder + a `_CutStore` memory in `_local_search`
so the search stops re-proposing toxic block-sets (cuts force-place count down → Z1 down on dense).
**M5** adds `src/parallel_decode.py` (NEW): 4-core independent-seed multi-start, fallback to in-process,
plus a ~12-line call-site swap in `algorithm()`. **M6** adds `src/regime.py` (NEW, already created):
regime routing that retunes seed order / budget fractions / op weights / SA temp / CP-SAT enable, wired
into `algorithm()` via config fields whose defaults reproduce today's behavior bit-identically.

---

## 2. CONFLICT MATRIX

Rows = edited functions in `src/myalgorithm.py`. Columns = tracks. `X` = track edits this function;
`(call)` = track only adds a call site / passes a new kwarg (low conflict); `—` = no touch.
NEW FILES (`parallel_decode.py`, `regime.py`) live outside `myalgorithm.py` and conflict with nobody.

| `myalgorithm.py` function (lines)            | perf-fix | M2        | M4         | M5      | M6      |
|----------------------------------------------|----------|-----------|------------|---------|---------|
| `algorithm()` orchestrator (781–1105)        | **X** (floor/gate logic) | — | (call) trace only | **X** (call-site swap 1017–1037) | **X** (import + budget/seed/cpsat fields) |
| `algorithm()` timeguard consts (841–845,867–871) | **X** (0.80/0.93/check_cost) | — | — | reads `decode_deadline` live | **X** (literals→`rc.work_frac`/`rc.hard_stop_frac`) |
| `_decode_bay` (117–166)                       | **X** (sched. quality) | (opt A only) | **X** (return `(res, forced_ids)`) | — | — |
| `_decode_assignment` (425–439)                | —        | —         | — (uses 2-tuple wrapper) | — | — |
| `_Decoder.decode` (191–218)                   | —        | —         | **X** (cache 2→3-tuple + `decode_full`) | — | — |
| `_local_search` (447–735)                     | **X** (w3-dom regression, stagnation) | — | **X** (`_CutStore`, cut consults, destroy branch) | — | (call) +2 kwargs `op_weights0`,`sa_temp_frac` |
| seeds/budget block (946–1042)                 | **X** (timeguard) | — | — | **X** (build seeds list, parallel swap) | **X** (cpsat gate `rc.use_cpsat`, seed reorder) |
| `geom_kernel.py` (separate file)              | —        | **X** (Opt B fast-path guard) | — | — | — |

### Collisions that MUST be serialized (same function, two writers)

- **C1 — `algorithm()` orchestrator + timeguard (841–845, 867–871, floor 883–945, gate 1047–1105):**
  perf-fix **and** M5 **and** M6 all edit here. **Perf-fix lands first** (it owns the floor/gate/timeguard
  constants). M6 then *replaces the literals* it left (`0.80`→`rc.work_frac`, `0.93`→`rc.hard_stop_frac`).
  M5 then inserts its call swap at 1017–1037. Apply order: perf-fix → M6 → M5.
- **C2 — `_local_search` body (447–735):** perf-fix (w3-dom regression + stagnation cure) **and** M4
  (`_CutStore` + cut consults in op_shift/op_swap/op_destroy_repair 488–588) **and** M6 (2 new kwargs at
  the 447 signature + lines 592/599). HIGH overlap — M4's guard-clauses sit in the exact lines perf-fix is
  rewriting. **Perf-fix MUST land and freeze first.** Then M6's kwargs (mechanical, defaults = no-op), then
  M4 rebased onto the frozen operator bodies.
- **C3 — `_Decoder.decode` (191–218):** only M4 edits it (cache 2→3-tuple + `decode_full`). The 2-tuple
  `decode()` wrapper is the firewall: every existing caller (`_decode_assignment`, the 3 operators) keeps
  working. No perf-fix edit expected here, but **if** the perf-fix touches the cache for `_decode_bay`
  scheduling quality, M4 rebases after it.
- **C4 — `_decode_bay` (117–166):** perf-fix edits scheduling quality; M4 changes the *return contract* to
  `(result, forced_ids)`; M2 Option A would also thread a running `CraneMask` here. **Avoid M2 Option A**
  (use Option B, geom_kernel-only) precisely to keep this function single-writer between perf-fix and M4.
  Order: perf-fix → M4. M2 stays out of this function entirely.

### Non-collisions (safe / parallel)

- `parallel_decode.py` and `regime.py` are **new files** — zero conflict; can be authored anytime.
- M6's `regime.py` already exists with passing tests; only its *wiring* into `algorithm()` collides (C1/C2).
- M2 Option B lives **100% in `geom_kernel.py`** (no `myalgorithm.py` edit) — fully parallel to everything.
- M4's `tr.log("cut", …)` trace calls in `algorithm()` are additive only (no behavior change).

---

## 3. RECOMMENDED APPLY ORDER

Principle: **−1 / invariant-violation risks land FIRST**, then milestones in dependency order. The
perf-fix track is fixing an active (a) worse-than-baseline regression on w3-dom n40 and (b) wall-clock
overrun — both are direct −1 / invariant-§4.4 violations and must precede everything.

### Step 0 — PERF-FIX (separate worker, already in flight) — **BLOCKER for all below**
- **Change:** floor/gate logic in `algorithm()`, `_decode_bay` scheduling quality, `_local_search`
  w3-dom regression + stagnation cure, timeguard constants (841–845).
- **Accept:** `python tools/bench.py instances/gen --timelimit 60` → feasible 100%, timeouts 0,
  every instance ≤ 0.85·T, and `gen_n40_loose_w3_s8/s17` + `gen_n40_tight_w3_s10` **≥ baseline**
  (regression gone). Plus `python -m pytest tests/test_smoke.py tests/test_feasibility.py -v`.
- **Gate to proceed:** perf-fix worker signals `_local_search` + `algorithm()` + `_decode_bay` are
  **frozen**. No milestone that edits these functions may start before this signal.

### Step 1 — M2 (geom kernel, Option B) — *can run in parallel with Step 0* (no `myalgorithm.py` edit)
- **Prerequisite:** none (lives entirely in `geom_kernel.py` + `tests/`). Independent of the perf-fix.
- **Change (1–2 lines):** in `geom_kernel.crane_path_maybe_clear` and `same_height_maybe_clear`, add a
  `if len(existing_blocks) < K (≈8): return False` short-circuit so small blocker sets skip the raster
  rebuild and fall straight to the (cheaper) Shapely AABB early-out; only rasterize on dense bays.
  Add the 2 agreement tests to `tests/test_geom_kernel.py`.
- **Accept:**
  - `python tools/run_local.py instances/example/example_B2_b10.json --timelimit 60` → objective
    **bit-identical** to before (kernel is a prefilter, must not move the verdict; expect 1022.70).
  - `python -m pytest tests/test_geom_kernel.py -v` → existing test + 2 new agreement tests, 0 disagreements.
  - `python tools/bench.py instances/gen --timelimit 60` → no regression on `n40_*_w3_*` rows; throughput
    (elapsed ↓ or trace `iters` ↑) on n120 rows.
- **Note:** do **NOT** take M2 Option A (it edits `_decode_bay`, colliding with perf-fix + M4). Defer A.

### Step 2 — M6 (regime wiring) — first `myalgorithm.py` milestone after perf-fix freeze
- **Prerequisite:** Step 0 frozen (edits `algorithm()` + `_local_search` signature — C1/C2).
- **Change (2 lines summary):** add guarded `from regime import config_from_prob, DEFAULT_CONFIG`; compute
  `rc = config_from_prob(prob_info)` after `bay_u`; replace budget/seed/cpsat/op-weight/SA-temp literals
  with `rc.*` fields whose defaults equal today's values (TOSSUP/UNKNOWN ⇒ byte-identical path).
- **Accept:** `python -m pytest tests/test_regime.py -v` (already green) **plus** post-wire
  `python tools/bench.py instances/gen --timelimit 60` → feasible 100%, timeouts 0, `example_B2_b10`
  bit-identical (loose ⇒ TOSSUP ⇒ no-op), and ≥1 DECOMPOSITION instance (w2/w3-loose) improves with no regression.

### Step 3 — M4 (no-good-cut seam) — highest-conflict, lands after perf-fix + M6 settle
- **Prerequisite:** Step 0 frozen AND Step 2 applied (M4 + M6 both touch `_local_search` 447 signature
  and operator bodies — rebase M4 onto the post-M6 `_local_search`). C2/C3/C4.
- **Change (2 lines summary):** add `BayCert` + `_Decoder.decode_full` (cache 2→3-tuple, keep `decode`
  2-tuple wrapper as firewall) + `_decode_bay` returns `(result, forced_ids)`; add `_CutStore` in
  `_local_search` with cut consults *before* each `decoder.decode` in op_shift/op_swap/op_destroy_repair
  + one cut-driven destroy branch. Cuts only prune/steer — empty/failed store ⇒ exact M3 behavior.
- **Accept:** `python tools/bench.py instances/gen --timelimit 60` → on dense set
  (`gen_n120_tight_w1_s14`, `gen_n120_tight_w2_s15`, `gen_n40_tight_w3_s10`, `gen_n40_loose_w3_s8/s17`)
  force-place total (trace `tr.log("cut", …)`) **strictly decreases** + Z1 improves; feasible 100%;
  `example_B2_b10` bit-identical (loose ⇒ cuts never fire). Plus `pytest tests/test_feasibility.py -v`.

### Step 4 — M5 (4-core parallel) — last; only call-site swap in `myalgorithm.py`
- **Prerequisite:** Step 0 frozen (M5 swaps the search call at 1017–1037, inside the block perf-fix +
  M6 edit — C1). Author `parallel_decode.py` anytime; apply the call swap last.
- **Change (2 lines summary):** ship `src/parallel_decode.py` (`_search_worker` module-level +
  `run_parallel_multistart` returning `(best_assign,best_obj)` or `None`, never raises); in `algorithm()`
  wrap the single `_local_search` call with a `USE_PARALLEL` gate (timelimit≥20, n≥30, n_bays≥2) →
  `run_parallel_multistart` → parent re-decode winner → fall through to in-process `_local_search` on
  `None`/mismatch.
- **Accept:**
  - `python -m pytest tests/test_parallel_pickle.py -v` (NEW) → task-args + `_search_worker` picklable;
    2-worker run ≤ single-process objective.
  - `python tools/bench.py instances/gen --timelimit 60` → parallel objective ≤ single-process on every
    instance, summed worker iters > single-process, feasible 100%, timeouts 0, peak ≤ 4 cores.
  - Verify `tools/run_local.py` + `tools/bench.py` have `if __name__ == "__main__":` (spawn fork-bomb guard).

---

## 4. Per-milestone effort + single biggest risk

| Milestone | Effort | Single biggest risk |
|-----------|--------|---------------------|
| **Step 0 perf-fix** (other worker) | in flight | A timeguard tightening that starves the search of useful iters on n120 while fixing the overrun (over-correction). |
| **M2** (Option B) | ~1–2 h | The `K` fast-path threshold flips a verdict if mis-set so the kernel is no longer a pure prefilter → `example_B2_b10` objective drifts. Mitigation: agreement tests assert 0 disagreement + bit-identical objective. |
| **M6** wiring | ~1–2 h | A non-default regime (DECOMPOSITION/ESCAPE) field raises `hard_stop_frac` > 0.93 or reorders seeds so a feasible seed is dropped → timeout/regression. Mitigation: all regimes keep `hard_stop_frac ≤ 0.93`; defaults are no-ops. |
| **M4** seam | ~0.5–1 day | The cut store becomes load-bearing for *correctness* (a move depends on a cut) instead of just pruning — or the 2→3-tuple cache split breaks an existing `decode()` caller. Mitigation: 2-tuple wrapper firewall; empty store ≡ M3; gate is sole feasibility authority. |
| **M5** parallel | ~1–1.5 days | A closure/lambda/`_Decoder` leaks across the spawn boundary → `PicklingError` at dispatch = crash = −1. Mitigation: module-level worker only, send raw `prob_info`, `pickle.dumps` pre-flight test, `None`-returning fallback wraps everything. |

---

## 5. Notes for the executor

- Re-bench (`tools/bench.py instances/gen --timelimit 60`) is the **single regression gate after every step**;
  treat any feasible<100%, timeout>0, or `example_B2_b10` objective drift as a stop-the-line event.
- Local env name is **`ogc2025`** (`C:/Users/peter/anaconda3/envs/ogc2025/python.exe`, Py 3.11), NOT `ogc2026`
  (CLAUDE.md §8 / dev-plan §5.4 are stale on this point — flag to user; see open questions).
- dev-plan §5.4 `CraneMask` API (`can_place`/`add`/`remove`) is **obsolete**; real API is
  `clear_for`/`crane_path_maybe_clear`/`same_height_maybe_clear`. Update the doc when convenient.
