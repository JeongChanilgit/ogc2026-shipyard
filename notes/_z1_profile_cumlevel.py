"""Profile the cum_level re-decode hot path on a saved layout."""
import sys, json, cProfile, pstats, io, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
sys.stdout.reconfigure(encoding="utf-8")
import myalgorithm as M
from utils import Bay
name=sys.argv[1] if len(sys.argv)>1 else "prob_14"
solp=sys.argv[2] if len(sys.argv)>2 else f"results/_sol_{name.replace('prob_','p')}.json"
prob=json.load(open(ROOT/'instances'/'train'/f'{name}.json'))
sol=json.load(open(ROOT/solp))
bays=[Bay.from_dict(d,i) for i,d in enumerate(prob['bays'])]
_,results,_=M._results_from_solution(prob,sol)
pr=cProfile.Profile()
t=time.time()
pr.enable()
cand=M._cumulative_leveled_redecode_verified(prob,bays,results,deadline=time.monotonic()+40,alpha=0.9)
pr.disable()
dt=time.time()-t
print(f"{name}: cum_level wall={dt:.1f}s cand={'sol' if cand else 'None'}")
s=io.StringIO(); ps=pstats.Stats(pr,stream=s).sort_stats('cumulative')
ps.print_stats(20)
print("\n".join(s.getvalue().splitlines()[:32]))
print("=== by tottime ===")
s2=io.StringIO(); ps2=pstats.Stats(pr,stream=s2).sort_stats('tottime'); ps2.print_stats(15)
print("\n".join(s2.getvalue().splitlines()[4:22]))
