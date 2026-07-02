"""CLI + orchestration for the eval harness.

    python -m eval.run_eval --source local --n 5 --repeat 3
    python -m eval.run_eval --source local --id md2html__alerts
    python -m eval.run_eval --source local --agent fake-fixing --n 1   # token-free smoke

The agent-under-test is selectable: `--agent ep5` (default, the real reference
agent) or a fake adapter for token-free testing. Providers supply instances;
sampling picks which to run; the runner scores each; results.py records them.
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from eval.results import aggregate, append_scoreboard, apply_retention, write_manifest, write_summary
from eval.runner import run_instance
from eval.sampling import filter_pool, sample
from eval.tests.conftest import fixing_solver, noop_solver  # fake adapters live with the tests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_local_instances():
    from eval.targets.local import get_instances
    return get_instances()


def _load_instances(source):
    if source == "local":
        return load_local_instances()
    if source == "swebench":
        from eval.targets.swebench import get_instances
        return get_instances()  # deferred stub: raises with a clear message
    raise SystemExit(f"unknown source: {source}")


def _select_agent(name):
    if name == "fake-fixing":
        return fixing_solver, "fake-fixing"
    if name == "fake-noop":
        return noop_solver, "fake-noop"
    if name == "ep5":
        from eval.agent import solve  # imported lazily: only the real run needs it
        return solve, "ep5"
    raise SystemExit(f"unknown agent: {name}")


def _agent_git_sha():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main(argv=None):
    p = argparse.ArgumentParser(description="Run the reference agent over a pool of problems.")
    p.add_argument("--source", default="local", choices=["local", "swebench"])
    p.add_argument("--agent", default="ep5", help="ep5 | fake-fixing | fake-noop")
    p.add_argument("--n", type=int, default=1)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--id", dest="instance_id", default=None)
    p.add_argument("--difficulty", choices=["easy", "medium", "hard"], default=None,
                   help="filter by Verified's time-to-fix bucket before sampling")
    p.add_argument("--repo", default=None, help="filter by repo substring, e.g. flask")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model", default="(default)", help="recorded in the manifest/scoreboard")
    p.add_argument("--keep", choices=["none", "failures", "all"], default="failures")
    p.add_argument("--results-root", default="eval/results")
    p.add_argument("--timestamp", default=None, help="override batch id (tests use this)")
    args = p.parse_args(argv)

    solve, agent_label = _select_agent(args.agent)
    instances = filter_pool(_load_instances(args.source),
                            difficulty=args.difficulty, repo=args.repo)
    picked = sample(instances, n=args.n, seed=args.seed, instance_id=args.instance_id)
    if not picked:
        raise SystemExit("no instances selected (check --id / --difficulty / --repo)")

    results_root = Path(args.results_root)
    stamp = args.timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_dir = results_root / stamp
    batch_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for inst in picked:
        for k in range(args.repeat):
            label = inst.id if k == 0 else f"{inst.id}-run{k + 1}"
            print(f"[eval] {label}", flush=True)
            results.append(run_instance(inst, solve, batch_dir, run_label=label))

    agg = aggregate(results, repeat=args.repeat)
    write_summary(batch_dir, agg, results)
    write_manifest(batch_dir, {
        "timestamp": stamp, "agent": agent_label, "agent_git_sha": _agent_git_sha(),
        "model": args.model, "source": args.source, "n": args.n, "repeat": args.repeat,
        "seed": args.seed, "filters": {"difficulty": args.difficulty, "repo": args.repo},
        "instance_ids": [i.id for i in picked],
    })
    append_scoreboard(results_root, {
        "timestamp": stamp, "agent": agent_label, "model": args.model, "source": args.source,
        "n": len(picked), "repeat": args.repeat, "seed": args.seed,
        "pass_at_1": agg["pass_at_1"], "pass_at_k": agg["pass_at_k"],
        "mean_seconds": agg["mean_seconds"], "batch_dir": str(batch_dir),
    })
    apply_retention(batch_dir, results, keep=args.keep)

    print(f"[eval] pass@1={agg['pass_at_1']:.1%}  pass@k={agg['pass_at_k']:.1%}  -> {batch_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
