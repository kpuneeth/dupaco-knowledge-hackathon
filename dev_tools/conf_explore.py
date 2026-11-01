"""Explore rate-fact identities across pages/snapshots to design conflicts()."""
import sys, re
from collections import defaultdict
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from pathlib import Path
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots")): ks.ingest(s)

def metric(h):
    h = h.lower()
    return "apy" if "apy" in h else "apr" if "apr" in h else "rate" if h else "?"

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower().replace("months", "month"))

groups = defaultdict(list)
for snap in ks.snapshots:
    for f in snap.facts:
        hs = [metric(h) for h, _ in f.values]
        for i, (h, v) in enumerate(f.values):
            m = hs[i] if hs[i] != "?" else f"#{i}/{len(hs)}"
            groups[(norm(f.section), norm(f.label), m)].append((snap.taken_on, f.page.url[23:], v))
mode = sys.argv[1] if len(sys.argv) > 1 else "multi"
n = 0
for k, obs in sorted(groups.items()):
    vals = sorted({v for _, _, v in obs})
    if len(vals) > 1:
        n += 1
        if mode == "multi":
            print(k, vals)
            for o in sorted(set(obs)): print("     ", o)
print(n, "multi-valued groups of", len(groups))
