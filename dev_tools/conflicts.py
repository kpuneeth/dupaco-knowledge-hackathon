"""Print conflicts() output: python3 dev_tools/conflicts.py [filter-regex]"""
import sys, re, time
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from pathlib import Path
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots")): ks.ingest(s)
t = time.time(); cs = ks.conflicts(); el = time.time() - t
pat = re.compile(sys.argv[1], re.I) if len(sys.argv) > 1 else None
for c in cs:
    if pat and not pat.search(c.topic):
        continue
    print(f"- {c.topic}\n    values={c.values}\n    resolution={c.resolution}\n    {c.reason}")
print(len(cs), "conflicts", f"({el:.2f}s)")
