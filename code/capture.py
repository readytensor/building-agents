"""
capture.py — run a command and save everything it prints to a per-run log folder.

Mirrors the command's output to your terminal live while also writing a copy to
a fresh per-run folder, so a run can be reviewed or debugged later and earlier
runs are never overwritten. Each line is stamped with the time elapsed since the
run started.

Cross-platform and project-agnostic: it runs whatever command you give it. With
no command it defaults to `python -u agent.py` in the current directory, which
is the common case for this repo. It uses the same interpreter that launched it
(sys.executable), so it stays inside your active virtual environment.

Examples:
    python ../../capture.py                      # run agent.py in the current dir
    python capture.py --cwd episodes/01-loop      # run agent.py in that dir
    python capture.py -- pytest -q                # run any command

Each run creates a folder <logdir>/<timestamp>/ (default <cwd>/logs/) containing:
    terminal.log     human-readable, each line prefixed [+12.34s]
    terminal.jsonl   one JSON object per line: {"t": 12.34, "text": "..."}
                     plus a leading "meta" record and a trailing "end" record.

Any files named with --collect that the command produced (default:
tool_calls.jsonl) are moved into the run folder, so each run's outputs stay
together and a fixed-name file is preserved per run instead of being overwritten.

The command is run unbuffered (PYTHONUNBUFFERED) so the live mirror and the log
stay in real time and in order.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_args():
    """Read the command line: an optional working directory, an optional log
    directory, the artifact files to collect, and the command to run."""
    parser = argparse.ArgumentParser(description="Run a command and log its output to a per-run folder.")
    parser.add_argument("--cwd", default=".", help="working directory to run in (default: current)")
    parser.add_argument("--logdir", default=None, help="where run folders are created (default: <cwd>/logs)")
    parser.add_argument(
        "--collect", action="append", default=None,
        help="a file the command writes that should be moved into the run folder; "
             "repeatable (default: tool_calls.jsonl)",
    )
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


def collect_artifacts(names, cwd: Path, run_dir: Path) -> None:
    """Move any of the named files the command produced into this run's folder.
    A fixed-name output like tool_calls.jsonl is thus preserved per run instead
    of being overwritten by the next run. Files that weren't produced are
    silently skipped."""
    for name in names:
        produced = cwd / name
        if produced.exists():
            shutil.move(str(produced), str(run_dir / name))
            print(f"[capture] collected {name}", flush=True)


def main() -> int:
    args = parse_args()
    cwd = Path(args.cwd).resolve()
    command = resolve_command(args.command)
    logs_dir = Path(args.logdir).resolve() if args.logdir else cwd / "logs"
    collect = args.collect if args.collect is not None else ["tool_calls.jsonl"]

    # Each run gets its own timestamped folder, so runs never overwrite each
    # other. If two runs start in the same second, add a -2, -3, ... suffix so
    # rapid back-to-back runs still get distinct folders.
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = logs_dir / run_id
    suffix = 2
    while run_dir.exists():
        run_dir = logs_dir / f"{run_id}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    plain_log = run_dir / "terminal.log"
    json_log = run_dir / "terminal.jsonl"

    printable_command = " ".join(command)
    print(f"[capture] running: {printable_command}  ->  {run_dir}\n", flush=True)

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
        "run_id": run_id,
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

    # Gather the command's own output files into this run's folder.
    collect_artifacts(collect, cwd, run_dir)

    print(f"\n[capture] done in {duration}s (exit {exit_code}) -> {run_dir}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
