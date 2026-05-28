"""
run.py — run an episode's agent as a fresh, self-contained "run".

This is the repo's harness around the episodes. Each invocation:
  1. creates a new run folder, logs/<timestamp>/ (runs never overwrite),
  2. runs the episode's agent,
  3. moves the agent's tool_calls.jsonl into that run folder,
  4. and, with --capture, also records the terminal output there (via capture.py).

Collecting runs this way makes it easy to compare how the agent's path and
tool-call count vary from one run to the next on the same task.

The episodes stay self-contained — `python agent.py` still works on its own.
run.py is just the outer harness; it can run any episode.

    python ../../run.py                       # run agent.py in the current folder
    python run.py --cwd episodes/01-loop       # run a specific episode from code/
    python ../../run.py --capture             # also record terminal output
"""
import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import capture  # sibling module; sys.path[0] is run.py's folder, so this resolves


def make_run_dir(logs_dir: Path) -> Path:
    """Create a fresh run folder named by the current time. If two runs start in
    the same second, add a -2, -3, ... suffix so neither is overwritten."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = logs_dir / run_id
    suffix = 2
    while run_dir.exists():
        run_dir = logs_dir / f"{run_id}-{suffix}"
        suffix += 1
    run_dir.mkdir()
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an episode's agent as a fresh, recorded run.")
    parser.add_argument("--cwd", default=".", help="episode directory to run in (default: current)")
    parser.add_argument("--logdir", default=None, help="where run folders are created (default: <cwd>/logs)")
    parser.add_argument("--capture", action="store_true", help="also record terminal output into the run folder")
    parser.add_argument(
        "--collect", action="append", default=None,
        help="agent output file(s) to move into the run folder (default: tool_calls.jsonl)",
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="command to run; defaults to `python -u agent.py`",
    )
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    command = capture.resolve_command(args.command)
    logs_dir = Path(args.logdir).resolve() if args.logdir else cwd / "logs"
    collect = args.collect if args.collect is not None else ["tool_calls.jsonl"]

    run_dir = make_run_dir(logs_dir)
    print(f"[run] {' '.join(command)}  ->  {run_dir}\n", flush=True)

    if args.capture:
        # capture.py records the terminal into the run folder (and mirrors live).
        exit_code = capture.run_and_capture(command, cwd, run_dir)
    else:
        # No capture: let the command print straight to this terminal.
        exit_code = subprocess.run(command, cwd=cwd).returncode

    # Move the agent's own output files into this run's folder, so a fixed-name
    # file like tool_calls.jsonl is preserved per run instead of being overwritten.
    for name in collect:
        produced = cwd / name
        if produced.exists():
            shutil.move(str(produced), str(run_dir / name))
            print(f"[run] collected {name}", flush=True)

    print(f"\n[run] done (exit {exit_code}) -> {run_dir}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
