# Source Library — OGC 2026 solver (74 harvested 2026-06-14, ≥50 target met)

Rating: **direct** = runnable code/algo we can use; **adapt** = port needed; **ref** = ideas only.
Grouped by theme. The deep-research academic pass (rate-limited mid-verify) corroborates
the same directions (ATC dispatch, BRP/relocation, LBBD, packing-first) — treat its
claims as candidate-directions, not verified.

## A. Closest problem match — shipyard block spatial scheduling
- [S01] He, Hong, Kim 2024 "Quick & situ-aware spatiotemporal scheduling" J.Scheduling — **two-phase: P1 bay+time-window assign, P2 2D coords+rotation; min late+imbalance; KSOE-validated. CLOSEST = likely competitor method.** adapt — https://link.springer.com/article/10.1007/s10951-024-00804-1
- [S02] Kwon & Lee 2015 C&IE — bay-assign + 2D placement, overhead-crane HEIGHT constraint, bay workload balance (Z2). adapt — https://www.sciencedirect.com/science/article/abs/pii/S0360835215002296
- [S03] Park, Lee, Park, Kim 1996 C&IE (SNU) — seminal simultaneous schedule+2D-alloc, partial-enum + decomposition (assign-then-place). ref — https://snu.elsevierpure.com/en/publications/modeling-and-solving-the-spatial-block-scheduling-problem-in-a-sh
- [S04] Zhang & Chen 2012 IJPR — two-stage NMIP + **agglomerate time-space-close blocks into virtual super-blocks** before scheduling. adapt — https://www.tandfonline.com/doi/abs/10.1080/00207543.2011.588623
- [S05] Ge & Wang 2021 C&IE — MIP + block-priority GA for 2D irregular assign w/ due dates; 15°-multiple polygon simplification. ref — https://www.sciencedirect.com/science/article/abs/pii/S0360835220306550
- [S06] Xie et al. 2025 Eng.Opt — dynamic block reschedule + adaptive yard layout (BST+DRL), −56% interference moves. ref — https://www.tandfonline.com/doi/abs/10.1080/0305215X.2025.2466829
- [S07] Block-assignment matheuristic 2023 C&IE — two-stage region→shop assign, min workload-imbalance, −35% violation. adapt — https://www.sciencedirect.com/science/article/abs/pii/S0360835223006277
- [S08] Kim, Jeong, Shin 2020 — DRL block placement minimizing crane-obstruction rearrangement (j≥k analog). ref — https://www.researchgate.net/publication/340791490
- [S09] CP model industrial shipbuilding 2023 MDPI JMSE — Python+Gurobi/CPLEX FJSP+assembly, min makespan+tardiness vs erection due dates. adapt — https://www.mdpi.com/2077-1312/11/8/1517
- [S10] CP decomposition block assembly 2025 IJPR — CP beats exact MIP on industrial shipbuilding w/ due dates, buffer capacity, crane overhang. ref — https://www.tandfonline.com/doi/full/10.1080/00207543.2025.2503465

## B. Crane / blocking (j≥k) constraint + transferable analogs
- [S11] **wsgisler/job-shop-scheduling — DIRECT CP-SAT blocking-JS Python: blocking via `start_next==end_curr` + AddNoOverlap = "task holds resource until successor starts" = crane column-descent serialization.** direct — https://github.com/wsgisler/job-shop-scheduling
- [S12] Mascis & Pacciarelli 2002 EJOR — alternative-graph unifying blocking+no-wait JS; crane column = "machine", co-occupying blocks = disjunctive pair. ref — https://www.semanticscholar.org/paper/1c13d20a4f9bea46e92f4f95eeb9f5f480df90af
- [S13] **Luo CPAIOR 2022 "Packing by Scheduling" — convert 2D packing → CP scheduling (NoOverlap1D via cumulative); encode crane j≥k as disjunctive scheduling constraint; OOM memory savings vs MIP.** adapt — https://tidel.mie.utoronto.ca/pubs/Luo_CPAIOR22.pdf
- [S14] Aircraft-hangar exit-blocking MILP 2025 arXiv 2508.02640 — 2D place + entry/exit + exit-blocking (b blocks a's egress → temporal order); closest published analog to crane j≥k. adapt — https://arxiv.org/abs/2508.02640
- [S15] Aircraft hangar maintenance MILP 2019 AMM — 2D parking + schedule + rolling-in/out path blocking, big-M disjunctive. adapt — https://www.sciencedirect.com/science/article/pii/S0307904X18305353
- [S16] Mogali, Barbulescu, Smith 2021 EJOR — job-insertion polytope speeds blocking-JS local search (re-insert into vertical slot). adapt — https://www.sciencedirect.com/science/article/pii/S0377221721001648
- [S17] Lange & Werner 2018 J.Sched — 4 MIP formulations, resource held until successor starts (=crane j≥k); concrete var/constraint sets. adapt — https://ideas.repec.org/a/spr/jsched/v21y2018i2d10.1007_s10951-017-0526-0.html
- [S18] BJSSP GA 2026 MDPI Algorithms — feasibility-preserving (repair-free) chromosome by construction. adapt — https://www.mdpi.com/1999-4893/19/2/115
- [S19] Interrupting-swap BJSP GNN+RL 2023 arXiv 2302.02506 — dynamic disjunctive graph; swap maps to crane column reorder. ref — https://arxiv.org/abs/2302.02506
- [S20] jinboszu/ucrp-idbb — exact iter-deepening B&B unrestricted container relocation (upper blocks lower = j≥k); LB + dominance. adapt — https://github.com/jinboszu/ucrp-idbb
- [S21] jinboszu/rcrp-idbb — restricted CRP B&B w/ lexicographic dominance. adapt — https://github.com/jinboszu/rcrp-idbb
- [S22] jinboszu/crp-ip — Python+CPLEX IP models for stacking-order blocking. adapt — https://github.com/jinboszu/crp-ip
- [S23] jinboszu/remarshaling — Java+CPLEX MIP rearrange stacked containers w/ crane order. ref — https://github.com/jinboszu/remarshaling
- [S24] rubenlej/block-relocation-problem — Java reactive GRASP min crane working time. adapt — https://github.com/rubenlej/block-relocation-problem
- [S25] operagang/CRP_RL — Python DRL container retrieval w/ crane blocking, pretrained. ref — https://github.com/operagang/CRP_RL
- [S26] Lersteau & Shen 2022 C&IE — survey BRP/PMP exact+heuristic+RL, LB families + decompositions. ref — https://www.sciencedirect.com/science/article/abs/pii/S0360835222005381

## C. Crane scheduling (non-crossing = j≥k ordering)
- [S27] QCSP non-crossing+safety exact branch-and-price 2019 C&OR — j≥k = non-crossing constraint; portable formulation. adapt — https://www.sciencedirect.com/science/article/abs/pii/S0305054819300747
- [S28] JorikJooken/MCTSQuayCraneSchedulingNonCrossingConstraints — C++ MCTS, readable non-crossing feasibility check. adapt — https://github.com/JorikJooken/MCTSQuayCraneSchedulingNonCrossingConstraints
- [S29] Boysen, Briskorn, Meisel 2017 EJOR — crane interference classification, binary overtaking/position-order vars vocabulary. ref — https://doi.org/10.1016/j.ejor.2016.08.041
- [S30] Lim et al. 2004 NRL — non-crossing/neighborhood/separation crane MIP+DP+tabu (foundational). adapt — https://onlinelibrary.wiley.com/doi/abs/10.1002/nav.10123

## D. CP-SAT / OR-Tools / packing-as-scheduling code (DIRECT)
- [S31] **d-krupke/cpsat-primer — packing_with_rotations.py (rotation via bool swap w/h, x/y intervals, add_no_overlap_2d) + scheduling chapters.** direct — https://github.com/d-krupke/cpsat-primer
- [S32] google/or-tools scheduling.md — official interval/no_overlap/no_overlap_2d/cumulative/optional-interval reference. direct — https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md
- [S33] google/or-tools flexible_job_shop_sat.py — optional intervals + add_exactly_one for bay/machine assign + no_overlap per machine. direct — https://github.com/google/or-tools/blob/stable/examples/python/flexible_job_shop_sat.py
- [S34] PyJobShop — pip CP-SAT parallel-machine scheduling, weighted tardiness, release dates, setup. direct — https://github.com/PyJobShop/PyJobShop · paper arXiv 2502.13483
- [S35] eskinderit/2D-Strip-Packing-Problem — OR-Tools CP/LP + Z3 strip packing w/ rotation, symmetry-breaking. adapt — https://github.com/eskinderit/2D-Strip-Packing-Problem

## E. Exact MIP/CP for 2D irregular packing + LBBD
- [S36] **Optimal decomposition additive manuf. 2024 EJOR — LBBD jointly solving irregular 2D batch packing + machine schedule w/ release/processing/tardiness. STRUCTURALLY IDENTICAL to OGC.** adapt — https://www.sciencedirect.com/science/article/pii/S0377221724001784
- [S37] Branch-and-cut integrated AM planning 2023 arXiv 2308.09468 — combinatorial Benders: master schedule/assign, subproblem orthogonal-packing-w/-rotation feasibility. ref — https://arxiv.org/abs/2308.09468
- [S38] ktnr/BinPacking2D — Python Gurobi master + CP-SAT subproblem exact 2D packing, placement-point reductions, symmetry cuts. adapt — https://github.com/ktnr/BinPacking2D
- [S39] Dotted-Board Model 2013 IJPE (Toledo et al.) — discretize 1 dim → binary MIP for irregular placement; fits integer (x,y). adapt — https://www.sciencedirect.com/science/article/abs/pii/S0925527313001722
- [S40] Leao et al. 2016 IJPR — semi-continuous MIP (1 axis discrete, 1 continuous), fewer vars. ref — https://www.tandfonline.com/doi/full/10.1080/00207543.2015.1041571
- [S41] Lastra-Díaz & Ortuño 2022/24 EJOR (NFP-CM-VS) — SOTA exact MIP irregular strip packing, vertical-slice NFP + valid ineqs; Java code below. adapt — https://arxiv.org/abs/2206.00032
- [S42] RAMNEST V1R1 (Mendeley) — downloadable Java source for NFP-CM-VS MIP. adapt — https://data.mendeley.com/datasets/m8nzsk5c9v/1

## F. LBBD / branch-and-check (assign-master + schedule-subproblem)
- [S43] Hooker 2007 OR — canonical LBBD: MILP master assigns tasks→facilities, CP subproblem sequences each; no-good/optimality cut blueprint. ref — https://pubsonline.informs.org/doi/10.1287/opre.1060.0371
- [S44] Elci & Hooker 2022 IJOC (arXiv 2012.14074) — branch-and-check (cuts via lazy callback) orders of magnitude faster than outer LBBD; tardiness subproblem. ref — https://arxiv.org/abs/2012.14074
- [S45] Thorsteinsson 2001 CP — original branch-and-check (cuts at integer nodes via callbacks). ref — https://link.springer.com/chapter/10.1007/3-540-45578-7_2
- [S46] Li, Côté et al. 2022 IJOC — LBBD parallel-machine scheduling + LOCATION (=bay assign + sequence per bay); optimality cuts from subproblem dual. adapt — https://pubsonline.informs.org/doi/10.1287/ijoc.2021.1113
- [S47] Karlsson & Rönnberg 2022 C&OR — partial-assignment warm-start for stronger/faster LBBD cuts. adapt — https://www.sciencedirect.com/science/article/pii/S0305054822001769
- [S48] Avgerinos et al. 2024 EJOR (arXiv 2310.05893) — branch-and-check w/ local-branching Benders cut kills entire neighborhood; total-tardiness parallel machines. adapt — https://arxiv.org/abs/2310.05893
- [S49] RCPSP energy LBBD 2026 arXiv 2601.06542 — ILP master + CP subproblem (RCPSP ≈ crane j≥k), scales 1600 tasks. adapt — https://arxiv.org/abs/2601.06542
- [S50] mitchopt/Combining-Optimization-and-Simulation-LBBD — Python+Gurobi runnable master/subproblem loop, cut-gen pattern. adapt — https://github.com/mitchopt/Combining-Optimization-and-Simulation-Using-Logic-Based-Benders-Decomposition

## G. Metaheuristics (ALNS / ILS / SA) — Python code
- [S51] **N-Wouda/ALNS — DIRECT Python ALNS (632★, v7): custom destroy/repair + acceptance (SA, RecordToRecord, GreatDeluge, LateAcceptanceHillClimbing, MovingAvgThreshold...), roulette/MAB op-select.** direct — https://github.com/N-Wouda/ALNS
- [S52] ALNS RCPSP example — most_mobile/non_peak/segment removal + random_insert (job scheduling destroy ops). direct — https://github.com/N-Wouda/ALNS/blob/master/examples/resource_constrained_project_scheduling_problem.ipynb
- [S53] ALNS cutting-stock example — worst_removal (high-wastage) + minimal_wastage repair (1D assign). direct — https://alns.readthedocs.io/en/stable/examples/cutting_stock_problem.html
- [S54] ALNS CVRP example — Shaw string_removal (relatedness) 2.9% vs 9.2% random; remove temporally-clustered blocks. direct — https://alns.readthedocs.io/en/latest/examples/capacitated_vehicle_routing_problem.html
- [S55] Wouda & Lan 2023 JOSS — ALNS library reference paper. ref — https://doi.org/10.21105/joss.05028
- [S56] Ropke & Pisinger 2006 Transp.Sci — foundational ALNS: Shaw/worst/random removal + regret repair. ref — https://doi.org/10.1287/trsc.1050.0135
- [S57] Pisinger & Ropke 2010 (LNS handbook chapter) — all destroy/repair ops + destruction-degree/acceptance guidelines. ref — https://backend.orbit.dtu.dk/ws/files/5293785/Pisinger.pdf
- [S58] Martin-Iradi 2023 arXiv 2302.02356 — ALNS continuous berth allocation (assign ships→berth pos + entry/exit times); closest domain to bay-assign+timing. adapt — https://arxiv.org/abs/2302.02356
- [S59] Croce et al. 2012/18 (arXiv 1811.02882) — ILS + VLNS parallel-machine total tardiness; pairwise-interchange/dynasearch/machine-reassign neighborhoods. adapt — https://arxiv.org/abs/1811.02882
- [S60] ocatias/Metaheuristic-UPMS — C# SA+VLNS+MIP unrelated-parallel-machine total tardiness. adapt — https://github.com/ocatias/Metaheuristic-UPMS
- [S61] taylankabbani/Metaheuristic-Algorithms-for-SMTWTP — pure Python SA/tabu/local-search 1||ΣwjTj swap-neighborhood. direct — https://github.com/taylankabbani/Metaheuristic-Algorithms-for-SMTWTP
- [S62] Subramanian & Farias 2015 arXiv 1501.05882 — move-filtering to prune unpromising swaps in tardiness ILS. adapt — https://arxiv.org/abs/1501.05882

## H. Dispatch rules (ATC family) for weighted tardiness
- [S63] Vepsalainen & Morton 1987 Mgmt.Sci — **canonical ATC index wj/pj·exp(-slack/(κ·p̄))**; construction order by tardiness urgency. adapt — https://pubsonline.informs.org/doi/abs/10.1287/mnsc.33.8.1035
- [S64] Keshri, Gupta, Khanra 2025 C&OR — modified ATCR (fixed+variable tardiness) + adjacent pairwise interchange; maps to multi-component obj. adapt — https://dl.acm.org/doi/10.1016/j.cor.2025.107097

## I. Geometry / nesting engines (Python-callable)
- [S65] **spyrrow — pip Python binding to sparrow (SOTA nesting); Item/StripPackingInstance/solve()→(x,y,rotation).** direct — https://github.com/PaulDL-RS/spyrrow
- [S66] sparrow — SOTA 2D irregular strip-packing (Rust, MIT); collision-resolution loop. adapt — https://github.com/JeroenGar/sparrow
- [S67] jagua-rs — SOTA polygon collision-detection engine (Rust); exact feasibility oracle. adapt — https://github.com/JeroenGar/jagua-rs
- [S68] sparrow paper 2025 arXiv 2509.13329 — exploration+compression phases, benchmarks. ref — https://arxiv.org/abs/2509.13329
- [S69] liangxuCHEN/no_fit_polygon — pure-Python NFP+GA+BL placement (MIT, 64★). direct — https://github.com/liangxuCHEN/no_fit_polygon
- [S70] seanys/2D-Irregular-Packing-Algorithm — pure-Python NFP+SA+LP-compaction+cuckoo (158★). adapt — https://github.com/seanys/2D-Irregular-Packing-Algorithm
- [S71] libnest2d (+pynest2d) — C++ NFP packer w/ Python bindings (PrusaSlicer). adapt — https://github.com/tamasmeszaros/libnest2d
- [S72] Jack000/SVGnest — original NFP+GA nesting reference (JS). ref — https://github.com/Jack000/SVGnest

## J. Learning-augmented (defer — no GPU on eval server)
- [S73] GFPack++ 2024 ICCV (arXiv 2406.07579) — transformer gradient-field 2D irregular placement, fast inference. adapt(GPU) — https://github.com/TimHsue/GFPack-pp
- [S74] Luo CPAIOR "Packing by Scheduling" (dup of S13, listed for completeness).
