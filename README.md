# Knowledge system that knows what's true *now*

My submission for the Interface.ai knowledge hackathon. The solution lives in [`submission/`](submission/):

- `solution.py`: `build()` returns the system with `ingest`, `answer` and `conflicts`.
- `NOTES.md`: how it works and how it decides what's current.
- `requirements.txt`: empty. It uses the standard library only, needs **no API keys** and makes no network calls.

## Running it

The website snapshots are not in this repo, as the submission rules require. To run the scorer, copy the kit's `snapshots_zip/` folder into the repo root:

```bash
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

`harness/` and `eval/` are the unchanged copies from the kit.

## Results on the public set (Python 3.11)

| Pillar | Score |
|---|---|
| Accuracy | 0.910 |
| Consistency | 1.0 (multiplied by accuracy) |
| Speed | 1.0 (multiplied by accuracy). Each answer takes under 0.1s; ingesting all five snapshots takes about 3s. |
| Conflicts | 20 entries. No public gold exists, so these were checked against a hand-made list in `dev_tools/my_conflicts_gold.json`. |

## Development tools

[`dev_tools/`](dev_tools/) contains the scripts used while building the solution. Run them from the repo root:

- `show.py`: per-question results.
- `probe.py`: asks your own question sets. The `probes*.tsv` files are the reworded and extra questions used as regression checks.
- `probe_check.py`: scores `probes4.tsv`, which holds 126 reworded and "as of" questions with expected values (120 pass).
- `conflicts.py`: prints the `conflicts()` output.
- `dbg*.py`: debugging tools for fact matching, passage ranking and fees.
