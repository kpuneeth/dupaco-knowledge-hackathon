import sys
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from pathlib import Path
import solution as S
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots"))[-1:]: ks.ingest(s)
snap = ks._select_snapshot(None)
print(len(snap.fees), "fees")
for f in snap.fees:
    if any(k in f.label.lower() for k in ("stop", "wire", "official")): print(f.page.url[-30:], "|", f.label, "|", f.value, sorted(f.tokens))
for q in sys.argv[1:]:
    print(q, "->", S._answer_fee(snap, q))
