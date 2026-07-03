"""Run the agent's actions inside a SWE-bench instance's own Docker container.

Each Verified instance has a prebuilt image containing the repo's exact
environment (interpreter + frozen dependency versions) with the source checked
out, installed, and built at /testbed. The agent works directly on that
checkout -- the canonical scaffold pattern (SWE-agent, OpenHands): bash and
the file tools all execute inside via docker exec, and the only thing that
ever leaves the container is text over exec stdout -- tool output while the
agent works, and the model_patch (capture_diff) when it finishes. Nothing is
mounted from or copied to the host.

The container is disposable (--rm): anything the agent installs or breaks dies
with it. Grading later uses a fresh, pristine container from the same image.

All docker invocations go through an injectable `runner` so the module is fully
testable offline.
"""
import json
import shlex
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


def start(instance_id: str, runner=_run) -> str:
    """Start the instance's container. The agent works directly on the image's
    own /testbed checkout: correct base state, dependencies installed, C
    extensions already built. Pulls the image on first use (cached in Docker's
    store afterwards). Returns the container id and marks it ACTIVE, which
    routes the agent's bash and file tools here."""
    global ACTIVE
    cid = runner([
        "docker", "run", "-d", "--rm",
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
    # The in-container coreutils `timeout` is the real limit. Timing out the
    # `docker exec` client host-side kills only the client -- the command
    # itself would keep running inside the container (the same orphan problem
    # the host bash tool solves with a process-tree kill), degrading every
    # later command. -k 5 follows the TERM with a KILL if the command ignores
    # it; the host-side timeout below is just a fallback for docker itself
    # wedging, so it fires later.
    script = (f"source /opt/miniconda3/bin/activate testbed && cd /testbed && "
              f"timeout -k 5 {timeout} bash -c {shlex.quote(command)}")
    cmd = ["docker", "exec", container_id, "bash", "-c", script]
    if runner is not None:  # injectable path for tests
        return runner(cmd)

    output, returncode = _exec_run(cmd, timeout + 15)
    if output is None or returncode == 124:  # 124 = `timeout` expired (killed the command)
        return (f"Error: command timed out after {timeout}s inside the container "
                "and was killed. Avoid long-running or interactive commands; "
                "scope test runs to the relevant files.")
    if len(output) > 20_000:                 # same cap as the host bash tool
        output = output[:20_000] + "\n...[truncated]"
    if returncode:
        output += f"\n(exit code {returncode})"
    return output or "(no output)"


def _fileops_source() -> str:
    """Source of the in-container file operations, read fresh so edits to
    container_fileops.py never need a process restart."""
    return (Path(__file__).with_name("container_fileops.py")).read_text(encoding="utf-8")


def fileop(container_id: str, op: str, kwargs: dict, runner=None, timeout: int = 60) -> str:
    """Run one file operation (read/write/edit/grep/list_files) against the
    container's /testbed, by piping container_fileops.py plus a single
    dispatch call over `docker exec -i python -`. Content travels on stdin
    (no shell quoting, no argv size limits). Uses the image's base conda
    python -- always modern -- rather than the testbed env, whose interpreter
    can be as old as the instance."""
    payload = json.dumps({"op": op, **kwargs})
    program = _fileops_source() + f'\nprint(dispatch(json.loads({json.dumps(payload)})), end="")\n'
    cmd = ["docker", "exec", "-i", container_id, "/opt/miniconda3/bin/python", "-"]
    if runner is not None:  # injectable path for tests
        return runner(cmd, program)
    try:
        proc = subprocess.run(cmd, input=program, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"Error: {op} timed out after {timeout}s."
    if proc.returncode:
        return f"Error: {op} failed in the container: {(proc.stderr or proc.stdout)[-1000:]}"
    return proc.stdout


# What never belongs in a model_patch: caches and build artifacts the agent's
# own exploration creates inside /testbed (pip install -e ., in-tree rebuilds).
_DIFF_EXCLUDES = [":(exclude)*.pyc", ":(exclude)__pycache__", ":(exclude)*.egg-info",
                  ":(exclude).eggs", ":(exclude)*.so", ":(exclude)build"]


def capture_diff(container_id: str, runner=_run) -> str:
    """The model_patch: everything the agent changed at /testbed since the
    image's base_commit, captured with one exec BEFORE teardown (the changes
    die with the container). Staging first makes new files show up in the
    diff; the patch text is the only artifact that leaves."""
    runner(["docker", "exec", container_id, "git", "-C", "/testbed", "add", "-A"])
    return runner(["docker", "exec", container_id, "git", "-C", "/testbed",
                   "diff", "--cached", "--", ".", *_DIFF_EXCLUDES])


def stop(container_id: str, runner=_run) -> None:
    """Remove the container (it is --rm'd anyway on stop). Clears ACTIVE."""
    global ACTIVE
    try:
        runner(["docker", "rm", "-f", container_id])
    finally:
        ACTIVE = None
