"""
capture.py — run a command and save everything it prints to a timestamped log.

Mirrors the command's output to your terminal live while also writing a copy to
a log directory, so a run can be reviewed or debugged later. Each line is
stamped with the time elapsed since the run started.

Cross-platform and project-agnostic: it runs whatever command you give it. With
no command it defaults to `python -u agent.py` in the current directory, which
is the common case for this repo. It uses the same interpreter that launched it
(sys.executable), so it stays inside your active virtual environment.

Examples:
    python ../../capture.py                     # run agent.py in the current dir
    python capture.py --cwd episodes/01-loop     # run agent.py in that dir
    python capture.py -- pytest -q               # run any command
    python capture.py --logdir notes -- python walkthrough.py

Output (written into the log directory, default <cwd>/logs):
    run-YYYYMMDD-HHMMSS.log    human-readable, each line prefixed [+12.34s]
    run-YYYYMMDD-HHMMSS.jsonl  one JSON object per line: {"t": 12.34, "text": "..."}
                               plus a leading "meta" record and trailing "end"
                               record (exit code + total duration).

The command is run unbuffered (PYTHONUNBUFFERED) so the live mirror and the log
stay in real time and in order.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_args():
    """Read the command line: an optional working directory, an optional log
    directory, and the command to run (everything after `--`)."""
    parser = argparse.ArgumentParser(description="Run a command and log its output.")
    parser.add_argument("--cwd", default=".", help="working directory to run in (default: current)")
    parser.add_argument("--logdir", default=None, help="where to write logs (default: <cwd>/logs)")
    parser.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="command to run; defaults to `python -u agent.py`",
    )
    return parser.parse_args()


def resolve_command(raw_command):
    """Turn the leftover command-line args into a command list. argparse leaves
    a leading `--` in place, so drop it. If nothing was given, default to
    running agent.py with the current interpreter."""
    command = list(raw_command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = [sys.executable, "-u", "agent.py"]
    return command


def make_log_paths(logs_dir: Path):
    """Build a fresh, collision-free pair of log filenames stamped with the
    current time, so re-running never overwrites a previous capture."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    plain_log = logs_dir / f"run-{stamp}.log"
    json_log = logs_dir / f"run-{stamp}.jsonl"
    return plain_log, json_log


def start_command(command, cwd: Path) -> subprocess.Popen:
    """Launch the command as a child process whose output we can read line by
    line as it is produced."""
    # Force the child to emit output unbuffered and in UTF-8, so the live mirror
    # and the saved log stay in step (and arrows/checkmarks survive).
    child_env = dict(os.environ)
    child_env["PYTHONUNBUFFERED"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"

    return subprocess.Popen(
        command,
        cwd=cwd,
        env=child_env,
        stdout=subprocess.PIPE,     # we capture stdout...
        stderr=subprocess.STDOUT,   # ...and fold stderr into it, so errors are logged too
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,                  # line-buffered on our side
    )


def main() -> int:
    args = parse_args()
    cwd = Path(args.cwd).resolve()
    command = resolve_command(args.command)
    logs_dir = Path(args.logdir).resolve() if args.logdir else cwd / "logs"

    plain_log, json_log = make_log_paths(logs_dir)
    printable_command = " ".join(command)
    print(f"[capture] running: {printable_command}  ->  {plain_log}\n", flush=True)

    plain_file = open(plain_log, "w", encoding="utf-8")
    json_file = open(json_log, "w", encoding="utf-8")

    def write_json_record(record: dict) -> None:
        """Append one JSON object as its own line, and flush so the file stays
        readable even mid-run."""
        json_file.write(json.dumps(record) + "\n")
        json_file.flush()

    # First JSONL line is metadata about the run.
    write_json_record({
        "type": "meta",
        "command": command,
        "cwd": str(cwd),
        "started": datetime.now().isoformat(timespec="seconds"),
    })

    start_time = time.monotonic()
    exit_code = 0
    process = start_command(command, cwd)

    try:
        # Read the command's output one line at a time, as it appears.
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            elapsed = round(time.monotonic() - start_time, 2)

            # 1) Mirror to our own terminal, unchanged, so you still watch it live.
            print(line, flush=True)

            # 2) Human-readable log: prefix each line with how long into the run it appeared.
            plain_file.write(f"[+{elapsed:>7.2f}s] {line}\n")
            plain_file.flush()

            # 3) Structured log: for later inspection and post-processing.
            write_json_record({"t": elapsed, "text": line})

        exit_code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        exit_code = process.wait()
        print("\n[capture] interrupted", flush=True)

    # Final JSONL line records how the run ended.
    duration = round(time.monotonic() - start_time, 2)
    write_json_record({"type": "end", "exit_code": exit_code, "duration_s": duration})

    plain_file.close()
    json_file.close()

    print(f"\n[capture] done in {duration}s (exit {exit_code}) -> {plain_log}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
