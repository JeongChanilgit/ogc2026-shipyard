import sys, json, collections
sys.argv=["x"]
import v5_solver as V
import utils
data=json.load(open("C:/claude-develop/OGC2026/instances/train/prob_4.json",encoding="utf-8"))
import cpsat_guideline as cg
blocks=data["blocks"]; bays=data["bays"]; N=len(blocks); m=len(bays)
dim=[(b["width"],b["height"]) for b in bays]
g=cg.cpsat_guideline(data, time_s=6.0); assign=list(g)
br={}
for j in range(m):
    ids=[i for i in range(N) if assign[i]==j]
    if ids: br[j]=V.greedy_bay(data, dim[j][0], dim[j][1], [], ids)
# checks BEFORE step2
allids=[r["id"] for j in br for r in br[j]]
dup=[k for k,c in collections.Counter(allids).items() if c>1]
missing=[i for i in range(N) if i not in set(allids)]
print("after greedy: placed",len(allids),"of",N,"dup",dup[:10],"missing",missing[:10])
bad=[(r["id"],r["entry"],r["exit"]) for j in br for r in br[j] if r["exit"]<=r["entry"]]
print("entry>=exit recs:", bad[:10])
obj,r=V.evalu(data,br)
print("greedy-only feasible obj:",obj,"viol:",(r.get("violations") or [])[:4])
# now step2
br2=V.step2_all if False else None
for j in list(br.keys()):
    br[j]=V.step2_bay(data,j,br[j],8.0)
allids=[x["id"] for j in br for x in br[j]]
dup=[k for k,c in collections.Counter(allids).items() if c>1]
missing=[i for i in range(N) if i not in set(allids)]
print("after step2: placed",len(allids),"dup",dup[:10],"missing",missing[:10])
bad=[(x["id"],x["entry"],x["exit"]) for j in br for x in br[j] if x["exit"]<=x["entry"]]
print("entry>=exit after step2:", bad[:10])
obj,r=V.evalu(data,br)
print("after step2 feasible obj:",obj,"stage",r.get("stage"),"viol:",(r.get("violations") or [])[:6])
