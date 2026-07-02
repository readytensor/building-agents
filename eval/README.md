# eval/ - reference-agent evaluation

Runs the reference coding agent over a pool of problems and reports how often it
resolves them, so we can see that it generalizes beyond any single example.

## Run it

Token-free smoke check of the harness (fake agents over a synthetic repo, no
API calls):

    python -m pytest eval/tests -q

A real run of the reference agent over SWE-bench Verified instances, grading
each sample officially right after it runs (needs `pip install datasets`, plus
Docker and WSL for the per-instance containers and grading):

    python -m eval.run_eval --source swebench --n 5 --grade

Useful flags:

- `--n N` how many instances to sample
- `--id <instance-id>` run one specific instance
- `--difficulty {easy,medium,hard}` filter by Verified's time-to-fix bucket
- `--grade` officially grade each sample right after it runs (solve, grade,
  next sample), so a broken setup surfaces at the first sample
- `--repeat K` run each sampled instance K times (for pass@k and variance)
- `--seed S` reproducible sampling
- `--keep {none,failures,all}` how much per-instance log detail to retain

The `local` provider (`--source local`) is md2html-task scaffolding: its
`DEFAULT_SPECS` list in `eval/targets/local.py` is empty until real md2html
instances are seeded, so it currently selects no instances. The test suite
exercises it with synthetic specs.

## Results

Each run writes a timestamped batch under `eval/results/<timestamp>/`
(summary, per-instance verdicts and diffs) and appends one row to
`eval/results/scoreboard.jsonl` (rendered as `scoreboard.md`) so runs are easy
to compare. Verbose logs are kept only for failed instances by default.

## Tests

    python -m pytest eval/tests -q

The suite runs offline in a few seconds: it exercises the whole pipeline with
fake agents over a tiny synthetic repo, so it never calls an LLM.
