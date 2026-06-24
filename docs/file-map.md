# OGC2026 File Map

This file is the first context boundary before broad source reads or implementation.

## Major Areas

- `src/`: active solver code. `src/myalgorithm.py` is the submission entrypoint. Helper modules may be added here.
- `src/utils.py`: local copy of evaluator utilities and feasibility checker. Do not modify; the evaluation server overwrites it.
- `baseline/`: preserved official baseline package and archives. Do not modify.
- `instances/`: local example, generated, stress, tardiness, and training JSON instances. Treat large instance files as data; inspect metadata or slices before full reads.
- `tools/`: local runners, benchmarking, analysis, visualization, submission build, and Z1 diagnostic scripts.
- `tests/`: pytest smoke, feasibility, geometry, regime, parallel, and contract checks.
- `docs/`: official problem statements, extracted text, analysis, and this file map.
- `notes/`: research, strategy, experiment summaries, and HTML decision artifacts. Report generators are `notes/_z1_litpack.py`, `notes/_z1_html.py`, `notes/_z1_research_export.py`.
- `research/`: dedicated literature store. `research/z1-tardiness/` holds the 147-paper Z1→0 review (`z1-literature-2026-06-06.html`, `z1-tardiness-bibliography.md`, `z1-papers-data.json`).
- `results/` and `submissions/`: generated outputs. Read only targeted result files needed for the active question.

## Entrypoints

- Run one instance: `python tools/run_local.py <instance.json> --timelimit <seconds>`
- Isolated score run: `python tools/run_solver_once.py <instance.json> --solver our --timelimit <seconds>`
- Smoke tests: `python -m pytest tests/test_smoke.py -v`
- Full feasibility regression: `python -m pytest tests/test_feasibility.py -v`
- Build submission: `python tools/build_submission.py --tag <tag>`

## Current Task Units

### z1-recovery-strategy

Purpose: reduce total tardiness from 1000s toward two digits while preserving feasibility.

Workflow and allowed reads:

1. Local diagnosis: read `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/problem-analysis.md`, `tools/analyze_run.py`, `tools/resequence_gain.py`, `tools/validate_clean_decode.py`, `tools/z1_experiments.py`, targeted `notes/`, and focused slices of `src/myalgorithm.py`, `src/parallel_decode.py`, `src/regime.py`, `src/instrument.py`.
2. Official resource audit: read `README.md`, `OGC2026-대회개요.md`, `docs/problem-statement-v1.0.txt`, official competition pages, and official package metadata only.
3. Literature review (DONE 2026-06-06): 147-paper review in `research/z1-tardiness/` (`z1-literature-2026-06-06.html` + `z1-tardiness-bibliography.md` + `z1-papers-data.json`). Key result: crane j≥k = Blocking Job-Shop + Block-Relocation; 8 application insights with a Wave roadmap (Wave 1 = sequence↔timing split + exact O(n²) timing DP + ATC/Emmons seed, geometry-unchanged/objective-safe). Reuse before re-searching.
4. Strategy artifact: write `notes/z1-recovery-strategy-2026-06-06.html`; do not edit solver code unless the user asks for implementation in a later step.

Expand these reads only when a specific evidence gap blocks the next decision, then update this workflow.

### z1-objective-safe-implementation

Purpose: implement CRANE-safe Z1-reduction candidates without returning any solution whose official weighted objective is worse than the verified incumbent/baseline floor.

Workflow and allowed reads:

1. Candidate gate inspection: read focused slices of `src/myalgorithm.py`, `src/parallel_decode.py`, `tests/test_safe_foundation_contract.py`, and `tests/test_parallel_pickle.py`.
2. Implementation: edit only `src/myalgorithm.py` and, if process-level bay parallelism is needed, `src/parallel_decode.py`. Do not modify `src/utils.py` or `baseline/`.
3. Verification: run focused pytest contract/smoke tests plus `tools/run_solver_once.py` / `tools/run_compare_suite.py` on targeted training instances. Generated outputs should go under `results/`.
4. Handoff: report objective, Z1, Z2, Z3, feasibility, and wall time versus official baseline for each measured instance.

Expand these reads only when a specific failure or missing symbol requires it, then update this workflow.

## Do Not Touch

- Do not modify `src/utils.py`.
- Do not modify `baseline/`.
- Avoid broad rewrites of `src/myalgorithm.py` without a measured instance-level hypothesis and rollback-free patch scope.
- Avoid committing generated result churn from `results/` or `submissions/` unless explicitly requested.
