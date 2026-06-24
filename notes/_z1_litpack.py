# -*- coding: utf-8 -*-
"""One-off: load the haiku litsearch workflow result, dedupe, emit clean JSON + compact digest."""
import json, re, sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

src = Path(r"C:\Users\peter\AppData\Local\Temp\claude\C--claude-develop-OGC2026\d2fd2c5f-b5e4-436b-910d-7a7857ee558c\tasks\wnh8qx62g.output")
raw = src.read_text(encoding="utf-8")
# the file may be the raw JSON result, or wrapped; find first '{'
start = raw.find('{"topics"')
if start < 0:
    start = raw.find('{')
data = json.loads(raw[start:])
if "result" in data and isinstance(data["result"], dict):
    data = data["result"]
topics = data["topics"]

def norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:55]

seen, order = {}, []
for tp in topics:
    label = tp.get("topic", "")
    for p in tp.get("papers", []):
        k = norm(p.get("title", ""))
        if not k:
            continue
        if k in seen:
            seen[k]["_topics"].append(label)
            continue
        p["_topics"] = [label]
        seen[k] = p
        order.append(k)

papers = [seen[k] for k in order]
raw_count = sum(len(t.get("papers", [])) for t in topics)
print("RAW topics :", len(topics))
print("RAW papers :", raw_count)
print("UNIQUE     :", len(papers))
print()
print("=== per-topic counts ===")
for tp in topics:
    print(f"  {len(tp.get('papers',[])):2d}  {tp.get('topic','')[:78]}")
print()
print("=== DIGEST (unique) ===")
for i, p in enumerate(papers, 1):
    print(f"{i}. [{p.get('year','?')}] {p.get('title','')[:95]}")
    print(f"   M: {p.get('method','')[:135]}")
    print(f"   R: {p.get('relevance','')[:135]}")

out = Path(r"C:\claude-develop\OGC2026\notes\z1-papers-data.json")
out.write_text(json.dumps({"total": len(papers), "topics": topics, "papers": papers},
                          ensure_ascii=False, indent=1), encoding="utf-8")
print("\nWROTE", out, f"({out.stat().st_size} bytes)")
