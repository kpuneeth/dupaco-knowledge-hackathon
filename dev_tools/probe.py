import sys, json, time
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from pathlib import Path
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots")): ks.ingest(s)
qs = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
for row in qs:
    q, as_of = row[0], (row[1] if len(row) > 1 and row[1] else None)
    a = ks.answer(q, as_of)
    print(f"Q: {q}  [as_of={as_of}]\n   -> {'' if a.confident else '(not confident) '}{a.text[:230]}\n   src: {[x.url[23:] for x in a.sources][:3]}")
