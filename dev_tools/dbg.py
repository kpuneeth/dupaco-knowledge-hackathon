import sys
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from pathlib import Path
import solution as S
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots")): ks.ingest(s)
snap = ks._select_snapshot(sys.argv[2] if len(sys.argv) > 2 else None)
q = S._parse_query(sys.argv[1]); print(q.terms, q.term_months)
for sc, mis, f in sorted(S._match_facts(snap, q), key=lambda x: -x[0])[:80]:
    print(round(sc,2), mis, f.page.authority, f.page.url[23:], "|", f.parent, "|", f.section, "|", f.label, f.values)
