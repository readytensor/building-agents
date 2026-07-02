# eval/ - reference-agent evaluation

Runs the reference coding agent over a pool of problems and reports how often it
resolves them, so we can see that it generalizes beyond any single example.

## Run it

Token-free smoke check of the harness (uses a fake agent, no API calls):

    python -m eval.run_eval --source local --agent fake-fixing --n 1

A real run of the reference agent over local md2html problems:

    python -m eval.run_eval --source local --n 5 --repeat 3

Useful flags:

- `--n N` how many instances to sample
- `--repeat K` run each sampled instance K times (for pass@k and variance)
- `--id <instance-id>` run one specific instance
- `--seed S` reproducible sampling
- `--keep {none,failures,all}` how much per-instance log detail to retain

## Results

Each run writes a timestamped batch under `eval/results/<timestamp>/`
(summary, per-instance verdicts and diffs) and appends one row to
`eval/results/scoreboard.jsonl` (rendered as `scoreboard.md`) so runs are easy
to compare. Verbose logs are kept only for failed instances by default.

## Tests

    python -m pytest eval/tests -q

The suite runs offline in a few seconds: it exercises the whole pipeline with
fake agents over a tiny synthetic repo, so it never calls an LLM.
