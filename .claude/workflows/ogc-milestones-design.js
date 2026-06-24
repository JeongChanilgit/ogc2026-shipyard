export const meta = {
  name: 'ogc-milestones-design',
  description: 'Design M2/M4/M5 specs + author M6 regime.py for OGC2026, in parallel with the perf-fix track',
  phases: [
    { title: 'Design', detail: 'parallel: M2 geom integ, M4 no-good cut, M5 4-core parallel, M6 regime.py' },
    { title: 'Synthesize', detail: 'merge specs into sequenced integration plan + conflict matrix' },
  ],
}

const CTX = `Project: OGC 2026 "Grand Shipyard Puzzle" solver (2D irregular packing + single-machine tardiness + bay assignment, weighted-sum minimization). Working dir: C:/claude-develop/OGC2026 (Windows; use forward slashes).

Entry point: src/myalgorithm.py - a single file. Public function: algorithm(prob_info: dict, timelimit: float)->dict returning {"operations": {time_str: [op,...]}}. The evaluation server calls this directly.
Helpers already present: src/baseline_greedy.py (official greedy: EDD + best-fit + Phase-2 repair; importable funcs greedyalgorithm,_block_bbox,_block_size,_candidate_positions,_find_earliest_slot,_empty_bay_entry,_build_operations), src/geom_kernel.py (EXISTS but NOT yet integrated - suffix-OR crane mask + raster collision, NumPy), src/utils.py (Bay, Block, check_feasibility - DO NOT MODIFY, server overwrites it), src/instrument.py (off-by-default tracer).

MUST READ before designing: notes/dev-plan.md (the single source of truth: milestone defs M0-M6, data contract 5.3, function signatures 5.4, invariants section 4), notes/strategy.md (the decomposition architecture: Layer1 assignment fixes Z2/Z3 closed-form, Layer2 per-bay decoder does Z1+feasibility, no-good-cut seam). Also read src/myalgorithm.py fully and src/geom_kernel.py and tests/test_geom_kernel.py.

HARD INVARIANTS every spec MUST respect (dev-plan section 4): (1) signature fixed; (2) never modify utils.py or baseline/; (3) every returned solution passes utils.check_feasibility else return last feasible incumbent; (4) NEVER return worse than baseline - a verified best-feasible floor is mandatory; (5) no internet, no Gurobi/Xpress (OR-Tools CP-SAT optional, must degrade gracefully if absent); (6) wall-clock timeguard ~0.80-0.85*timelimit then assemble+check in remaining budget (overrun = server timeout = score -1); (7) wrap everything in try/except so any crash still returns the saved incumbent; (8) bare imports only (no __init__.py, no relative imports - the build flattens src/*.py to the zip root); (9) deterministic (random.seed 20260529).

Current milestone state (from bench + code): M0 done (gen_instance.py, bench.py, 17 instances in instances/gen/). M1 done. M2: geom_kernel.py written but NOT wired into _decode_bay. M3: PARTIALLY done - _local_search already has op_shift, op_swap, op_destroy_repair with adaptive roulette + SA acceptance. M4/M5/M6: NOT started.

SCORING: score per instance = -1 if infeasible/timeout/crash, else R - nb (R teams, nb strictly-better teams; ties = full marks). Avoiding -1 is priority #1; beating rivals on objective is priority #2.

CRITICAL COORDINATION CONSTRAINT: A separate worker is editing src/myalgorithm.py RIGHT NOW for performance fixes (a worse-than-baseline regression on w3-dominant n40 instances + a wall-clock overrun). You MUST NOT edit src/myalgorithm.py or ANY existing file. Your spec deliverables are your RETURNED TEXT. The only NEW file you may create is explicitly named in your task.`;

// Structured return so the Synthesize step builds the conflict matrix deterministically
// (no fragile free-text parsing). Each design agent puts its full prose spec in `spec`
// and ALSO fills the matrix-critical fields. (Insight: every benchmarked subagent repo
// enforces a fixed return schema for reliable downstream consumption.)
const SPEC_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['milestone', 'spec', 'functionsTouched', 'newFiles', 'effort', 'biggestRisk', 'acceptanceCommand'],
  properties: {
    milestone: { type: 'string', description: 'e.g. M2, M4, M5, M6' },
    spec: { type: 'string', description: 'Full spec in markdown: ALL numbered deliverables from the task, verbatim and complete.' },
    functionsTouched: { type: 'array', items: { type: 'string' }, description: 'Every function in src/myalgorithm.py this milestone edits (for the conflict matrix). Empty array if none.' },
    newFiles: { type: 'array', items: { type: 'string' }, description: 'New files this milestone creates (paths). Empty array if none.' },
    effort: { type: 'string', description: 'Rough effort estimate (e.g. S/M/L + one line).' },
    biggestRisk: { type: 'string', description: 'The single biggest risk in one sentence.' },
    acceptanceCommand: { type: 'string', description: 'Exact command to verify (e.g. python tools/bench.py instances/gen --timelimit 60).' },
  },
};

// All design agents do heavy reading + spec reasoning -> intentionally left on the
// inherited (strong) model; downgrading would degrade spec quality.

const RETURN_INSTR = `

RETURN FORMAT: respond via the structured schema. Put the COMPLETE spec (all numbered deliverables above, full prose, nothing dropped) in the \`spec\` field as markdown. Also fill \`functionsTouched\` (myalgorithm.py functions you touch - critical for the conflict matrix), \`newFiles\`, \`effort\`, \`biggestRisk\`, and \`acceptanceCommand\`.`;

phase('Design');

const designs = await parallel([
  () => agent(`${CTX}

YOUR TASK = Milestone M2 SPEC (geometry kernel integration). Do NOT write code to disk; return a precise spec as text.
Read src/geom_kernel.py, tests/test_geom_kernel.py, the _decode_bay / _candidate_positions / _find_earliest_slot path (src/myalgorithm.py + src/baseline_greedy.py), and how utils.check_feasibility validates collisions + crane access (the l1<=l2 suffix-OR rule).
Deliver:
1. Exact integration point: where in _decode_bay the Shapely-based bay.contains_block + _find_earliest_slot checks should be replaced or pre-filtered by geom_kernel (CraneMask + raster AND), keeping the baseline Shapely primitives as a verified FALLBACK (kernel accelerates, never becomes the source of truth - the final gate is always utils.check_feasibility).
2. The kernel's public API you rely on (class/methods, signatures) - quote what geom_kernel.py actually exposes vs. what dev-plan 5.4 specified; flag any mismatch.
3. A regression test (extend tests/test_geom_kernel.py): for every instance in instances/gen, the kernel's feasibility verdict must AGREE with utils.check_feasibility on the decoded solution (0 disagreements). Give the test skeleton.
4. Acceptance criteria: example_B2_b10 result UNCHANGED (same feasibility + objective), and large-instance decode throughput up (bench elapsed down or more search iters in same time).
5. Risk/conflict notes: list every function in myalgorithm.py your change touches (so the integrator can sequence against the perf-fix track). Estimate effort.${RETURN_INSTR}`, { label: 'M2-geom-spec', phase: 'Design', schema: SPEC_SCHEMA }),

  () => agent(`${CTX}

YOUR TASK = Milestone M4 SPEC (no-good-cut / lazy-constraint loop, the decomposition "seam"). Do NOT write code to disk; return a precise spec as text.
Read notes/strategy.md section 3 (the seam), _local_search and _decode_bay (force-place fallback) and _cpsat_assignment in src/myalgorithm.py.
The idea: when Layer-2 (per-bay decoder) is forced to defer/force-place blocks (causing Z1 to explode), it should emit a CERTIFICATE ("bay j cannot co-host block-set B" / "block i exits far past its due date in bay j"); Layer-1 / the assignment search should consume that certificate as a no-good cut and re-repair (eject overflow blocks, reassign), instead of blindly re-trying the same overloaded assignment.
Deliver:
1. Certificate data structure + exactly where _decode_bay / _decode_assignment detect & emit it (force-place was used / per-bay tardiness above a threshold).
2. How the assignment-level search (_local_search) ingests cuts: a forbidden-subset store, how op_destroy_repair / op_shift consult it to avoid regenerating cut assignments, and how repair ejects overflow blocks. Keep it at the ASSIGNMENT level (no pixel search). Re-solve is cheap because Z2/Z3 are closed-form.
3. Why this is bounded in wall-clock (must converge within the timeguard on large/tight instances) and how it degrades gracefully.
4. Acceptance: on high-density instances, force-place count drops -> Z1 improves; feasibility rate stays 100%; no timeout.
5. Risk/conflict notes: list every function in myalgorithm.py touched (esp. _local_search internals, which the perf-fix track may also edit). Estimate effort.${RETURN_INSTR}`, { label: 'M4-nogood-spec', phase: 'Design', schema: SPEC_SCHEMA }),

  () => agent(`${CTX}

YOUR TASK = Milestone M5 SPEC (4-core parallelism; server is <=4 cores / 16GB / no internet). Do NOT write code to disk; return a precise spec as text.
Read _decode_assignment, _Decoder, the seeds_decode + search phases of algorithm() in src/myalgorithm.py. Note the decomposition fact: per-bay feasibility is INDEPENDENT, so bays decode in parallel; and independent-seed GRASP restarts can run in parallel then keep the best.
Deliver:
1. Recommend ONE primary parallelization (parallel per-bay decode OR parallel independent-seed/multi-start search-then-best) with justification for THIS code shape, plus the fallback.
2. PICKLE-SAFETY analysis (critical -1 risk): what must cross the process boundary. prob_info is a dict of primitives (picklable). But _Decoder holds Bay objects and a cache; Bay/Block come from utils. Specify exactly what to send to workers (dicts/lists, not Bay objects) and what comes back (placement dicts), and how to rebuild Bay inside the worker. Module-level worker functions only (Windows spawn start-method - NOT fork; closures/lambdas are NOT picklable on Windows).
3. multiprocessing.Pool sizing (<=4 workers, never exceed), chunking, and a try/except + single-process automatic fallback so a pickling/spawn failure can NEVER produce -1. Account for Windows spawn import-cost overhead vs. small instances (when NOT to parallelize).
4. How it fits the timeguard (workers must respect a deadline; collect best feasible before assemble).
5. Acceptance: same wall-clock -> more search iters / >= single-process objective; never >4 cores; gate+timeguard intact.
6. Risk/conflict notes: functions touched in myalgorithm.py + whether a new module (e.g. src/parallel_decode.py) is cleaner. Estimate effort.${RETURN_INSTR}`, { label: 'M5-parallel-spec', phase: 'Design', schema: SPEC_SCHEMA }),

  () => agent(`${CTX}

YOUR TASK = Milestone M6 (regime routing). You ARE permitted to CREATE the NEW file src/regime.py (it does not exist). Read dev-plan.md M6 + section 5.2/5.4, strategy.md section 5 (regime table), and how algorithm() in src/myalgorithm.py sets budgets (done_by, work_deadline, decode_deadline, hard_stop), chooses seeds, and runs _local_search.
Write src/regime.py: a small, dependency-light, deterministic module that reads (w1,w2,w3), packing density, n_blocks, n_bays and returns a structured config (a plain dataclass or dict) describing: which seeds to prioritize, search time-budget fractions, ALNS operator-weight hints / mode (decomposition-dominant vs escape co-evolve), and any per-regime acceptance-temperature hint. It must:
 - import nothing beyond stdlib (no numpy/ortools) so it can never crash the solver; pure functions; deterministic.
 - expose a clear API, e.g. classify(prob_info)->Regime and a function returning the config dict, with sensible defaults that REPRODUCE current behavior when the regime is unknown (so wiring it in is a no-op until tuned - protects invariants).
 - include a docstring mapping each regime (w1-dom / w2-dom / w3-dom x loose/tight x small/large n) to its strategy, citing strategy.md section 5.
 - be fully self-contained and unit-testable.
After writing src/regime.py, ALSO write tests/test_regime.py with basic unit tests (classification on the 3 example regimes; defaults are safe).
Then RETURN a SPEC for the minimal hook needed in algorithm() to consult regime.py (exact insertion points + how the returned config maps to existing budget/seed/search variables) - but DO NOT edit myalgorithm.py yourself. Put that hook spec in \`spec\`, list the files you created in \`newFiles\` (e.g. src/regime.py, tests/test_regime.py), and put the algorithm() functions the hook touches in \`functionsTouched\`.${RETURN_INSTR}`, { label: 'M6-regime-author', phase: 'Design', schema: SPEC_SCHEMA }),
]);

const [m2, m4, m5, m6] = designs;

phase('Synthesize');

// Pre-compiled structured metadata from each spec's schema, so the conflict matrix
// is grounded in each milestone's DECLARED functionsTouched/newFiles rather than
// re-parsed from prose. (null = that design agent was skipped/failed.)
const structuredMeta = [m2, m4, m5, m6].filter(Boolean).map(d =>
  `- ${d.milestone}: functionsTouched=[${(d.functionsTouched || []).join(', ') || 'none'}]; ` +
  `newFiles=[${(d.newFiles || []).join(', ') || 'none'}]; effort=${d.effort}; ` +
  `biggestRisk=${d.biggestRisk}; accept=${d.acceptanceCommand}`).join('\n');

await agent(`${CTX}

You are the integration planner. Below are 4 milestone specs (M2, M4, M5) and the M6 regime author's report, plus a STRUCTURED METADATA block each spec declared. Write the file notes/milestone-impl-plan.md (create/overwrite it) containing:
1. A one-paragraph status recap (what's done M0-M3, what these specs add M2-M6).
2. A CONFLICT MATRIX: rows = the functions in src/myalgorithm.py that get edited (algorithm() orchestrator, _local_search, _decode_bay, _decode_assignment, _Decoder, seeds/budget block); columns = {perf-fix track, M2, M4, M5, M6}; mark which track touches which function. SEED THE MATRIX FROM THE STRUCTURED METADATA's functionsTouched fields (they are authoritative), then cross-check against each prose spec. The perf-fix track (run by a separate worker, in parallel) is editing: the floor/gate logic in algorithm(), _decode_bay scheduling quality, and the timeguard constants. Call out every collision so edits get SERIALIZED safely (this is NOT a git repo, so no worktree isolation - edits to the same function must be sequential).
3. A RECOMMENDED APPLY ORDER interleaving the perf-fix track and milestones, with rationale: perf fixes (regression + timeguard) land FIRST (they are -1 / invariant-violation risks), then milestones in dependency order. For each milestone give: prerequisite, the 1-2 line change summary, and the exact acceptance command (use each spec's declared acceptanceCommand).
4. Per-milestone effort estimate + the single biggest risk (use the declared effort/biggestRisk fields).
Keep it tight and actionable - it will be executed by the main session. After writing the file, return a short summary (which milestones are ready to integrate, the recommended first 3 actions, any open question for the user).

=== STRUCTURED METADATA (declared by each spec; authoritative for the conflict matrix) ===
${structuredMeta}

=== M2 SPEC ===
${m2?.spec ?? '(M2 spec unavailable - agent skipped/failed)'}

=== M4 SPEC ===
${m4?.spec ?? '(M4 spec unavailable - agent skipped/failed)'}

=== M5 SPEC ===
${m5?.spec ?? '(M5 spec unavailable - agent skipped/failed)'}

=== M6 REGIME AUTHOR REPORT ===
${m6?.spec ?? '(M6 report unavailable - agent skipped/failed)'}`, { label: 'synthesize-plan', phase: 'Synthesize' });

return {
  created: ['src/regime.py', 'tests/test_regime.py', 'notes/milestone-impl-plan.md'],
  note: 'Specs for M2/M4/M5 in notes/milestone-impl-plan.md; M6 regime.py authored. myalgorithm.py untouched (perf-fix track owns it).',
};