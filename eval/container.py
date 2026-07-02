"""Run bash inside a SWE-bench instance's own Docker container.

Each Verified instance has a prebuilt image containing the repo's exact
environment (interpreter + frozen dependency versions) with the source at
/testbed. We start that image with the agent's working copy bind-mounted over
/testbed: the agent's file edits happen on the host (where diffs and telemetry
live), while its bash commands execute inside the container -- so running the
project's real test suite finally works, and the agent gets true feedback on
its edits.

The container is disposable (--rm): anything the agent installs or breaks dies
with it. Grading later uses a fresh, pristine container from the same image.

All docker invocations go through an injectable `runner` so the module is fully
testable offline.
"""
import subprocess
from pathlib import Path

# The container the current run's bash tool should exec into (None = no
# container; bash falls back to the host). Set by start()/stop(); the eval
# agent runs one instance at a time, so one slot is enough.
ACTIVE = None

BASH_TIMEOUT = 120  # seconds; test suites are slower than host one-liners


def _run(cmd: list) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed: {proc.stderr[-1000:]}")
    return proc.stdout


def image_for(instance_id: str) -> str:
    """Official prebuilt image for an instance. Docker Hub repo names can't
    contain double underscores, so SWE-bench publishes with `_1776_`."""
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def start(instance_id: str, work_dir: Path, runner=_run) -> str:
    """Start the instance's container with `work_dir` mounted over /testbed.
    Pulls the image on first use (cached in Docker's store afterwards).
    Returns the container id and marks it ACTIVE for the bash proxy."""
    global ACTIVE
    mount = f"{Path(work_dir).resolve().as_posix()}:/testbed"
    cid = runner([
        "docker", "run", "-d", "--rm",
        "-v", mount,
        "-w", "/testbed",
        image_for(instance_id),
        "sleep", "infinity",
    ]).strip()
    ACTIVE = cid
    return cid


def _exec_run(cmd: list, timeout: int) -> tuple:
    """Real executor for exec_bash: returns (output, returncode). Non-zero exit
    is a normal outcome (a failing test run), not an error."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return (None, None)  # signal timeout to the caller
    return ((proc.stdout + proc.stderr).strip(), proc.returncode)


def exec_bash(container_id: str, command: str, runner=None, timeout: int = BASH_TIMEOUT) -> str:
    """Run one shell command inside the container, in the repo's own
    environment (the images ship a conda env named `testbed`)."""
    script = f"source /opt/miniconda3/bin/activate testbed && cd /testbed && {command}"
    cmd = ["docker", "exec", container_id, "bash", "-c", script]
    if runner is not None:  # injectable path for tests
        return runner(cmd)

    output, returncode = _exec_run(cmd, timeout)
    if output is None:
        return (f"Error: command timed out after {timeout}s inside the container. "
                "Avoid long-running or interactive commands; scope test runs to "
                "the relevant files.")
    if len(output) > 20_000:                 # same cap as the host bash tool
        output = output[:20_000] + "\n...[truncated]"
    if returncode:
        output += f"\n(exit code {returncode})"
    return output or "(no output)"


def stop(container_id: str, runner=_run) -> None:
    """Remove the container (it is --rm'd anyway on stop). Clears ACTIVE."""
    global ACTIVE
    try:
        runner(["docker", "rm", "-f", container_id])
    finally:
        ACTIVE = None
