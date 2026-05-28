"""
capture.py — run an episode's agent.py and save everything it prints to a log.

Mirrors the agent's output to your terminal live while also writing a
timestamped copy to <episode>/logs/, so you can review a run afterwards. Each
line is stamped with the time elapsed since the run started.

Cross-platform: pure Python, no shell pipes. Runs the same interpreter that
launched it (sys.executable), so it uses your active virtual environment.

Usage (from an episode directory):
    python ../../capture.py

Usage (from the code/ root, naming the episode):
    python capture.py episodes/01-loop

Output (written into <episode>/logs/, which is gitignored):
    run-YYYYMMDD-HHMMSS.log    human-readable, each line prefixed [+12.34s]
    run-YYYYMMDD-HHMMSS.jsonl  one JSON object per line: {"t": 12.34, "text": "..."}
                               plus a leading "meta" record and trailing "end"
                               record (exit code + total duration).

agent.py is run unbuffered so the live mirror and the log stay in real time and
in order. agent.py's relative paths (initial/, sandbox/, ../../.env) resolve as
if you'd run it directly, because we set cwd to the episode.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def find_episode_dir() -> Path:
    """Decide which episode to run: the path given as an argument, or the
    current directory if none was given."""
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve()
    return Path.cwd()


def make_log_paths(logs_dir: Path) -> tuple[Path, Path]:
    """Build a fresh, collision-free pair of log filenames stamped with the
    current time, so re-running never overwrites a previous capture."""
    logs_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    plain_log = logs_dir / f"run-{stamp}.log"
    json_log = logs_dir / f"run-{stamp}.jsonl"
    return plain_log, json_log


def start_agent(episode_dir: Path) -> subprocess.Popen:
    """Launch <episode_dir>/agent.py as a child process whose output we can
    read line by line as it is produced."""
    # Force the child to emit output unbuffered and in UTF-8, so the live
    # mirror and the saved log stay in step (and arrows/checkmarks survive).
    child_env = dict(os.environ)
    child_env["PYTHONUNBUFFERED"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"

    return subprocess.Popen(
        [sys.executable, "-u", "agent.py"],
        cwd=episode_dir,            # so agent.py's relative paths still work
        env=child_env,
        stdout=subprocess.PIPE,     # we capture stdout...
        stderr=subprocess.STDOUT,   # ...and fold stderr into it, so errors are logged too
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,                  # line-buffered on our side
    )


def main() -> int:
    episode_dir = find_episode_dir()
    agent_file = episode_dir / "agent.py"
    if not agent_file.is_file():
        sys.stderr.write(f"capture.py: no agent.py found in {episode_dir}\n")
        return 2

    plain_log, json_log = make_log_paths(episode_dir / "logs")
    episode_name = episode_dir.name
    print(f"[capture] running {episode_name}/agent.py  ->  logs/{plain_log.name}\n", flush=True)

    # Open both log files for the whole run.
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
        "episode": episode_name,
        "started": datetime.now().isoformat(timespec="seconds"),
        "agent": str(agent_file),
        "argv": sys.argv,
    })

    start_time = time.monotonic()
    exit_code = 0
    agent = start_agent(episode_dir)

    try:
        # Read the agent's output one line at a time, as it appears.
        for raw_line in agent.stdout:
            line = raw_line.rstrip("\n")
            elapsed = round(time.monotonic() - start_time, 2)

            # 1) Mirror to our own terminal, unchanged, so you still watch it live.
            print(line, flush=True)

            # 2) Human-readable log: prefix each line with how long into the run it appeared.
            plain_file.write(f"[+{elapsed:>7.2f}s] {line}\n")
            plain_file.flush()

            # 3) Structured log: for replay timing and LLM summarization.
            write_json_record({"t": elapsed, "text": line})

        exit_code = agent.wait()
    except KeyboardInterrupt:
        agent.terminate()
        exit_code = agent.wait()
        print("\n[capture] interrupted", flush=True)

    # Final JSONL line records how the run ended.
    duration = round(time.monotonic() - start_time, 2)
    write_json_record({"type": "end", "exit_code": exit_code, "duration_s": duration})

    plain_file.close()
    json_file.close()

    print(f"\n[capture] done in {duration}s (exit {exit_code}) -> logs/{plain_log.name}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
