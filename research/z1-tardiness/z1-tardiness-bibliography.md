# OGC 2026 — Z1 (Tardiness) → 0 : Literature Bibliography

> 147 unique papers · 18 themes · collected via 18 parallel `haiku` web-researchers, synthesized by `opus` · 2026-06-06

Companion files in this folder:

- **`z1-literature-2026-06-06.html`** — full report with the 8 application insights, roadmap, and Method→our-code mapping (open in a browser).

- **`z1-papers-data.json`** — machine-readable source data (title/authors/venue/url/method/relevance).


**Core framing:** the crane vertical-access rule (j>=k) is structurally a *Blocking Job-Shop* (zero-buffer) + *Container Block-Relocation* (clear-above) constraint. Packing density is not the lever; crane serialization is. See the HTML report for the full insight write-up.


---


## 1. Shipyard Block Spatial Scheduling (SSP)  (10)

**1.** [A spatial scheduling system and its application to shipbuilding: DAS-CURVE](https://www.sciencedirect.com/science/article/abs/pii/0957417496000103) (1996)  
*K.J. Lee, J.K. Lee, S.Y. Choi · Expert Systems with Applications, Vol. 11, No. 2, pp. 311–324*  
- **Method:** Knowledge-based spatial scheduling system (Daewoo/KAIST) combining block arrangement, assignment, and scheduling algorithms for polygonal objects in rectangular workplaces, with due-date and workload-balance objectives.  
- **→ Z1 relevance:** Foundational formulation of bay-assignment + placement + scheduling as a unified problem; DAS-CURVE's block-arrangement and dispatch logic is the direct ancestor of OGC's phase-1/phase-2 structure.  

**2.** [Modeling and solving the spatial block scheduling problem in a shipbuilding company](https://snu.elsevierpure.com/en/publications/modeling-and-solving-the-spatial-block-scheduling-problem-in-a-sh) (1996)  
*Kyungchul Park, Kyungsik Lee, Sungsoo Park, Sunghwan Kim · Computers & Industrial Engineering, Vol. 30, No. 3, pp. 357–364. DOI: 10.1016/0360-8352(96)00004-6*  
- **Method:** Partial enumeration + decomposition for scheduling combined with a heuristic spatial-allocation procedure, treating simultaneous bay assignment and 2D placement as a coupled optimization.  
- **→ Z1 relevance:** First MIP-style formulation of SSP co-optimizing schedule and spatial layout; decomposition strategy directly applicable to OGC's (bay, position, time) decision coupling.  

**3.** [Heuristic and metaheuristic spatial planning of assembly blocks with process schedules in an assembly shop using differential evolution](https://www.tandfonline.com/doi/abs/10.1080/09537280802474941) (2008)  
*Supported by Daewoo Shipbuilding and Marine Engineering (DSME) · Production Planning & Control, Vol. 19, No. 6, pp. 605–615*  
- **Method:** Bottom-left-fill heuristic for placement combined with differential evolution metaheuristic to jointly optimize block sequencing order and orientations, formulated as combinatorial optimization.  
- **→ Z1 relevance:** DE-based joint optimization of block sequence and orientation is directly portable to OGC; orientation search + placement order is a key lever for crane-serialization reduction.  

**4.** [Spatial scheduling algorithm minimising makespan at block assembly shop in shipbuilding](https://www.tandfonline.com/doi/abs/10.1080/00207541003709536) (2011)  
*Junli Zheng, Zhibin Jiang, Qiang Chen et al. · International Journal of Production Research, Vol. 49, No. 8, pp. 2351–2371. DOI: 10.1080/00207541003709536*  
- **Method:** Greedy spatial scheduling algorithm with multiple placement strategies (largest contact area, bottom-left-fill variants) and block sequencing rules targeting makespan minimization on polygonal workplates.  
- **→ Z1 relevance:** Demonstrates that spatial placement policy (contact area maximization) directly affects how long blocks block each other; same logic governs OGC crane-access serialization duration.  

**5.** [Solving the spatial scheduling problem: a two-stage approach](https://www.semanticscholar.org/paper/Solving-the-spatial-scheduling-problem:-a-two-stage-Zhang-Chen/12435a0e8e7c305d541c5159d8e9699a624fd63b) (2012)  
*Zhiying Zhang, Jie Chen · International Journal of Production Research, Vol. 50, No. 10, pp. 2732–2743. DOI: 10.1080/00207543.2011.588623*  
- **Method:** Two-stage approach: agglomeration algorithm (AA) clusters spatiotemporally close blocks into virtual blocks (stage 1), then nonlinear MIP optimizes schedule and 2D placement jointly (stage 2).  
- **→ Z1 relevance:** Spatial-temporal clustering before scheduling reduces the combinatorial search; analogous to grouping OGC blocks by crane-access window to sequence exits without collision.  

**6.** [Spatial scheduling for large assembly blocks in shipbuilding](https://www.sciencedirect.com/science/article/abs/pii/S0360835215002296) (2015)  
*Byunghoon Kwon, Gyunghyun Lee (Lim) · Computers & Industrial Engineering, Vol. 89, pp. 203–212. DOI: 10.1016/j.cie.2015.02.009*  
- **Method:** MIP model solved by commercial solver; modifies bottom-left-fill into diagonal-fill (considers both bottom-left and top-right anchor points) to handle large irregularly-shaped blocks; minimizes total weighted tardiness.  
- **→ Z1 relevance:** Direct predecessor to OGC's formulation: MIP with tardiness objective + diagonal-fill placement for irregular blocks; shows commercial MIP is viable at shipyard scale (≤30 min).  

**7.** [Resource and time criticality based block spatial scheduling in a shipyard under uncertainty](https://www.tandfonline.com/doi/full/10.1080/00207543.2018.1424369) (2018)  
*Vijaya Dixit, Priyanka Verma, Piyush Raj, Mayank Sharma · International Journal of Production Research, Vol. 56, No. 22. DOI: 10.1080/00207543.2018.1424369*  
- **Method:** Priority-rule simulation combining time criticality index (TCI) and resource/space criticality index (RCI) under stochastic processing times; first to introduce spatial-resource criticality into BSS dispatch rules.  
- **→ Z1 relevance:** RCI-based dispatching directly models bay-congestion priority; tells OGC which blocks to move first when crane access bottlenecks appear, reducing expected tardiness under uncertainty.  

**8.** [Spatial scheduling for irregularly shaped blocks in shipbuilding](https://www.sciencedirect.com/science/article/abs/pii/S0360835220306550) (2021)  
*Yan Ge, Aimin Wang · Computers & Industrial Engineering, Vol. 152, Feb 2021. DOI: 10.1016/j.cie.2020.106985*  
- **Method:** MIP model for irregular-polygon blocks using standard-angle filling (angles rounded to 15° multiples) to approximate polygon packing as near-rectangular, jointly minimizing delay and maximizing workspace utilization.  
- **→ Z1 relevance:** Standard-angle polygon simplification reduces OGC's irregular-shape non-overlap complexity; the MIP delay-minimization structure is directly applicable to Z1 (total tardiness) reduction.  

**9.** [Spatial arrangement using deep reinforcement learning to minimise rearrangement in ship block stockyards](https://www.tandfonline.com/doi/full/10.1080/00207543.2020.1748247) (2020)  
*Byeongseop Kim, Yongkuk Jeong, Jong Gye Shin · International Journal of Production Research, Vol. 59. DOI: 10.1080/00207543.2020.1748247*  
- **Method:** Multi-agent deep reinforcement learning with separate DQN-based policies for block arrival placement and rearrangement; reward shaped to minimize unnecessary block moves in stockyard.  
- **→ Z1 relevance:** DRL placement policy that minimizes future blocking/relocation directly addresses OGC's crane-access serialization: learned policy can pre-position blocks to minimize j>=k conflicts.  

**10.** [Quick and situ-aware spatiotemporal scheduling for shipbuilding manufacturing](https://link.springer.com/article/10.1007/s10951-024-00804-1) (2024)  
*Junying He, Soon-Ik Hong, Seong-Hee Kim · Journal of Scheduling. DOI: 10.1007/s10951-024-00804-1*  
- **Method:** Two-phase algorithm: phase 1 assigns bay and processing-start-date (scheduling), phase 2 determines exact (x,y) coordinates and rotation within bay (placement); validated on KSOE industrial datasets targeting tardiness and workload fairness.  
- **→ Z1 relevance:** Most recent direct analog to OGC's problem (bay assignment + placement + tardiness + workload balance); phase-1/phase-2 decomposition and KSOE validation make it directly portable.  


## 2. Shipbuilding Block Stockyard & Stacking  (6)

**11.** [Integrated dynamic scheduling of shipyard blocks considering adaptive adjustment in stockyard layout](https://www.tandfonline.com/doi/full/10.1080/0305215X.2025.2466829) (2025)  
*Meijing Zhong, Chunjin Li, Yuan Hu, Chao Kang, Zan Liu, Jian Guo, Yang Xie · Engineering Optimization (online first, DOI 10.1080/0305215X.2025.2466829)*  
- **Method:** Binary-search-tree heap-field layout + DRL integrated scheduler; reduces interference block moves 56% over baseline.  
- **→ Z1 relevance:** Combines layout adaptation with scheduling to cut interference-move counts — directly analogous to reducing crane-blocking that serializes our bay entries/exits.  

**12.** [Spatial Scheduling Optimization Algorithm for Block Assembly in Shipbuilding](https://doi.org/10.1155/2017/1923646) (2017)  
*Zhengyang Shang, Jinan Gu, Wei Ding, Enock Andrews Duodu · Mathematical Problems in Engineering, Article ID 1923646*  
- **Method:** Best-contact algorithm (BCA) + genetic algorithm jointly optimize block sequence and start times to minimize makespan.  
- **→ Z1 relevance:** GA-based joint sequence+timing search is portable to OGC's combined bay-assignment+ENTRY/EXIT scheduling to pull tardiness toward zero.  

**13.** [A stack-based retrieval method for the steel plate yard retrieval problem in shipbuilding](https://doi.org/10.1007/s10696-023-09490-1) (2024)  
*Lebao Wu, Zuhua Jiang, Xinyu Li · Flexible Services and Manufacturing Journal, 36(1)*  
- **Method:** IP model + heuristic that sequences retrieval stacks and preferentially relocates blocking plates to target-free stacks to minimize relocation count.  
- **→ Z1 relevance:** Relocation-minimization logic for stacked storage directly models the crane vertical-access (j≥k) serialization; fewer relocations = shorter crane queues = less tardiness.  

**14.** [Yard Crane Scheduling for container storage, retrieval, and relocation](https://doi.org/10.1016/j.ejor.2018.05.007) (2018)  
*Virgile Galle, Cynthia Barnhart, Patrick Jaillet · European Journal of Operational Research, 271(1), 288–316*  
- **Method:** Integer program jointly scheduling crane moves for storage, retrieval, and relocation; local-search heuristic optimizes future relocation cost at time of storage.  
- **→ Z1 relevance:** Anticipatory storage placement to cut future crane blocking time directly translates to choosing OGC ENTRY positions that minimize downstream crane-serialization tardiness.  

**15.** [The Block Retrieval Problem](https://doi.org/10.1016/j.ejor.2017.08.048) (2018)  
*Marcos de Melo da Silva, Güneş Erdoğan, Maria Battarra, Vitaly Strusevich · European Journal of Operational Research, 265(3), 931–950*  
- **Method:** NP-hardness proofs, branch-and-bound, and heuristics for retrieving stacked items in a prescribed departure order with minimum relocations.  
- **→ Z1 relevance:** Establishes complexity of crane-access-blocked retrieval sequencing; lower-bound and B&B insights apply to OGC EXIT scheduling under the j≥k crane constraint.  

**16.** [Optimising outbound scheduling in shipyard steel stockyard](https://doi.org/10.1080/17445302.2024.2400492) (2024)  
*Jinghua Li, Ming He, Lei Zhou, Dening Song, Boxin Yang · Ships and Offshore Structures (online first, DOI 10.1080/17445302.2024.2400492)*  
- **Method:** Outbound scheduling model solved by improved ant colony optimization (ECS-IACO) with dynamic pheromone matrix, minimizing energy and delay.  
- **→ Z1 relevance:** Due-date-driven outbound sequencing from a stacked yard — the retrieval ordering insight reduces crane-queue buildup that is OGC's primary tardiness driver.  


## 3. Crane Scheduling — Non-Crossing / Interference  (9)

**17.** [A generalized classification scheme for crane scheduling with interference](https://doi.org/10.1016/j.ejor.2016.08.041) (2017)  
*Nils Boysen, Dirk Briskorn, Frank Meisel · European Journal of Operational Research, Vol. 258(1), pp. 343–357*  
- **Method:** Taxonomy/classification framework unifying non-crossing, safety-distance, and interference constraints across ports, rail terminals, and warehouses; surveys complexity results.  
- **→ Z1 relevance:** Provides canonical vocabulary and problem decomposition for modeling our crane j≥k serialization constraint as a non-crossing scheduling sub-problem.  

**18.** [Scheduling Multiple Yard Cranes with Crane Interference and Safety Distance Requirement](https://doi.org/10.1287/trsc.2015.0641) (2015)  
*Yong Wu, Wenkai Li, Matthew E. H. Petering, Mark Goh, Robert de Souza · Transportation Science, Vol. 49(4)*  
- **Method:** O(n³) clustering-reassigning heuristic enforcing non-crossing + safety distance; benchmarked against MILP, near-optimal in real-time.  
- **→ Z1 relevance:** Direct template for serializing crane moves under interference: convert our j≥k access constraint into a safety-distance scheduling layer to cut waiting-induced tardiness.  

**19.** [Sequencing Two Cooperating Automated Stacking Cranes in a Container Terminal](https://doi.org/10.1287/trsc.1090.0298) (2010)  
*Iris F. A. Vis, Hector J. Carlo · Transportation Science, Vol. 44(4)*  
- **Method:** Mathematical model for two non-crossing cranes sharing one block; lower-bound algorithm + simulated-annealing heuristic within 2% of lower bound.  
- **→ Z1 relevance:** Seminal 2-crane non-crossing formulation directly analogous to our single-bay two-layer crane access problem; SA heuristic is portable to our time-limited solver.  

**20.** [Scheduling Twin Yard Cranes in a Container Block](https://doi.org/10.1287/trsc.2014.0533) (2015)  
*Boysen, Nils; Briskorn, Dirk; Meisel, Frank · Transportation Science, Vol. 49(3)*  
- **Method:** Models twin ASC problem as multiple asymmetric generalized TSP with precedence constraints; solved with adaptive large neighborhood search (ALNS) for makespan minimization.  
- **→ Z1 relevance:** ALNS framework for non-crossing twin-crane sequencing is directly portable; precedence-constraint encoding maps onto our vertical-access (j≥k) ordering requirement.  

**21.** [Twin-crane scheduling during seaside workload peaks with a dedicated handshake area](https://doi.org/10.1007/s10951-021-00710-w) (2022)  
*Lennart Zey, Dirk Briskorn, Nils Boysen · Journal of Scheduling, Vol. 25(1), pp. 3–34*  
- **Method:** Exact procedures for non-crossing twin-crane coordination using a handshake staging area; precedence constraints from stacked containers in transfer zone; makespan objective.  
- **→ Z1 relevance:** Handshake zone is analogous to our intermediate staging tactic: parking blocks in a neutral layer so crane j-access is unblocked, directly reducing serialization delays.  

**22.** [An exact solution approach for scheduling cooperative gantry cranes](https://doi.org/10.1016/j.ejor.2018.07.043) (2019)  
*Dominik Kress, Jan Dornseifer, Florian Jaehn · European Journal of Operational Research, Vol. 273(1), pp. 82–101*  
- **Method:** Dynamic programming with dominance/bounding for two gantry cranes sharing rails; beam-search heuristic for online use; non-crossing + time-window constraints; minimizes makespan.  
- **→ Z1 relevance:** DP with dominance properties can enumerate crane-access sequences under j≥k constraint efficiently; beam-search variant fits our 4-CPU wall-clock budget.  

**23.** [A Benders decomposition-based framework for solving quay crane scheduling problems](https://doi.org/10.1016/j.ejor.2018.08.009) (2019)  
*Defeng Sun, Lixin Tang, Roberto Baldacci · European Journal of Operational Research, Vol. 273(2), pp. 504–515*  
- **Method:** Logic-based Benders decomposition: master problem assigns workloads respecting non-crossing; slave subproblems sequence operations per crane; logic cuts enforce feasibility.  
- **→ Z1 relevance:** Decomposition separates our bay-assignment (which determines crane-access order) from block-sequencing; master-slave structure controls the j≥k serialization bottleneck explicitly.  

**24.** [Crane scheduling problem with non-interference constraints in a steel coil distribution centre](https://doi.org/10.1080/00207543.2016.1193249) (2017)  
*Gabriela N. Maschietto, Yassine Ouazene, Martín G. Ravetti, Maurício C. de Souza, Farouk Yalaoui · International Journal of Production Research, Vol. 55(6), pp. 1607–1622*  
- **Method:** Two-crane parallel-machine scheduling with non-interference; MILP for small instances; genetic algorithm achieving near-optimal gaps of 2–10% on real warehouse instances.  
- **→ Z1 relevance:** Steel-coil warehouse is structurally identical to shipyard bay: two cranes on shared rail, blocking, real due dates — GA with non-interference encoding directly applicable.  

**25.** [Advances in multi-crane scheduling: Extended non-interference modeling and temporal-constraint-based valid inequalities](https://doi.org/10.1016/j.ejor.2025.10.032) (2025)  
*Woo-Jin Shin, Hyun-Jung Kim · European Journal of Operational Research, Vol. 331(1), pp. 35–47*  
- **Method:** Generalized closed-form Extended Temporal Distance (ETD) model for N cranes transporting across multiple track locations; MILP + valid inequalities from network analysis; minimizes total flow time.  
- **→ Z1 relevance:** ETD model handles multi-location crane moves (enter/exit at different bay positions) — exactly our block ENTRY/EXIT timing model — providing tighter interference bounds to cut tardiness.  


## 4. Container Pre-Marshalling & Block Relocation (j>=k analog)  (10)

**26.** [Solving the Pre-Marshalling Problem to Optimality with A* and IDA*](https://link.springer.com/article/10.1007/s10696-016-9246-6) (2016)  
*Silke Boge, Marc Goerigk, Sigrid Knust · Flexible Services and Manufacturing Journal (Springer), published online 2016*  
- **Method:** A* and IDA* search with novel branching and symmetry-breaking rules to solve pre-marshalling (clear-above-before-access) to proven optimality.  
- **→ Z1 relevance:** Directly models the j>=k vertical-access rule as a must-clear-above constraint; A*/IDA* framework ports to deciding which crane-blocked bay slot to clear first to free tardy blocks.  

**27.** [Integer Programming Models for the Pre-Marshalling Problem](https://ideas.repec.org/a/eee/ejores/v274y2019i1p142-154.html) (2019)  
*Consuelo Parreño-Torres, Ramon Alvarez-Valdes, Rubén Ruiz · European Journal of Operational Research, Vol. 274(1), pp. 142-154*  
- **Method:** Two families of ILP formulations plus an iterative solution procedure that avoids needing a hard-to-obtain upper bound, solved with CPLEX.  
- **→ Z1 relevance:** ILP formulation of must-clear-above ordering can be embedded as a subproblem to enumerate minimum-relocation move sequences that unblock tardy items.  

**28.** [A New Effective Unified Model for Solving the Pre-Marshalling and Block Relocation Problems](https://ideas.repec.org/a/eee/ejores/v271y2018i1p40-56.html) (2018)  
*Marcos de Melo da Silva, Sophie Toulouse, Roberto Wolfler Calvo · European Journal of Operational Research, Vol. 271(1), pp. 40-56*  
- **Method:** Single unified ILP formulation covering PMP, BRP, and restricted-BRP variants simultaneously, benchmarked against state-of-the-art branch-and-bound.  
- **→ Z1 relevance:** Unifying pre-marshalling and relocation in one model mirrors our combined problem: a single formulation could co-optimize crane-clearance moves and block scheduling to cut tardiness.  

**29.** [An Exact Algorithm for the Unrestricted Block Relocation Problem](https://www.sciencedirect.com/science/article/abs/pii/S0305054818300583) (2018)  
*Shunji Tanaka, Fumitaka Mizuno · Computers & Operations Research, Vol. 95, pp. 12-31*  
- **Method:** Branch-and-bound with new lower bounds and dominance properties for the unrestricted BRP (any blocking container may be relocated), achieving optimality on large benchmarks.  
- **→ Z1 relevance:** Tight lower bounds and dominance rules for clearing blocking items directly translate to bounding how many crane-access violations must be resolved before a tardy block's EXIT time.  

**30.** [An Exact Algorithm for the Unrestricted Container Relocation Problem with New Lower Bounds and Dominance Rules](https://ideas.repec.org/a/eee/ejores/v304y2023i2p494-514.html) (2023)  
*Bo Jin, Shunji Tanaka · European Journal of Operational Research, Vol. 304(2), pp. 494-514*  
- **Method:** Iterative-deepening branch-and-bound (IDBB) with two new polynomial-time lower bounds and mutually consistent dominance rules for the unrestricted container relocation problem.  
- **→ Z1 relevance:** State-of-the-art exact BRP solver; lower bounds on relocations give a floor on unavoidable crane-serialization delay, enabling better EXIT-time estimates to reduce Z1.  

**31.** [The Bounded Beam Search Algorithm for the Block Relocation Problem](https://arxiv.org/abs/2206.12303) (2022)  
*Tiziano Bacci, Sara Mattia, Paolo Ventura · arXiv:2206.12303 (extended from Computers & Operations Research, Vol. 103, 2019)*  
- **Method:** Polynomial-time lower bound embedded in a bounded beam search, limiting enumeration with heuristic pruning criteria; outperforms prior heuristics on standard BRP benchmarks.  
- **→ Z1 relevance:** Beam search with crane-blocking lower bound can guide fast feasible sequencing of block entries/exits under j>=k, keeping schedule within time limits on the 4-CPU eval server.  

**32.** [Deep Learning Assisted Heuristic Tree Search for the Container Pre-Marshalling Problem](https://arxiv.org/abs/1709.09972) (2020)  
*André Hottung, Shunji Tanaka, Kevin Tierney · Computers & Operations Research, Vol. 113 (2020)*  
- **Method:** Neural networks trained on near-optimal solutions learn branching heuristics and admissible lower bounds; integrated into DLTS tree search achieving <2% optimality gap on real instances.  
- **→ Z1 relevance:** Learned lower bound on clearance moves can approximate crane-serialization cost within our scheduling loop; branching policy trained offline is CPU-only and fits eval-server constraints.  

**33.** [Minimizing Crane Times in Pre-Marshalling Problems](https://ideas.repec.org/a/eee/transe/v137y2020ics1366554519311949.html) (2020)  
*Consuelo Parreño-Torres, Ramon Alvarez-Valdes, Rubén Ruiz, Kevin Tierney · Transportation Research Part E: Logistics and Transportation Review, Vol. 137, article 101917*  
- **Method:** ILP model plus iterative-deepening branch-and-bound minimizing actual crane time (not move count) in pre-marshalling, with new upper/lower bounds and dominance criteria.  
- **→ Z1 relevance:** Optimizing crane time rather than move count matches our tardiness objective: bounding crane-clearance duration tightens EXIT-time windows and directly reduces Z1.  

**34.** [The Container Premarshalling Problem under Limited Crane Time: A Constraint Programming Approach](https://dl.acm.org/doi/10.1016/j.cor.2024.106635) (2024)  
*Celia Jiménez-Piqueras, Consuelo Parreño-Torres, Ramon Alvarez-Valdes, Rubén Ruiz · Computers & Operations Research, Vol. 166, article 106635*  
- **Method:** CP model for CPMP-LCT (premarshalling when full bay rearrangement is infeasible within a crane time budget); CP outperforms ILP on partial-rearrangement instances.  
- **→ Z1 relevance:** Partial-clearance under time budget is exactly our situation: crane time is shared, so this CP approach selects which j>=k violations to fix within the scheduling window to minimize tardiness.  

**35.** [A Study on the Block Relocation Problem: Lower Bound Derivations and Strong Formulations](https://arxiv.org/abs/1904.03347) (2019)  
*Chao Lu, Bo Zeng, Shixin Liu · arXiv:1904.03347*  
- **Method:** General lower-bound framework using critical substructures; strong MIP formulation covering 8 BRP variants; iterative exact procedure benchmarked across all variants.  
- **→ Z1 relevance:** Comprehensive lower-bound taxonomy for all BRP variants provides tight dual bounds on crane-blocking delay, enabling provably good EXIT-time assignments that minimize tardiness.  


## 5. Single-Machine Total / Weighted Tardiness  (9)

**36.** [One-Machine Sequencing to Minimize Certain Functions of Job Tardiness](https://ideas.repec.org/a/inm/oropre/v17y1969i4p701-715.html) (1969)  
*H. Emmons · Operations Research, 17(4):701–715*  
- **Method:** Three pairwise job-ordering dominance theorems that fix precedence between job pairs, pruning the search space for any exact 1||ΣT_j solver.  
- **→ Z1 relevance:** Emmons' dominance rules let us immediately fix order of many block-pairs without search, shrinking the crane-serialization scheduling space.  

**37.** [A 'Pseudopolynomial' Algorithm for Sequencing Jobs to Minimize Total Tardiness](https://www.sciencedirect.com/science/article/pii/S0167506008707428) (1977)  
*E. L. Lawler · Annals of Discrete Mathematics, 1:331–342*  
- **Method:** DP decomposition: select job with max processing time, enumerate its position after EDD position; recursion reduces to independent subproblems; O(n²P) time.  
- **→ Z1 relevance:** Lawler's decomposition is the canonical exact DP for 1||ΣT_j; directly computes optimal entry/exit sequence for crane-serialized blocks within a bay.  

**38.** [A Branch and Bound Algorithm for the Total Weighted Tardiness Problem](https://pubsonline.informs.org/doi/10.1287/opre.33.2.363) (1985)  
*C. N. Potts, L. N. Van Wassenhove · Operations Research, 33(2):363–377*  
- **Method:** B&B with Lagrangian relaxation lower bounds (subproblem = 1||ΣwC_j), fast multiplier-adjustment instead of subgradient, plus DP-dominance pruning in the tree.  
- **→ Z1 relevance:** Solves 1||ΣwT_j exactly up to ~50 jobs; directly applicable to scheduling crane-access slots for weighted-priority blocks per bay.  

**39.** [Priority Rules for Job Shop Scheduling: Making More Efficient Use of the Flexibility of Soft Due-Dates (ATC rule)](https://www.semanticscholar.org/paper/Priority-Rules-for-Job-Shops-with-Weighted-Tardiness-Vepsalainen-Morton/6e6eb8df4cd3c2b994fc8823bade0e8a28bab32a) (1987)  
*A.-P. J. Vepsalainen, T. E. Morton · Management Science, 33(8):1035–1047*  
- **Method:** ATC index = (w_j/p_j)·exp(-max(d_j-p_j-t,0)/(k·p̄)), a look-ahead priority rule that blends WSPT urgency with exponential due-date slack penalisation.  
- **→ Z1 relevance:** ATC is a fast O(n log n) construction heuristic for weighted tardiness; use it to build the initial block-release ordering before any crane-aware refinement.  

**40.** [Local Search Heuristics for the Single Machine Total Weighted Tardiness Scheduling Problem](https://pubsonline.informs.org/doi/10.1287/ijoc.10.3.341) (1998)  
*H. A. J. Crauwels, C. N. Potts, L. N. Van Wassenhove · INFORMS Journal on Computing, 10(3):341–350*  
- **Method:** Comparative study of descent, simulated annealing, threshold accepting, tabu search, and genetic algorithms on 1||ΣwT_j using a binary encoding plus decoding heuristic.  
- **→ Z1 relevance:** Establishes benchmark local-search operators (swap, insert) and their performance profiles; template for crane-aware neighborhood moves on the block sequence.  

**41.** [An Iterated Dynasearch Algorithm for the Single-Machine Total Weighted Tardiness Scheduling Problem](https://pubsonline.informs.org/doi/abs/10.1287/ijoc.14.1.52.7712) (2002)  
*R. K. Congram, C. N. Potts, S. L. van de Velde · INFORMS Journal on Computing, 14(1):52–67*  
- **Method:** Dynasearch: DP over an exponential-size 'compound move' neighborhood (all sequences of non-overlapping adjacent swaps) in polynomial time, iterated with perturbation.  
- **→ Z1 relevance:** Searches vastly more of the permutation space per iteration than simple swap; can efficiently explore crane-serialisation reorderings that standard 2-opt misses.  

**42.** [The Single-Machine Total Tardiness Scheduling Problem: Review and Extensions](https://ideas.repec.org/a/eee/ejores/v202y2010i1p1-7.html) (2010)  
*C. Koulamas · European Journal of Operational Research, 202(1):1–7*  
- **Method:** Survey of exact algorithms, FPTAS, and heuristics for 1||ΣT_j; extensions cover release dates, sequence-dependent setups, and generalised due-date models.  
- **→ Z1 relevance:** Road-map for choosing the right algorithm tier (exact vs. heuristic) as bay sizes and time limits vary in the shipyard problem.  

**43.** [Data-driven Algorithm for Scheduling with Total Tardiness](https://arxiv.org/abs/2005.05579) (2020)  
*M. Bouška, A. Novák, P. Šůcha, I. Módos, Z. Hanzálek · arXiv:2005.05579 (also EJOR 308(3):990–1006, 2023)*  
- **Method:** Deep neural network trained on optimal solutions acts as a polynomial-time criterion estimator inside Lawler's decomposition, replacing the exhaustive DP split search.  
- **→ Z1 relevance:** Achieves ~0.5% optimality gap on instances up to 350 jobs in milliseconds; can be trained on solved crane-schedule subproblems to guide fast online sequencing.  

**44.** [Deep Learning-Driven Scheduling Algorithm for a Single Machine Problem Minimizing the Total Tardiness](https://arxiv.org/abs/2402.14847) (2024)  
*M. Bouška, P. Šůcha · arXiv:2402.14847 (extended EJOR version)*  
- **Method:** Improved DNN estimator within Lawler's DP decomposition with faster dataset generation; reduces optimality gap further and scales to larger instances.  
- **→ Z1 relevance:** Directly portable: train on crane-serialised single-bay scheduling instances to get a near-optimal sequencer that respects release/due-date structure.  


## 6. Parallel-Machine Total Weighted Tardiness  (8)

**45.** [Priority Rules for Job Shops with Weighted Tardiness Costs](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.33.8.1035) (1987)  
*A.P.J. Vepsalainen, T.E. Morton · Management Science, 33(8), pp. 1035–1047*  
- **Method:** ATC (Apparent Tardiness Cost) composite dispatching rule blending WSPT and slack for weighted tardiness.  
- **→ Z1 relevance:** ATC/ATCS applied per bay as a fast assignment/sequencing priority gives an O(n log n) greedy that minimises tardy wait time in the crane-serialisation queue.  

**46.** [Dominance Rules for the Parallel Machine Total Weighted Tardiness Scheduling Problem with Release Dates](https://www.semanticscholar.org/paper/Dominance-rules-for-the-parallel-machine-total-with-Jouglet-Savourey/f4cdb4010a9a050986197aab4c5187ddc79dd71c) (2011)  
*A. Jouglet, D. Savourey · Computers & Operations Research, 38(5), pp. 1259–1266*  
- **Method:** Dominance/dominance-filtering rules adapted from single-machine literature to prune infeasible or suboptimal job-machine assignments with release dates.  
- **→ Z1 relevance:** Pruning rules eliminate orderings that cannot reduce Z1, directly cutting the crane-serialisation search space during bay-assignment decisions.  

**47.** [Branch-and-Bound Algorithm for Total Weighted Tardiness Minimization on Parallel Machines under Release Dates Assumptions](https://doi.org/10.1051/ro/2012010) (2012)  
*I. Kacem, N. Souayah, M. Haouari · RAIRO – Operations Research, 46(2), pp. 125–147*  
- **Method:** Branch-and-bound with novel lower/upper bounds for Pm|r_j|sum w_j T_j; solves instances up to 50 jobs × 4 machines.  
- **→ Z1 relevance:** Provides exact lower-bound framework applicable per-bay; lower-bound values can seed metaheuristic improvement for Z1 reduction.  

**48.** [Exact Algorithm over an Arc-Time-Indexed Formulation for Parallel Machine Scheduling Problems](https://link.springer.com/article/10.1007/s12532-010-0019-z) (2010)  
*A. Pessoa, E. Uchoa, M.P. de Aragão, R. Rodrigues · Mathematical Programming Computation, 2(3–4), pp. 259–290*  
- **Method:** Branch-cut-and-price over arc-time-indexed formulation (variable per job-pair × completion-time), first to solve P||sum w_j T_j up to 100 jobs optimally.  
- **→ Z1 relevance:** Arc-time formulation can model bay-level crane-serialisation constraints as precedence arcs, enabling MIP-exact Z1 minimisation for small instances.  

**49.** [Iterated Local Search and Very Large Neighborhoods for the Parallel-Machines Total Tardiness Problem](https://arxiv.org/abs/1811.02882) (2012)  
*F. Della Croce, T. Garaix, A. Grosso · Computers & Operations Research, 39(6), pp. 1213–1217*  
- **Method:** ILS combining generalised pairwise-interchange, dynasearch (polynomial-time exhaustive over chained swaps), and machine-reassignment neighbourhood.  
- **→ Z1 relevance:** Dynasearch explores chained-move neighbourhoods; applying it within each bay's schedule can rapidly reduce Z1 by escaping crane-induced local optima.  

**50.** [Parallel Machine Total Tardiness Scheduling with a New Hybrid Metaheuristic Approach](https://www.sciencedirect.com/science/article/abs/pii/S0305054806000463) (2007)  
*D. Anghinolfi, M. Paolucci · Computers & Operations Research, 34(11), pp. 3471–3490*  
- **Method:** Hybrid particle-swarm / clonal-selection metaheuristic for Pm||sum T_j, encoding schedules as priority permutations decoded by ATC dispatching.  
- **→ Z1 relevance:** Permutation-encoded population search avoids exhaustive enumeration; directly portable to the bay-assignment + ENTRY/EXIT time optimisation loop.  

**51.** [Analysis of Variable Neighborhood Descent as a Local Search Operator for Total Weighted Tardiness Problem on Unrelated Parallel Machines](https://www.sciencedirect.com/science/article/pii/S0305054820300034) (2020)  
*R.O.M. Diana, S.R. de Souza · Computers & Operations Research, 117, art. 104886*  
- **Method:** VND with multiple neighbourhood structures (insertion, swap, machine-reassignment) embedded into IG, ABC, and GA as local-search operator for R||sum w_j T_j.  
- **→ Z1 relevance:** VND systematically exploits multiple move types; embedding it inside bay-level improvement loops can reduce Z1 by reordering crane-access queues.  

**52.** [Iterated Greedy Algorithms for a Complex Parallel Machine Scheduling Problem](https://www.sciencedirect.com/science/article/abs/pii/S037722172100672X) (2022)  
*D. Mecler, V. Abu-Marrul, R. Martinelli, A. Hoff · European Journal of Operational Research, 300(2), pp. 545–560*  
- **Method:** Iterated Greedy destroy-and-repair with Random VND local search for parallel machines with release dates, family setups, and machine eligibility.  
- **→ Z1 relevance:** Destroy-and-repair on bay assignments resets crane-blocking configurations; re-inserting blocks by earliest-release/latest-due order directly targets Z1.  


## 7. RCPSP with Spatial / 2D Resources  (5)

**53.** [Packing Problems and Project Scheduling Models: An Integrating Perspective](https://www.researchgate.net/publication/245280867_Packing_Problems_and_Project_Scheduling_Models_An_Integrating_Perspective) (2000)  
*Sönke Hartmann · Journal of the Operational Research Society, Vol. 51, pp. 1083–1092*  
- **Method:** Unifying classification showing every packing problem is a special case of RCPSP; enables cross-pollination of solvers  
- **→ Z1 relevance:** Provides theoretical bridge: OGC 2D polygon packing per bay is an sRCPSP instance, so RCPSP priority-rule technology directly transfers  

**54.** [A Branch and Bound Algorithm for Project Scheduling Problem with Spatial Resource Constraints](https://doi.org/10.1155/2015/628259) (2015)  
*Hu et al. · Mathematical Problems in Engineering (Hindawi), Article 628259*  
- **Method:** Branch-and-bound with implicit enumeration scheme + precedence-based lower bound + dominance pruning for 2D spatial RCPSP  
- **→ Z1 relevance:** First exact B&B for 2D sRCPSP in shipbuilding context; dominance rules could tighten our crane-serialization ordering search space  

**55.** [A three-dimensional spatial resource-constrained project scheduling problem: Model and heuristic](https://doi.org/10.1016/j.ejor.2024.07.018) (2024)  
*Jingwen Zhang, Lubo Li, Erik Demeulemeester, Haohua Zhang · European Journal of Operational Research, Vol. 319, No. 3, pp. 943–966*  
- **Method:** IP formulation of 3D sRCPSP + heuristic with 36 priority rules (11 new spatial-feature rules) + 3 spatial allocation strategies + decision-tree rule selector  
- **→ Z1 relevance:** 3D spatial resource = our bay-layer structure; new spatial priority rules (e.g. volumetric urgency) can be adapted to encode crane-access clearance as a priority signal  

**56.** [A Q-learning based hyper-heuristic scheduling algorithm with multi-rule selection for sub-assembly in shipbuilding](https://www.sciencedirect.com/science/article/abs/pii/S0360835224006880) (2024)  
*Authors from ScienceDirect (2024) · Computers & Industrial Engineering (September 2024), Article S0360835224006880*  
- **Method:** Q-learning agent selects among multiple spatial layout heuristics (low-level) and sequencing rules online; minimises makespan under space + worker resources  
- **→ Z1 relevance:** Adaptive rule selection learns which crane-compatible placement heuristic to invoke per block, replacing our static greedy and potentially cutting crane-wait tardiness  

**57.** [Solving the parallel processor scheduling and bin packing problems with contiguity constraints: Mathematical models and computational studies](https://www.sciencedirect.com/science/article/pii/S0377221724007161) (2024)  
*Researchers at Tilburg University · European Journal of Operational Research (2024)*  
- **Method:** MILP with contiguity constraints coupling bin-packing assignment with parallel-machine scheduling; exact decomposition via LP relaxation + column generation  
- **→ Z1 relevance:** Contiguity = our crane-access vertical-clearance rule; decomposition approach decouples bay assignment from position so crane constraint can be imposed as a cut  


## 8. Temporal / Dynamic 2D Bin Packing with Due Dates  (11)

**58.** [A Genetic Algorithm for Two-Dimensional Bin Packing with Due Dates](https://www.semanticscholar.org/paper/A-genetic-algorithm-for-two-dimensional-bin-packing-Bennell-Lee/28f53e1528d848f64a0b19ad8e8f899f2908dbae) (2013)  
*Julia A. Bennell, Lai Soon Lee, Chris N. Potts · International Journal of Production Economics, Vol. 145(2), pp. 547–560*  
- **Method:** GA with multi-crossover operator and best-fit placement decoder; minimizes number of bins AND maximum lateness Lmax jointly.  
- **→ Z1 relevance:** Establishes the core 2DBPP-DD benchmark; GA ordering heuristic directly maps to block-to-bay assignment under due-date pressure driving Z1.  

**59.** [A Hybrid Feasibility Constraints-Guided Search to the Two-Dimensional Bin Packing Problem with Due Dates](https://arxiv.org/abs/1703.07244) (2018)  
*Sergey Polyakovskiy, Rym M'Hallah · European Journal of Operational Research, Vol. 266(3), pp. 819–839*  
- **Method:** Two-stage hybrid: CP-based neighbourhood search for bin assignment, then MIP sub-problems guided by lookahead feasibility constraints to minimize Lmax.  
- **→ Z1 relevance:** Lookahead feasibility guards prevent selecting bay/time assignments that guarantee lateness; directly applicable to ENTRY/EXIT slot selection to cut Z1.  

**60.** [Number of Bins and Maximum Lateness Minimization in Two-Dimensional Bin Packing](https://www.sciencedirect.com/science/article/abs/pii/S0377221720308274) (2021)  
*Claudio Arbib, Fabrizio Marinelli, Andrea Pizzuti · European Journal of Operational Research, Vol. 291(1), pp. 101–113*  
- **Method:** Sequential Value Correction (SVC) heuristic that tightens lower bounds on Lmax by 31% for industry instances; bi-objective formulation solved via iterative bound improvement.  
- **→ Z1 relevance:** SVC's tight Lmax bound can guide bay assignment order to systematically minimise maximum tardiness, transferable to Z1 upper-bound tightening.  

**61.** [Just-in-Time Two-Dimensional Bin Packing](https://ideas.repec.org/a/eee/jomega/v102y2021ics0305048320306654.html) (2021)  
*Sergey Polyakovskiy, Rym M'Hallah · Omega, Vol. 102, Article 102311*  
- **Method:** Integrated CP model plus two cut-and-check decompositions (CP-master and warm-started MIP-master) minimizing total weighted earliness-tardiness for 2D packing.  
- **→ Z1 relevance:** Cut-and-check decomposition separates packing feasibility from scheduling lateness — matches OGC structure where crane/spatial feasibility and tardiness are coupled.  

**62.** [Just-in-Time Batch Scheduling Problem with Two-Dimensional Bin Packing Constraints](https://arxiv.org/abs/1703.07290) (2017)  
*S. Polyakovskiy, A. Makarowsky, R. M'Hallah · Proceedings of the Genetic and Evolutionary Computation Conference (GECCO), pp. 321–328*  
- **Method:** CP (impact-based search in IBM CP Optimizer) and agent-based constructive method; CP wins on small instances, agent-based on large.  
- **→ Z1 relevance:** Agent-based constructive approach scales to large instances with earliness-tardiness penalties — applicable to large OGC shipyard instances where exact methods time out.  

**63.** [Exact Solutions to the Two-Dimensional Bin Packing Problem with Due Dates](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5343698) (2025)  
*Milad Dehghan, Sergey Polyakovskiy, Rym M'Hallah · SSRN Working Paper (preprint, July 2025)*  
- **Method:** Branch-and-bound / exact MIP approach for 2DBPP-DD; most recent state-of-the-art exact solver for this combined problem.  
- **→ Z1 relevance:** Provides exact optimality certificates for small instances; useful as oracle to validate whether Z1-reduction heuristics reach optimal lateness on OGC toy instances.  

**64.** [The Temporal Bin Packing Problem: An Application to Workload Management in Data Centres](https://ieeexplore.ieee.org/document/7814593/) (2016)  
*Milan de Cauwer, Deepak Mehta, Barry O'Sullivan · IEEE 28th International Conference on Tools with Artificial Intelligence (ICTAI), pp. 157–164*  
- **Method:** Formalises TBPP where items consume capacity during a time interval [start, end]; column generation lower bound plus first-fit greedy heuristic.  
- **→ Z1 relevance:** Foundational TBPP model: blocks occupying bay floor space only during [ENTRY, EXIT] is exactly the temporal bin packing formulation; column generation bound is directly portable.  

**65.** [A Branch-and-Price Algorithm for the Temporal Bin Packing Problem](https://arxiv.org/abs/1902.04925) (2020)  
*Mauro Dell'Amico, Fabio Furini, Manuel Iori · Computers & Operations Research, Vol. 114, Article 104825*  
- **Method:** Exponential-size formulation solved via branch-and-price; polynomial and extended formulations compared; handles instances up to 500 items, 150 time steps.  
- **→ Z1 relevance:** Branch-and-price framework for temporal packing scales to OGC instance sizes; pricing sub-problem structure usable for bay-selection with time-window capacity at every tick.  

**66.** [Matheuristics for the Temporal Bin Packing Problem](https://link.springer.com/chapter/10.1007/978-3-319-58253-5_19) (2018)  
*Fabio Furini, X. Shen · Recent Developments in Metaheuristics, Operations Research/Computer Science Interfaces Vol. 62, Springer*  
- **Method:** Matheuristic combining LP relaxation of extended TBPP formulation with large neighbourhood search; competitive with exact B&P on medium instances.  
- **→ Z1 relevance:** Matheuristic approach is CPU-friendly within the 4-core/no-GPU evaluation server; LNS on top of LP relaxation is directly implementable for crane-serialisation-aware bay scheduling.  

**67.** [Multi-Objective Temporal Bin Packing Problem: An Application in Cloud Computing](https://www.sciencedirect.com/science/article/abs/pii/S0305054820300769) (2020)  
*Nursen Aydin, I. Muter, S. I. Birbil · Computers & Operations Research, Vol. 121, Article 104959*  
- **Method:** Weighted-sum MIP plus fire-up elimination heuristic; minimises active bins and server start-ups simultaneously over time.  
- **→ Z1 relevance:** Multi-objective TBPP with activation costs mirrors Z2 (workload imbalance) + Z1 trade-off; fire-up elimination maps to reducing idle-crane wait times that cause tardiness.  

**68.** [Bin Packing Problem with Time Lags](https://pubsonline.informs.org/doi/10.1287/ijoc.2022.1165) (2022)  
*Orlando Rivera Letelier, François Clautiaux, Ruslan Sadykov · INFORMS Journal on Computing, Vol. 34(4)*  
- **Method:** Branch-cut-and-price with compact + exponential formulation; separation algorithms for feasible item-to-bin assignment under minimum and maximum lag constraints.  
- **→ Z1 relevance:** Time-lag constraints (minimum gap between dependent packing events) model crane serialisation ordering; branch-cut-and-price exact framework applicable to small OGC subproblems.  


## 9. Irregular Strip Packing / Nesting (NFP)  (9)

**69.** [The Geometry of Nesting Problems: A Tutorial](https://www.sciencedirect.com/science/article/abs/pii/S0377221706012379) (2008)  
*J.A. Bennell, J.F. Oliveira · European Journal of Operational Research, Vol. 184, pp. 397–415*  
- **Method:** Unified tutorial covering no-fit polygon (NFP), phi-functions, and raster representations for placement feasibility in irregular 2D packing.  
- **→ Z1 relevance:** Provides the geometric toolkit (NFP, phi-function, raster) needed to test non-overlap feasibility when placing each block in a bay, the inner loop of any Z1-reducing scheduler.  

**70.** [A New Bottom-Left-Fill Heuristic Algorithm for the Two-Dimensional Irregular Packing Problem](https://pubsonline.informs.org/doi/10.1287/opre.1060.0293) (2006)  
*E. Burke, R. Hellier, G. Kendall, G. Whitwell · Operations Research, Vol. 54(3), pp. 587–601*  
- **Method:** Bottom-left-fill greedy placement using NFP-based collision detection; hill-climbing and tabu search perturbation improve compaction of irregular polygons.  
- **→ Z1 relevance:** Fast BLF placement directly assigns (x,y) for each block in a bay; embedded in a scheduler it yields feasible positions in microseconds, enabling many candidate entry/exit times to be evaluated.  

**71.** [A Comprehensive and Robust Procedure for Obtaining the No-Fit Polygon Using Minkowski Sums](https://dl.acm.org/doi/10.1016/j.cor.2006.02.026) (2008)  
*J.A. Bennell, K.A. Song · Computers & Operations Research, Vol. 35(3), pp. 1082–1096*  
- **Method:** Minkowski-sum-based NFP computation that correctly handles concavities, holes, slits, and lock-and-key configurations with internal-edge removal.  
- **→ Z1 relevance:** Robust NFP pre-computation eliminates expensive polygon-intersection checks at runtime; correct NFPs for concave shipyard blocks are a prerequisite for any overlap-free placement move.  

**72.** [An Iterated Local Search Algorithm Based on Nonlinear Programming for the Irregular Strip Packing Problem](https://www.sciencedirect.com/science/article/pii/S1572528609000218) (2009)  
*T. Imamichi, M. Yagiura, H. Nagamochi · Discrete Optimization, Vol. 6(4), pp. 345–361*  
- **Method:** Overlap-minimization via unconstrained nonlinear programming (quasi-Newton) for separation; iterated local search with polygon-swap moves drives total overlap to zero.  
- **→ Z1 relevance:** ILS+NLP separation is one of the strongest heuristics for compacting irregular polygons; adapting it to each bay gives the tightest packing under crane (j≥k) and floor constraints, reducing waiting-induced tardiness.  

**73.** [Jostle Heuristics for the 2D-Irregular Shapes Bin Packing Problems with Free Rotation](https://www.sciencedirect.com/science/article/abs/pii/S0925527317302980) (2018)  
*A. Martinez-Sykora, R. Alvarez-Valdes, J.A. Bennell, J.M. Tamarit · International Journal of Production Economics, Vol. 195, pp. 12–26*  
- **Method:** Jostle: iteratively re-packs shapes by alternating leftmost and rightmost placement passes, shaking the container to fill gaps; diversification via local-search perturbation.  
- **→ Z1 relevance:** Jostle's re-insertion loop can be used after any block exits a bay to re-tighten remaining shapes, directly shrinking the effective footprint and enabling earlier entry of tardy blocks.  

**74.** [A New Approach for Sheet Nesting Problem Using Guided Cuckoo Search and Pairwise Clustering](https://www.sciencedirect.com/science/article/abs/pii/S0377221713005080) (2013)  
*A. Elkeran · European Journal of Operational Research, Vol. 231(3), pp. 757–769*  
- **Method:** Pairwise polygon clustering pre-groups congruent shapes; guided cuckoo search optimises strip length while a secondary overlap-minimisation phase resolves collisions.  
- **→ Z1 relevance:** Clustering blocks that share shape families reduces NFP diversity and speeds up placement enumeration per bay, allowing more schedule candidates to be tested within the time budget.  

**75.** [A Fast and Scalable Bottom-Left-Fill Algorithm to Solve Nesting Problems Using a Semi-Discrete Representation](https://arxiv.org/abs/2103.08739) (2021)  
*S. Chehrazad, D. Roose, T. Wauters · European Journal of Operational Research (arXiv:2103.08739, published EJOR 2022)*  
- **Method:** Semi-discrete representation: pieces and strip discretised as equidistant vertical segments; sweep-line BLF placement runs in milliseconds even with rotations on standard benchmarks.  
- **→ Z1 relevance:** Millisecond feasibility checks per placement trial allow an outer scheduling loop to enumerate thousands of (bay, orientation, entry-time) combinations, attacking Z1 by exploring more time-slot candidates.  

**76.** [Irregular Packing Problems: A Review of Mathematical Models](https://www.sciencedirect.com/science/article/abs/pii/S0377221719303820) (2020)  
*A.A.S. Leao, F.M.B. Toledo, J.F. Oliveira, M.A. Carravilla, R. Alvarez-Valdés · European Journal of Operational Research, Vol. 282(3), pp. 803–822*  
- **Method:** Systematic taxonomy of MIP, NLP, CP, and combinatorial models for nesting, with unified notation comparing NFP-based, phi-function, and raster formulations.  
- **→ Z1 relevance:** Identifies which model classes scale to the 10–100 block instances in OGC 2026 and which are too costly; guides model selection so placement decisions stay tractable inside the scheduling loop.  

**77.** [Matheuristics for the Irregular Bin Packing Problem with Free Rotations](https://www.sciencedirect.com/science/article/abs/pii/S0377221716307950) (2017)  
*A. Martinez-Sykora, R. Alvarez-Valdes, J. Bennell, R. Ruiz, J.M. Tamarit · European Journal of Operational Research, Vol. 258(2), pp. 440–455*  
- **Method:** Constructive matheuristic (NFP-based greedy) combined with VLNS (very large neighbourhood search) and ILP re-optimisation for the irregular bin packing problem with continuous rotations.  
- **→ Z1 relevance:** The constructive+VLNS pattern maps directly to our bay-assignment sub-problem: build an initial feasible placement per bay, then apply neighbourhood search to free space for blocks with tight due dates.  


## 10. Large Neighborhood Search (LNS / ALNS)  (9)

**78.** [Using Constraint Programming and Local Search Methods to Solve Vehicle Routing Problems](https://link.springer.com/chapter/10.1007/3-540-49481-2_30) (1998)  
*Paul Shaw · CP-98: 4th Int'l Conference on Principles and Practice of Constraint Programming, LNCS 1520, pp. 417–431, Springer*  
- **Method:** Defines Large Neighborhood Search: iteratively destroy a partial solution using relatedness-based removal, then repair with CP-guided insertion.  
- **→ Z1 relevance:** Foundational destroy/repair template; relatedness-removal maps directly to grouping crane-blocked blocks for simultaneous rescheduling to cut tardiness.  

**79.** [Record Breaking Optimization Results Using the Ruin and Recreate Principle](https://dl.acm.org/doi/10.1006/jcph.1999.6413) (2000)  
*Gerhard Schrimpf, Johannes Schneider, Hermann Stamm-Wilbrandt, Gunter Dueck · Journal of Computational Physics, 159(2), 139–171*  
- **Method:** Ruin-and-Recreate: aggressively destroy a large fraction of current solution, reconstruct greedily, accept via record-to-record travel criterion.  
- **→ Z1 relevance:** Large-ruin strategy for escaping crane-serialization deadlocks; R&R on a tardy block cluster can simultaneously free vertical-access chains.  

**80.** [An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows](https://pubsonline.informs.org/doi/10.1287/trsc.1050.0135) (2006)  
*Stefan Ropke, David Pisinger · Transportation Science, 40(4), 455–472*  
- **Method:** ALNS: maintains a pool of destroy (random, Shaw, worst) and repair (greedy, k-regret) operators; roulette-wheel adaptive weight updates score each operator's improvement history.  
- **→ Z1 relevance:** Core ALNS framework to port directly: operator pool can include crane-aware block removal, weight updates steer search toward operators that reduce Z1.  

**81.** [A General Heuristic for Vehicle Routing Problems](https://www.sciencedirect.com/science/article/abs/pii/S0305054805003023) (2007)  
*David Pisinger, Stefan Ropke · Computers & Operations Research, 34(8), 2403–2435*  
- **Method:** Unifies five VRP variants into a single ALNS by transforming them into a rich pickup-and-delivery model; demonstrates operator generality across problem structures.  
- **→ Z1 relevance:** Shows ALNS scales to multi-attribute combined assignment+routing; the bay-assignment + crane-serialization coupling in OGC mirrors this multi-constraint setting.  

**82.** [Large Neighborhood Search (handbook chapter)](https://link.springer.com/chapter/10.1007/978-1-4419-1665-5_13) (2010)  
*David Pisinger, Stefan Ropke · Handbook of Metaheuristics, 2nd ed., Springer, pp. 399–420*  
- **Method:** Comprehensive survey of LNS variants: destroy operators (random, Shaw, worst, cluster), repair operators (greedy, k-regret), acceptance criteria (SA, record-to-record), and design guidelines.  
- **→ Z1 relevance:** Operator design blueprint for OGC: cluster-remove crane-blocked stacks, use k-regret reinsertion to prioritize blocks with tightest due dates, minimizing Z1.  

**83.** [An Adaptive Large Neighborhood Search Algorithm for the Resource-Constrained Project Scheduling Problem](https://www.semanticscholar.org/paper/An-Adaptive-Large-Neighborhood-Search-Algorithm-for-Muller/e52835889c74f2509323814b52f804de8a42ae36) (2009)  
*Laurent Flindt Muller · MIC 2009: VIII Metaheuristics International Conference*  
- **Method:** Applies ALNS to RCPSP: destroy operators remove precedence-violating or resource-overloaded activity subsets; repair re-inserts with earliest feasible start times.  
- **→ Z1 relevance:** RCPSP's precedence/resource constraints parallel OGC's crane vertical-access (j≥k) precedence; destroy-repair pattern for constrained project scheduling maps directly.  

**84.** [Improved Formulations and an Adaptive Large Neighborhood Search Heuristic for the Integrated Berth Allocation and Quay Crane Assignment Problem](https://ideas.repec.org/a/eee/transe/v105y2017icp123-147.html) (2017)  
*Çağatay Iris, Dario Pacino, Stefan Ropke · Transportation Research Part E, 105, 123–147*  
- **Method:** ALNS for simultaneous berth-time allocation + crane assignment: destroy operators remove vessel–berth–crane triplets; repair uses regret-based reinsertion respecting crane coverage and time-window constraints.  
- **→ Z1 relevance:** Combined spatial-assignment + crane-assignment + timing problem identical in structure to OGC bay+position+crane+entry-exit; operator patterns for joint feasibility are directly reusable.  

**85.** [Meta-analysis of Metaheuristics: Quantifying the Effect of Adaptiveness in Adaptive Large Neighborhood Search](https://www.sciencedirect.com/science/article/abs/pii/S037722172030936X) (2021)  
*Renata Turkeš, Kenneth Sörensen, Lars Magnus Hvattum · European Journal of Operational Research, 292(2), 423–442*  
- **Method:** Random-effects meta-analysis of 25 ALNS implementations across 63 studies; quantifies the average marginal benefit of the adaptive operator-selection layer (~0.14% improvement).  
- **→ Z1 relevance:** Calibrates whether to invest in adaptive weights vs. simpler LNS for OGC; confirms adaptiveness pays but is not the dominant factor—operator design and repair quality matter more.  

**86.** [Weighted Earliness/Tardiness Parallel Machine Scheduling Problem with a Common Due Date](https://www.sciencedirect.com/science/article/abs/pii/S0957417421012719) (2021)  
*Not confirmed from abstract (Expert Systems with Applications 2021) · Expert Systems with Applications, 186 (2021)*  
- **Method:** ET-ALNS: novel earliness-tardiness ALNS extension with ad-hoc removal/insertion operators and embedded fast objective re-evaluation for parallel machine scheduling with a common due window.  
- **→ Z1 relevance:** Direct template for Z1 (tardiness) objective in OGC: specialized remove-tardy-block operators + fast incremental objective update pattern accelerates per-iteration evaluation.  


## 11. Constraint Programming (CP-SAT / OR-Tools)  (9)

**87.** [The CP-SAT-LP Solver (Invited Talk)](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.CP.2023.3) (2023)  
*Laurent Perron, Frédéric Didier, Steven Gay · 29th International Conference on Principles and Practice of Constraint Programming (CP 2023), LIPIcs vol. 280*  
- **Method:** Hybrid CP+SAT+LP solver with lazy clause generation, LNS portfolio workers, and MIP presolve/cutting planes run in parallel.  
- **→ Z1 relevance:** Drop-in solver for our combined ENTRY/EXIT timing + bay assignment model; portfolio workers provide LNS that can escape crane-serialization bottlenecks driving Z1.  

**88.** [Solving RCPSP/max by Lazy Clause Generation](https://link.springer.com/article/10.1007/s10951-012-0285-x) (2013)  
*Andreas Schutt, Thibaut Feydy, Peter J. Stuckey, Mark G. Wallace · Journal of Scheduling, vol. 16, pp. 273–289, Springer*  
- **Method:** Hybrid finite-domain CP + SAT with no-good learning and conflict-driven search for resource-constrained scheduling with generalized precedence (time-lag) constraints.  
- **→ Z1 relevance:** RCPSP/max precedence relations are structurally identical to our crane j≥k access ordering; LCG's no-good learning can discover and cut crane-blocking patterns that inflate Z1.  

**89.** [Solving the Resource Constrained Project Scheduling Problem with Generalized Precedences by Lazy Clause Generation](https://arxiv.org/abs/1009.0347) (2010)  
*Andreas Schutt, Thibaut Feydy, Peter J. Stuckey, Mark G. Wallace · arXiv:1009.0347 (conference version CP 2010)*  
- **Method:** LCG hybrid that encodes time-window and resource constraints as SAT clauses, applies unit propagation and conflict analysis to prune the scheduling search tree.  
- **→ Z1 relevance:** Conference precursor demonstrating LCG closes 573 previously open RCPSP instances; provides blueprint for encoding crane-access precedences as learnable SAT clauses.  

**90.** [Explaining Time-Table-Edge-Finding Propagation for the Cumulative Resource Constraint](https://arxiv.org/abs/1208.3015) (2013)  
*Andreas Schutt, Thibaut Feydy, Peter J. Stuckey · CPAIOR 2013, LNCS vol. 7874, pp. 234–250 (arXiv:1208.3015)*  
- **Method:** Combines time-table resource profile with edge-finding in a cumulative propagator that generates explanations (nogood clauses) compatible with lazy clause generation.  
- **→ Z1 relevance:** This propagator is used inside CP-SAT's cumulative constraint; stronger pruning tightens ENTRY windows for blocks waiting behind crane-blocked neighbours, directly cutting tardiness.  

**91.** [Edge Finding Filtering Algorithm for Discrete Cumulative Resources in O(kn log n)](https://link.springer.com/chapter/10.1007/978-3-642-04244-7_62) (2009)  
*Petr Vilím · CP 2009, LNCS vol. 5732, pp. 802–816, Springer*  
- **Method:** O(kn log n) edge-finding algorithm for discrete cumulative constraints, using a sweep-line data structure to detect and prune infeasible interval orderings.  
- **→ Z1 relevance:** The core propagation algorithm underlying OR-Tools' add_cumulative; efficient pruning of bay-capacity (workload) windows helps schedule earlier EXIT times, reducing Z1.  

**92.** [Packing by Scheduling: Using Constraint Programming to Solve a Complex 2D Cutting Stock Problem](https://link.springer.com/chapter/10.1007/978-3-031-08011-1_17) (2022)  
*Yiqing Luo, J. Christopher Beck · CPAIOR 2022, LNCS vol. 13292, pp. 239–255, Springer*  
- **Method:** Reformulates 2D cutting-stock as a scheduling problem: each item becomes an interval variable on X and Y axes; no_overlap_2d (diffn) enforces non-overlap; CP solves placement+quantity jointly.  
- **→ Z1 relevance:** Direct methodological bridge: encodes our 2D polygon placement as CP interval pairs with no_overlap_2d, enabling timing (ENTRY/EXIT) and position to be co-optimized in one CP-SAT model.  

**93.** [Industrial-size Job Shop Scheduling with Constraint Programming](https://www.sciencedirect.com/science/article/pii/S2214716022000215) (2022)  
*Giacomo Da Col, Erich C. Teppan · Operations Research Perspectives, vol. 9, article 100249, Elsevier*  
- **Method:** Benchmarks OR-Tools CP-SAT and IBM CP Optimizer on instances up to 1M operations, comparing no-overlap propagation, LNS, and portfolio strategies at industrial scale.  
- **→ Z1 relevance:** Provides empirical guidance on when CP-SAT's built-in LNS beats CP Optimizer for job-shop variants similar to our bay-assignment + time scheduling subproblem.  

**94.** [PyJobShop: Solving Scheduling Problems with Constraint Programming in Python](https://arxiv.org/abs/2502.13483) (2025)  
*Leon Lan, Joost Berkhout · arXiv:2502.13483*  
- **Method:** Open-source Python library wrapping OR-Tools CP-SAT and CP Optimizer; unified API for FJSP, RCPSP, and multi-mode scheduling; benchmarked on 9,000+ instances.  
- **→ Z1 relevance:** Provides ready-made CP models for resource-constrained scheduling with release dates and due dates; can be adapted to add crane-ordering constraints and minimize weighted tardiness.  

**95.** [A Constrained Programming Model for the Optimization of Industrial-Scale Scheduling Problems in the Shipbuilding Industry](https://www.mdpi.com/2077-1312/11/8/1517) (2023)  
*(Sanmartín-Antelo and co-authors) · Journal of Marine Science and Engineering, vol. 11, no. 8, article 1517, MDPI*  
- **Method:** CP model for FJSP with assembly hierarchy, limited buffer capacity, and due-date constraints in a real shipbuilding facility; minimizes makespan and tardiness jointly.  
- **→ Z1 relevance:** Real shipyard CP application with spatial buffer and due-date tardiness objectives; demonstrates feasibility of CP for the exact constraint mix (placement + timing + tardiness) in our problem.  


## 12. Berth Allocation (space-time packing)  (9)

**96.** [The Berth Planning Problem](https://www.sciencedirect.com/science/article/abs/pii/S0167637798000108) (1998)  
*Andrew Lim · Operations Research Letters, Vol. 22(2-3), pp. 105-110*  
- **Method:** Transforms berth allocation to 2D rectangle-packing/graph-coloring; proves NP-hardness; proposes greedy heuristic.  
- **→ Z1 relevance:** Establishes the ship-in-quay = block-in-bay space-time rectangle analogy; NP-hardness proof motivates heuristic-first approach for our packing+scheduling problem.  

**97.** [Berth Scheduling by Simulated Annealing](https://www.sciencedirect.com/science/article/abs/pii/S0191261502000279) (2003)  
*Kap Hwan Kim, Kyung Chan Moon · Transportation Research Part B, Vol. 37(6), pp. 541-560*  
- **Method:** SA metaheuristic jointly optimizes 2D berthing position and time, minimizing total weighted tardiness/earliness via neighborhood moves in time-space.  
- **→ Z1 relevance:** Direct analog: SA on (position, entry-time, exit-time) tuples is portable to our (bay, x, y, ENTRY, EXIT) decisions to cut tardiness.  

**98.** [The Berth Allocation Problem: Models and Solution Methods](https://link.springer.com/article/10.1007/s00291-003-0140-8) (2004)  
*Yongpei Guan, Raymond K. Cheung · OR Spectrum, Vol. 26, pp. 75-92*  
- **Method:** Two MIP formulations for continuous BAP (minimize weighted flow-time); tree-search + lower-bound procedure + pair-wise exchange heuristic for large instances.  
- **→ Z1 relevance:** MIP formulation for non-overlapping 2D time-space rectangles with weighted completion objectives directly maps to our bay-level block scheduling with Z1 weighting.  

**99.** [A Scheduling Method for Berth and Quay Cranes](https://link.springer.com/article/10.1007/s00291-002-0109-z) (2003)  
*Young-Man Park, Kap Hwan Kim · OR Spectrum, Vol. 25, pp. 1-23*  
- **Method:** Two-phase IP: Phase 1 sub-gradient for berthing position+time+crane count; Phase 2 dynamic programming for detailed crane schedule given Phase 1 output.  
- **→ Z1 relevance:** Two-phase decomposition (assign bay/time first, then resolve crane conflicts in Phase 2) mirrors our need to decouple ENTRY/EXIT assignment from crane-access serialization repair.  

**100.** [The Berth Allocation Problem: A Strong Formulation Solved by a Lagrangean Approach](https://pubsonline.informs.org/doi/10.1287/trsc.1060.0171) (2007)  
*M. Flavia Monaco, Marcello Sammarra · Transportation Science, Vol. 41(2), pp. 265-280*  
- **Method:** Compact, strong MIP for discrete BAP with valid inequalities; Lagrangean relaxation + subgradient provides tight lower bound enabling branch-and-bound pruning.  
- **→ Z1 relevance:** Strong LP relaxation bounding technique applicable to our combined packing+crane-access MIP to certify optimality gaps and guide branch-and-bound for Z1 reduction.  

**101.** [Models for the Discrete Berth Allocation Problem: A Computational Comparison](https://ideas.repec.org/a/eee/transe/v47y2011i4p461-473.html) (2011)  
*Katja Buhrkal, Sara Zuglian, Stefan Ropke, Jesper Larsen, Richard Lusby · Transportation Research Part E, Vol. 47(4), pp. 461-473*  
- **Method:** Systematic comparison of three MIP models (position-based, time-indexed, set-partitioning) for discrete BAP; set-partitioning model dominates computationally.  
- **→ Z1 relevance:** Identifies which MIP encoding scales best for combined time-space problems; set-partitioning structure is directly portable to our bay-block assignment with release/due constraints.  

**102.** [A Survey of Berth Allocation and Quay Crane Scheduling Problems in Container Terminals](https://www.sciencedirect.com/science/article/abs/pii/S0377221709003579) (2010)  
*Christian Bierwirth, Frank Meisel · European Journal of Operational Research, Vol. 202(3), pp. 615-627*  
- **Method:** Taxonomy of BAP/QCSP models along spatial (discrete/continuous) and temporal (static/dynamic) axes; classifies objective functions, constraint types, and solution methods.  
- **→ Z1 relevance:** Taxonomy maps 1-to-1 onto our problem axes (continuous space, dynamic arrivals, tardiness objective); guides which exact/heuristic method class to port for crane-blocking subproblem.  

**103.** [A Follow-up Survey of Berth Allocation and Quay Crane Scheduling Problems in Container Terminals](https://ideas.repec.org/a/eee/ejores/v244y2015i3p675-689.html) (2015)  
*Christian Bierwirth, Frank Meisel · European Journal of Operational Research, Vol. 244(3), pp. 675-689*  
- **Method:** Extends 2010 survey with 120+ new papers; documents shift toward integrated BAP+crane+yard models, robust/stochastic variants, and ALNS/MIP hybrid dominance.  
- **→ Z1 relevance:** Documents that integrated crane-assignment models cut tardiness versus decoupled approaches — directly motivates integrating crane-access constraints into our scheduling objective.  

**104.** [An Adaptive Large Neighborhood Search for the Discrete and Continuous Berth Allocation Problem](https://www.sciencedirect.com/science/article/abs/pii/S0305054816000046) (2016)  
*Gustavo Henrique Mauri, Geraldo Regis Mauri, Luiz Antonio Nogueira Lorena, Gilbert Laporte · Computers & Operations Research, Vol. 70, pp. 140-154*  
- **Method:** ALNS with destroy/repair operators (random removal, worst-first removal, regret-based reinsertion) unified across discrete and continuous BAP variants.  
- **→ Z1 relevance:** ALNS destroy/repair on (bay, entry-time, exit-time) tuples is directly portable; worst-tardiness removal targets the crane-blocked blocks causing our Z1.  


## 13. Just-in-Time / Due-Date Scheduling & Timing DP  (8)

**105.** [Sequencing with Earliness and Tardiness Penalties: A Review](https://pubsonline.informs.org/doi/10.1287/opre.38.1.22) (1990)  
*K.R. Baker, G.D. Scudder · Operations Research, 38(1), pp. 22–36*  
- **Method:** Systematic review of JIT scheduling models: dominance properties, common vs. distinct due dates, single vs. parallel machines, penalty structures.  
- **→ Z1 relevance:** Establishes structural properties (V-shaped sequences, idle-time insertion) that directly inform how to sequence blocks around their due-EXIT dates to minimize Z1.  

**106.** [Optimal Timing of a Sequence of Tasks with General Completion Costs](https://www.sciencedirect.com/science/article/abs/pii/S0377221704000682) (2005)  
*M. Sourd, O. Witz · European Journal of Operational Research, 165(1), pp. 82–96*  
- **Method:** Dynamic programming O(n²) algorithm that computes optimal start-times for a fixed job sequence with arbitrary convex completion-cost functions and idle-time penalties.  
- **→ Z1 relevance:** Given a fixed crane-serialization order, this timing DP finds ENTRY/EXIT times minimizing Z1 exactly — decouples sequencing from timing, enabling a clean two-phase solver.  

**107.** [Just-in-Time Scheduling Problem with Affine Idleness Cost](https://www.sciencedirect.com/science/article/pii/S0377221723006690) (2024)  
*Zhen Tan, Guanqi Fu · European Journal of Operational Research, 313(3), pp. 954–976*  
- **Method:** O(n²) DP for timing sub-problem with non-convex cost + genetic algorithm with early-discarding for sequencing; handles earliness, tardiness, and idle-time costs jointly.  
- **→ Z1 relevance:** Crane serialization inserts forced idle gaps between blocks; this paper's DP handles affine idle costs — directly models the waiting cost when crane access is delayed.  

**108.** [Fast Neighborhood Search for the Single Machine Earliness–Tardiness Scheduling Problem](https://www.sciencedirect.com/science/article/abs/pii/S0305054809002895) (2010)  
*S. Kedad-Sidhoum, F. Sourd · Computers & Operations Research, 37(8), pp. 1464–1471*  
- **Method:** Block-structured schedule representation with O(n²) swap and extract-reinsert neighborhoods; embedded timing operator recomputes optimal ENTRY/EXIT after each move.  
- **→ Z1 relevance:** Provides fast local-search moves for reassigning block order within a bay while re-timing entries/exits to cut Z1, exploiting the timing-subproblem structure after each swap.  

**109.** [A Meta-Heuristic to Solve the Just-in-Time Job-Shop Scheduling Problem](https://www.sciencedirect.com/science/article/abs/pii/S0377221720303519) (2021)  
*M.M. Ahmadian, A. Salehipour, T.C.E. Cheng · European Journal of Operational Research, 288(1), pp. 14–29*  
- **Method:** Variable Neighbourhood Search (VNS) decomposing JIT-JSS into sub-problems; each operation has a distinct due-date with earliness/tardiness penalty; achieves new best solutions on benchmarks.  
- **→ Z1 relevance:** The shipyard problem is essentially JIT-JSS with crane precedence constraints; VNS sub-problem decomposition maps onto bay-level scheduling of block ENTRY/EXIT sequences.  

**110.** [Structural Properties and Algorithms for Earliness and Tardiness Scheduling Against Common Due Dates and Windows: A Review](https://www.sciencedirect.com/science/article/abs/pii/S036083522030509X) (2020)  
*G.A. Rolim, M.S. Nagano · Computers & Industrial Engineering, 149, Article 106803*  
- **Method:** Surveys 26 structural properties of optimal JIT schedules (V-shape, no-idle, position constraints) and classifies algorithms across machine environments and due-date variants.  
- **→ Z1 relevance:** Condensed reference for which structural properties survive with release dates and distinct due-dates — directly applicable when deciding whether to allow idle time before crane access.  

**111.** [A n Job, One Machine Sequencing Algorithm for Minimizing the Number of Late Jobs](https://pubsonline.informs.org/doi/10.1287/mnsc.15.1.102) (1968)  
*J.M. Moore · Management Science, 15(1), pp. 102–109*  
- **Method:** O(n log n) greedy algorithm (Moore-Hodgson): schedule EDD order; when a job becomes tardy, drop the longest-processing job seen so far; minimizes number of tardy jobs.  
- **→ Z1 relevance:** Provides a fast feasible baseline that maximizes on-time blocks; minimizing tardy count directly reduces Z1 ≥ 0 terms — use as initial solution seeding further optimization.  

**112.** [Earliness-Tardiness Scheduling Problems, I: Weighted Deviation of Completion Times About a Common Due Date](https://pubsonline.informs.org/doi/10.1287/opre.39.5.836) (1991)  
*H. Emmons · Operations Research, 39(5), pp. 836–846*  
- **Method:** Dominance theorems establishing pairwise job-ordering conditions (Emmons rules) that must hold in any optimal single-machine tardiness sequence; used to prune branch-and-bound trees.  
- **→ Z1 relevance:** Emmons dominance conditions prune the combinatorial explosion of bay-sequencing: pairs of blocks with clear priority order are fixed, shrinking the search space for crane-access scheduling.  


## 14. Matheuristics & Logic-Based Benders Decomposition  (9)

**113.** [Logic-based Benders decomposition](https://link.springer.com/article/10.1007/s10107-003-0375-9) (2003)  
*J. N. Hooker, G. Ottosson · Mathematical Programming, Vol. 96, pp. 33–60*  
- **Method:** Generalizes Benders decomposition so subproblems can be any optimization model (CP, MIP); master fixes assignment variables, subproblem sequences tasks.  
- **→ Z1 relevance:** Canonical framework: fix bay/entry-time master (MIP), solve crane-ordering subproblem (CP) per bay, cut back infeasibilities — directly decomposes our joint problem.  

**114.** [Planning and Scheduling by Logic-Based Benders Decomposition](https://pubsonline.informs.org/doi/10.1287/opre.1060.0371) (2007)  
*J. N. Hooker · Operations Research, Vol. 55, No. 3, pp. 588–602*  
- **Method:** MILP master assigns tasks to facilities; CP subproblem schedules tasks on each facility and generates Benders cuts (no-good + optimality) back to master.  
- **→ Z1 relevance:** Shows MILP+CP LBBD for multi-machine scheduling with resource constraints; directly portable to bay-assignment master + per-bay crane-serialization CP subproblem.  

**115.** [Combinatorial Benders Decomposition for Single Machine Scheduling in Additive Manufacturing with Two-Dimensional Packing Constraints](https://ideas.repec.org/a/eee/ejores/v317y2024i3p890-905.html) (2024)  
*Zhaofang Mao, Enyuan Fu, Dian Huang, Kan Fang, Lin Chen · European Journal of Operational Research, Vol. 317, No. 3, pp. 890–905*  
- **Method:** Combinatorial Benders decomposes batch-assignment (master MIP) from 2D rectangle packing (subproblem); combinatorial cuts + acceleration strategies for makespan minimization.  
- **→ Z1 relevance:** Nearest published analogue to our problem: packing+scheduling exact decomposition; swap makespan for tardiness and rectangles for polygons and the framework applies directly.  

**116.** [Improving the Efficiency of Logic-Based Benders Decomposition for p-Batch Scheduling Problems with Two-Dimensional Packing](https://www.sciencedirect.com/science/article/pii/S0377221726000767) (2026)  
*Florian Braun, Thomas Reuter, Guenther Zaepfel (and co-authors, EJOR 2026) · European Journal of Operational Research (online Jan 2026)*  
- **Method:** Dynamic approximation of 2D packing subproblems, criticality-based prioritization, and greedy/irreducible stronger Benders cuts to accelerate LBBD for batch+packing problems.  
- **→ Z1 relevance:** Most recent acceleration toolkit for packing+scheduling LBBD; cut-strengthening and subproblem approximation techniques are drop-in improvements for crane-serialization subproblems.  

**117.** [Novel Formulations and Logic-Based Benders Decomposition for the Integrated Parallel Machine Scheduling and Location Problem](https://pubsonline.informs.org/doi/10.1287/ijoc.2021.1113) (2022)  
*Yantong Li, Jean-François Côté, Leandro Callegari-Coelho, Peng Wu · INFORMS Journal on Computing, Vol. 34, No. 2, pp. 1048–1069*  
- **Method:** LBBD: MILP master locates machines and assigns jobs; CP subproblem sequences jobs per machine; novel formulations tighten master LP relaxation for makespan.  
- **→ Z1 relevance:** Location+assignment+sequencing structure mirrors our bay-selection+block-assignment+crane-ordering; location as discrete set closely analogous to bay choice.  

**118.** [Column Generation for the Integrated Berth Allocation, Quay Crane Assignment, and Yard Assignment Problem](https://pubsonline.informs.org/doi/10.1287/trsc.2018.0822) (2018)  
*Kai Wang, Lu Zhen, Shuaian Wang, Gilbert Laporte · Transportation Science, Vol. 52, No. 4, pp. 812–834*  
- **Method:** Dantzig-Wolfe reformulation over vessel patterns; column generation provides LP lower bound; pricing solved exactly; dual stabilization accelerates convergence.  
- **→ Z1 relevance:** Integrates spatial assignment (yard/berth) with crane assignment via column generation — template for reformulating our bay+crane-time assignment as a set-partitioning pricing problem.  

**119.** [An Accelerated Benders Decomposition Algorithm for the Integrated Storage Space Assignment, Berth Allocation, and Yard Crane Deployment Problem](https://www.sciencedirect.com/science/article/abs/pii/S0360835224005187) (2024)  
*Golsa Soroushnia, Mahdi Alinaghian, Amirsalar Malekahmadi · Computers & Industrial Engineering, Vol. 194*  
- **Method:** Accelerated Benders decomposition with combinatorial Benders cut + 8 valid inequalities for a three-way integrated spatial-assignment, berth, and crane-deployment MIP.  
- **→ Z1 relevance:** Shows that yard-crane deployment (spatial+temporal) integrates cleanly with Benders when valid inequalities tighten subproblem cuts — directly reduces crane waiting = our tardiness driver.  

**120.** [Hierarchical Rectangle Packing Solved by Multi-Level Recursive Logic-based Benders Decomposition](https://arxiv.org/abs/2512.20239) (2025)  
*Josef Grus, Zdeněk Hanzálek, Christian Artigues, Cyrille Briand, Emmanuel Hebrard · arXiv:2512.20239*  
- **Method:** Multi-level recursive LBBD: each level fixes container dimensions and decomposes into nested packing subproblems; dynamically refines block-dimension constraints without manual candidate enumeration.  
- **→ Z1 relevance:** Multi-level decomposition for packing-within-packing matches our nested structure (bay → floor → polygon placement); recursive cut propagation could handle crane-layer dependency.  

**121.** [Logic-Based Benders Decomposition for Large-Scale Optimization](https://arxiv.org/abs/1910.11944) (2019)  
*J. N. Hooker · Chapter in Large Scale Optimization in Supply Chains and Smart Manufacturing, Springer; arXiv:1910.11944*  
- **Method:** Comprehensive survey + theory of LBBD including branch-and-check variant; organizes literature by problem domain; covers planning, scheduling, packing, stochastic settings.  
- **→ Z1 relevance:** Authoritative reference and recipe book for choosing master/subproblem split and cut type; branch-and-check variant avoids repeated master solves — crucial for tight time limits.  


## 15. GA / Metaheuristics for Shipyard  (4)

**122.** [A Hybrid Heuristic Algorithm for Ship Block Construction Space Scheduling Problem](https://doi.org/10.1155/2015/841637) (2015)  
*Shicheng Hu, Tengjiao Liu, Song Wang, Yonggui Kao, Xuedong Sun · Discrete Dynamics in Nature and Society, Article 841637*  
- **Method:** Corner-guided BLF initial solution improved by simulated annealing with accept-worse neighbor moves to escape local optima; targets makespan minimization.  
- **→ Z1 relevance:** SA escape mechanism for shipyard block packing can be applied to our crane-serialized bay sequences to pull tardy blocks earlier.  

**123.** [A Genetic Algorithm for Erection Scheduling at a Dock](https://onepetro.org/JSPD/article-abstract/23/01/17/173380/A-Genetic-Algorithm-for-Erection-Scheduling-at-a) (2007)  
*Xu Ai-min, Ye Jin · Journal of Ship Production and Design, Vol. 23, No. 1, pp. 17–22*  
- **Method:** GA with a novel feasibility-preserving crossover operator over erection sequences; model includes crane-capacity and erection-network (precedence) constraints.  
- **→ Z1 relevance:** Crane-capacity and precedence constraints modeled directly in GA crossover; the j≥k crane access rule is structurally similar to erection precedence and can inherit this encoding.  

**124.** [A Metaheuristic Algorithm to Transporter Scheduling for Assembly Blocks in a Shipyard considering Precedence and Cooperating Constraints](https://doi.org/10.1155/2019/2615154) (2019)  
*Tao et al. · Discrete Dynamics in Nature and Society, Article 2615154*  
- **Method:** Hybrid topological-graph GA + Tabu Search encoding precedence and cooperation constraints; minimizes logistics time (empty travel + waiting + delay) for heavy block transporters.  
- **→ Z1 relevance:** GA-Tabu hybrid with explicit delay minimization under precedence constraints maps onto our crane serialization bottleneck; Tabu prevents cycling in sequencing decisions.  

**125.** [Block Transportation Scheduling under Delivery Restriction in Shipyard using Meta-Heuristic Algorithms](https://www.sciencedirect.com/science/article/abs/pii/S0957417413008361) (2014)  
*C.M. Joo, B.S. Kim · Expert Systems with Applications, Vol. 41, No. 6, pp. 2851–2858*  
- **Method:** MIP formulation + GA and Self-Evolution Algorithm (SEA) for block delivery sequencing with time-window delivery restrictions; minimizes total penalty (delay) time.  
- **→ Z1 relevance:** Penalty-time minimization (= tardiness) under delivery windows directly parallels Z1; SEA's self-adaptation avoids parameter tuning on varied instance sizes.  


## 16. Time-Space Network & Dynamic Facility Layout  (6)

**126.** [Space-Time Repetitive Project Scheduling Considering Location and Congestion](https://ascelibrary.org/doi/10.1061/%28ASCE%29CP.1943-5487.0000745) (2018)  
*Sha Tao, Changzhi Wu, Zhaohan Sheng, Xiangyu Wang · Journal of Computing in Civil Engineering, Vol. 32(3), ASCE*  
- **Method:** Multiobjective MIP model for activity scheduling + workspace congestion; solved via NSGA-II with electromagnetism-like mechanism.  
- **→ Z1 relevance:** Models spatial congestion serializing activities — directly analogous to crane-access serialization driving OUR Z1; congestion penalty can inform bay-time slot allocation to avoid crane queue buildup.  

**127.** [Novel Time-Space Network Flow Formulation and Approximate Dynamic Programming Approach for the Crane Scheduling in a Coil Warehouse](https://www.sciencedirect.com/science/article/abs/pii/S0377221717301935) (2017)  
*Yuan Yuan, Lixin Tang · European Journal of Operational Research, Vol. 262(2), pp. 424–437*  
- **Method:** Event-based time-space network flow: nodes = location × stage, edges = crane moves; 0-1 LP + approximate dynamic programming with affine value-function approximation.  
- **→ Z1 relevance:** Directly solves crane serialization through a time-space network — the core bottleneck of OUR Z1; the ADP approach is portable to our crane-access ordering subproblem within 30-min wall-clock limits.  

**128.** [An Innovative Operation-Time-Space Network for Solving Different Logistic Problems with Capacity and Time Constraints](https://onlinelibrary.wiley.com/doi/abs/10.1002/net.22042) (2021)  
*Daniela Ambrosino, Veronica Asta · Networks, Vol. 78(3), pp. 350–367, Wiley*  
- **Method:** Generic operation-time-space network graph (nodes = operation × time × location) unified LP flow formulation; applied to port rail shunting and quay crane scheduling.  
- **→ Z1 relevance:** Provides a unifying graph abstraction to encode crane access ordering + bay occupancy + time windows simultaneously — a ready blueprint for our combined scheduling-spatial model.  

**129.** [An Integrated Dynamic Facility Layout and Job Shop Scheduling Problem: A Hybrid NSGA-II and Local Search Algorithm](https://www.aimsciences.org/article/doi/10.3934/jimo.2019030) (2019)  
*Behrad Erfani, Sadoullah Ebrahimnejad, Amirhossein Moosavi · Journal of Industrial and Management Optimization, Vol. 16(4)*  
- **Method:** Simultaneous optimization of facility layout and job scheduling via hybrid NSGA-II + local search; quantifies 10% mean-flow-time gain vs. sequential optimization.  
- **→ Z1 relevance:** Demonstrates that co-optimizing physical layout (= bay assignment) with scheduling yields 10%+ tardiness reduction vs. decoupled approach — justifies integrated formulation for our Z1 attack.  

**130.** [A Matheuristic Algorithm for Block Assignment Problem in Long-Term Production Planning in the Shipbuilding Industry](https://www.sciencedirect.com/science/article/abs/pii/S0360835223006277) (2023)  
*Jonghwa Lee, Byung-In Kim · Computers & Industrial Engineering, Vol. 184, Article 109573*  
- **Method:** Two-stage matheuristic: stage 1 assigns block groups to regions (beam search); stage 2 assigns individual blocks to assembly shops (MIP); minimizes workload deviation.  
- **→ Z1 relevance:** Provides a real-world validated two-stage decomposition for bay (shop) assignment under workload balance — directly applicable to OUR Z2 + Z1 tradeoff and scalable to competition instance sizes.  

**131.** [SCaRC: Space-Constrained Resource-Constrained Scheduling System](https://ascelibrary.org/doi/10.1061/%28ASCE%290887-3801%281997%2911%3A1%2848%29) (1997)  
*Walid Y. Thabet, Yvan J. Beliveau · Journal of Computing in Civil Engineering, Vol. 11(1), pp. 48–59, ASCE*  
- **Method:** Knowledge-based system that treats workspace area as an explicit renewable resource constraint alongside labor/equipment; integrates space-based and resource-based scheduling in a single heuristic.  
- **→ Z1 relevance:** Seminal formalization of workspace as a scheduling resource — the conceptual foundation for treating crane-vertical-access clearance as a blocking resource constraint in our model.  


## 17. Blocking Job-Shop / No-Wait (crane-hold analog)  (10)

**132.** [Job-shop scheduling with blocking and no-wait constraints](https://www.sciencedirect.com/science/article/abs/pii/S0377221701003381) (2002)  
*Alessandro Mascis, Dario Pacciarelli · European Journal of Operational Research, vol. 143(3), pp. 498–517*  
- **Method:** Alternative graph (generalized disjunctive graph) formulation unifying blocking and no-wait constraints; dispatching heuristics on the graph.  
- **→ Z1 relevance:** Foundational model: blocking = zero buffer = crane hold. Alternative graph encodes crane-serialization waits exactly; basis for all downstream local-search methods.  

**133.** [A new neighborhood and tabu search for the Blocking Job Shop](https://www.sciencedirect.com/science/article/pii/S0166218X09000870) (2009)  
*Heinz Gröflin, Andreas Klinkert · Discrete Applied Mathematics, vol. 157, pp. 3643–3655*  
- **Method:** Feasible neighborhood via 'closure' and short-cycle properties of the disjunctive graph; tabu search on critical-arc swaps that preserve feasibility under blocking.  
- **→ Z1 relevance:** Directly portable: crane-access blocking = zero buffer; feasible-neighbor generation via critical-arc swap prevents infeasible crane-wait states, reducing tardiness.  

**134.** [The flexible blocking job shop with transfer and set-up times](https://link.springer.com/article/10.1007/s10878-009-9278-x) (2011)  
*Heinz Gröflin, Dinh Nguyen Pham, Reinhard Bürgy · Journal of Combinatorial Optimization, vol. 22, pp. 121–144*  
- **Method:** Local search with feasible neighborhood for flexible BJS (alternative machines, no buffers, setup times); implied co-moves of affected operations maintain feasibility.  
- **→ Z1 relevance:** Crane lifts are 'transfer' ops; implied co-moves model the cascade unblocking after a crane clears a path, enabling tardiness-aware sequencing.  

**135.** [A neighborhood for complex job shop scheduling problems with regular objectives](https://link.springer.com/article/10.1007/s10951-017-0532-2) (2017)  
*Reinhard Bürgy · Journal of Scheduling, vol. 20, pp. 391–422*  
- **Method:** Job-reinsertion neighborhood for complex job-shops (blocking, setup, transfer) with any regular objective (makespan, total tardiness, total weighted tardiness); tabu search.  
- **→ Z1 relevance:** Supports total-tardiness objective directly; reinserting a blocked block into an earlier crane-clear slot maps onto our Z1 reduction goal.  

**136.** [An iterated greedy metaheuristic for the blocking job shop scheduling problem](https://link.springer.com/article/10.1007/s10732-014-9279-5) (2016)  
*Marco Pranzo, Dario Pacciarelli · Journal of Heuristics, vol. 22, pp. 587–611*  
- **Method:** Iterated Greedy (destruction + greedy reconstruction) adapted for BJS; handles makespan on FT and LA benchmarks, beats state-of-art at the time.  
- **→ Z1 relevance:** IG skeleton is CPU-cheap and restartable; directly adaptable to tardiness by changing the insertion criterion to EDD/slack during greedy reconstruction.  

**137.** [An iterated greedy algorithm for solving the total tardiness parallel blocking flow shop scheduling problem](https://www.sciencedirect.com/science/article/abs/pii/S0957417418308078) (2019)  
*Immaculada Ribas Vila, Ramón Companys Pascual, Xavier Tort-Martorell · Expert Systems with Applications, vol. 121, pp. 347–361*  
- **Method:** Iterated Greedy with NEH-based initialization and due-date-aware insertion for parallel blocking flow shops; minimizes total tardiness under zero-buffer constraints.  
- **→ Z1 relevance:** Closest structural match: blocking + total-tardiness + parallel lines (analogous to parallel bays); IG with tardiness-aware insertion directly addresses our Z1 objective.  

**138.** [On Neighborhood Structures and Repair Techniques for Blocking Job Shop Scheduling Problems](https://www.mdpi.com/1999-4893/12/11/242) (2019)  
*Gröflin, Bürgy et al. · Algorithms (MDPI), vol. 12, no. 11, article 242*  
- **Method:** Simulated annealing with interchange/shift operators and scheduling-tailored repair procedures (transformation + feasibility repair) for blocking JSP with total tardiness.  
- **→ Z1 relevance:** SA + repair directly handles crane-induced infeasibility cycles; repair technique prevents getting stuck on infeasible crane-access states while optimizing Z1.  

**139.** [The blocking flow shop scheduling problem: A comprehensive and conceptual review](https://www.sciencedirect.com/science/article/abs/pii/S0957417419304774) (2019)  
*Hugo H. Miyata, Marcelo S. Nagano · Expert Systems with Applications, vol. 137, pp. 130–156*  
- **Method:** Systematic review of 139 papers (1969–2019): taxonomizes objectives, methods (77% metaheuristics), and open problems in blocking flowshop scheduling.  
- **→ Z1 relevance:** Survey confirms iterated greedy + local search dominate tardiness variants; maps which existing operators are transferable to our crane-blocking / multi-bay setting.  

**140.** [A MILP model to minimize total tardiness in a job shop scheduling problem with blocking and no-wait constraints](https://www.rairo-ro.org/articles/ro/abs/2025/05/ro240845/ro240845.html) (2025)  
*Zineb Lissioued, Samia Ourari, Hacène Ait Haddadène · RAIRO – Operations Research, vol. 59, pp. 2545–2558*  
- **Method:** First MILP (CPLEX) for the combined blocking-and-no-wait JSP with total tardiness objective; establishes benchmark baselines on classical instances.  
- **→ Z1 relevance:** MILP bounds tighten feasibility proof for crane-blocked schedules; model structure (disjunctive + no-wait) mirrors ENTRY/EXIT time-window constraints in our problem.  

**141.** [Generating Dispatching Rules for the Interrupting Swap-Allowed Blocking Job Shop Problem Using Graph Neural Network and Reinforcement Learning](https://arxiv.org/abs/2302.02506) (2023)  
*Vivian W.H. Wong, Sang Hun Kim, Junyoung Park, Jinkyoo Park, Kincho H. Law · arXiv preprint arXiv:2302.02506*  
- **Method:** Dynamic disjunctive-graph GNN trained via RL to generate real-time dispatching rules for blocking JSP with machine disruptions (swap-allowed variant).  
- **→ Z1 relevance:** GNN captures which blocked crane-access arc to break next; learned policy could replace greedy dispatch at each crane decision, directly reducing serialization-caused tardiness.  


## 18. Combined 2D Packing + Scheduling (AM nesting)  (6)

**142.** [Production scheduling and nesting in additive manufacturing](https://doi.org/10.1016/j.cie.2018.09.048) (2018)  
*A. Chergui, K. Hadj-Hamou, F. Vignat · Computers & Industrial Engineering, Vol. 126, pp. 292–301*  
- **Method:** Two-phase MILP + heuristic: groups irregular parts into batches, then sequences batches on parallel AM machines to minimize total tardiness.  
- **→ Z1 relevance:** Direct blueprint: decouple bay-assignment (batching) from time-sequencing, then minimize Z1 with a repair heuristic over each phase.  

**143.** [Machine scheduling with orientation selection and two-dimensional packing for additive manufacturing](https://www.sciencedirect.com/science/article/abs/pii/S030505482100037X) (2021)  
*Yuxin Che, Kanxin Hu, Zhenzhen Zhang, Andrew Lim · Computers & Operations Research, Vol. 130, Article 105245*  
- **Method:** MILP model + simulated annealing with 11 neighbourhood operators; first work coupling part-orientation selection with batch-machine scheduling and 2D packing.  
- **→ Z1 relevance:** SA operators that swap orientation and re-pack within a time slot can be adapted to reorder crane-access sequence and reduce blocking-induced tardiness.  

**144.** [An iterated local search for customer order scheduling in additive manufacturing](https://www.tandfonline.com/doi/full/10.1080/00207543.2023.2167015) (2023)  
*Benedikt Zipfel, Janis Neufeld, Udo Buscher · International Journal of Production Research, Vol. 62(3), pp. 605–625*  
- **Method:** ILS metaheuristic with perturbation + local search over joint nesting-and-scheduling decisions; MIP model integrates sequence-dependent setups and unrelated parallel machines; minimizes total weighted tardiness of orders.  
- **→ Z1 relevance:** ILS perturbation operators that reassign blocks between bays (machines) while re-nesting can escape crane-serialization deadlocks and cut Z1.  

**145.** [Optimal decomposition approach for solving large nesting and scheduling problems of additive manufacturing systems](https://www.semanticscholar.org/paper/Optimal-decomposition-approach-for-solving-large-of-Nascimento-Silva/55c649b6dc1dd458917d74f5181677b1b4b1a59f) (2024)  
*Paulo Jorge Nascimento, Cristóvão Silva, Carlos Henggeler Antunes, Samuel Moniz · European Journal of Operational Research, Vol. 317(1), pp. 92–110*  
- **Method:** Logic-based Benders decomposition (MIP+CP and pure CP variants); scheduling in master, nesting feasibility in sub-problem; solves instances 1–2 orders of magnitude larger than prior exact methods; minimizes cumulative tardiness.  
- **→ Z1 relevance:** Shows that Benders-separated crane-feasibility checks (sub-problem) with tardiness-driven sequencing (master) scale to production-size instances matching OGC problem scale.  

**146.** [A new branch-and-cut approach for integrated planning in additive manufacturing](https://arxiv.org/abs/2308.09468) (2024)  
*Benedikt Zipfel, Felix Tamke, Leopold Kuttner · European Journal of Operational Research (online 2024, arXiv 2308.09468)*  
- **Method:** Branch-and-cut via combinatorial Benders decomposition: scheduling master problem + orthogonal-packing-with-rotation feasibility sub-problem; state-of-the-art packing techniques accelerate sub-problem.  
- **→ Z1 relevance:** Packing sub-problem can be extended with crane-access (j≥k) feasibility checks, yielding an exact cut that prunes crane-blocking configurations and drives tardiness to zero.  

**147.** [Unrelated parallel batch processing machine scheduling with time requirements and two-dimensional packing constraints](https://www.sciencedirect.com/science/article/abs/pii/S0305054823003386) (2023)  
*(authors confirmed via ScienceDirect ISSN S0305054823003386) · Computers & Operations Research, Vol. 159*  
- **Method:** MILP model + ALNS with 11 removal and 7 insertion operators; Skyline and Open-Space packing patterns as sub-heuristics; minimizes total tardiness on unrelated parallel batch machines with release/due dates.  
- **→ Z1 relevance:** ALNS destroy-repair paradigm with embedded packing sub-heuristic is the closest architecture to our problem: swap blocks across bays, repack, check crane-access, update Z1.  
