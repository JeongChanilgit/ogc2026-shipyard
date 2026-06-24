#!/usr/bin/env bash
# Across-budget validation matrix for OGC_ADAPT_DECODE.
# Runs prob_{1,6,20} x tl{60,300} x config{off,adaptive}, emits a TSV table.
set -u
cd C:/claude-develop/OGC2026
OUT=tools/_adapt_matrix2.tsv
TMP=tools/_adapt_run.out
PARSE=tools/_adapt_parse.py
cat > "$PARSE" <<'PY'
import sys, json
inst, tl, cfg, path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
lines = [l for l in open(path, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
out = "PARSE_ERR\tno-json\t-\t-\t-"
for l in reversed(lines):
    s = l.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            d = json.loads(s)
            out = f"{d.get('feasible')}\t{d.get('obj1')}\t{d.get('obj2')}\t{d.get('obj3')}\t{d.get('elapsed')}"
            break
        except Exception as e:
            out = f"PARSE_ERR\t{e!r}\t-\t-\t-"
            break
print(f"{inst}\t{tl}\t{cfg}\t{out}")
PY
echo -e "instance\ttl\tconfig\tfeasible\tobj1\tobj2\tobj3\twall" > "$OUT"
run() {
  local inst="$1" tl="$2" cfg="$3" envset="$4"
  env $envset conda run -n ogc2025 python tools/run_solver_once.py \
      "instances/train/$inst.json" --solver our --timelimit "$tl" > "$TMP" 2>/dev/null
  python "$PARSE" "$inst" "$tl" "$cfg" "$TMP" >> "$OUT"
}
for inst in prob_1 prob_6 prob_20; do
  for tl in 60 300; do
    run "$inst" "$tl" "off"      "OGC_ADAPT_DECODE=0"
    run "$inst" "$tl" "adaptive" ""
  done
done
echo "DONE" >> "$OUT"
