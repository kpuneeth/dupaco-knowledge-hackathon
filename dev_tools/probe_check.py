"""Scored probes: question<TAB>as_of<TAB>must(|-sep)<TAB>must_not(|-sep, or R = should refuse)."""
import sys
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots, load_submission
from scoring import contains, REFUSAL_RE, _numbers
from pathlib import Path
ks = load_submission(Path("submission"))
for s in load_snapshots(Path("snapshots")): ks.ingest(s)
verbose = "-v" in sys.argv
ok = n = 0
for line in open(sys.argv[1]):
    if not line.strip(): continue
    c = (line.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
    q, as_of = c[0], c[1] or None
    must = [x for x in c[2].split("|") if x]
    a = ks.answer(q, as_of)
    if c[3] == "R":
        good = (not a.confident or bool(REFUSAL_RE.search(a.text))) and not _numbers(a.text)
        why = "should refuse"
    else:
        nots = [x for x in c[3].split("|") if x]
        miss = [m for m in must if not contains(a.text, m)]
        trap = [t for t in nots if contains(a.text, t)]
        good = not miss and not trap
        why = f"miss={miss} trap={trap}"
    n += 1; ok += good
    if not good or verbose:
        print(f"{'OK ' if good else 'FAIL'} {q} [{as_of}] {'' if good else why}\n     -> {'' if a.confident else '(nc) '}{a.text[:260]!r}\n     src: {[x.url[23:] for x in a.sources][:3]}")
print(f"\n{ok}/{n} passed")
