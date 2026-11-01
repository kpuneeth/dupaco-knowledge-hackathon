import sys
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from pathlib import Path
import solution as S
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots"))[-1:]: ks.ingest(s)
snap = ks._select_snapshot(None)
for q in sys.argv[1:]:
    print("####", q, S._query_terms(q))
    for sc, p in S._search_passages(snap, q, limit=6):
        print(f"  {sc:6.2f} a={p.page.authority} pub={p.page.published} {p.page.url[23:90]} | {p.text[:110]!r}")
