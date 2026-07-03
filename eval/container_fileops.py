"""File operations executed INSIDE a SWE-bench instance container.

The harness never imports this module at agent runtime. eval/container.py
sends its source over `docker exec -i <cid> python -` (stdin), with one
trailing `dispatch(...)` call appended, so each operation runs inside the
container against its own /testbed checkout -- the canonical scaffold
pattern: the workspace lives in the container, and only text crosses the
boundary.

Semantics mirror the episodes' host-side file tools (episodes/05-skills/
tools.py) exactly -- same outputs, same error strings -- so the model sees no
difference between a local host run and a container run.

It is also a plain importable module, which is how the offline tests exercise
it: dispatch(payload, root=some_tmp_dir).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path("/testbed")

# Same skip set as the episodes' tools.py: never task content, and on big
# repos this junk would otherwise eat the 200-file / 50-match output caps.
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", ".ruff_cache",
             "build", "dist", "node_modules", ".tox", ".eggs"}


def _safe_path(root: Path, path: str) -> Path:
    """Resolve `path` inside root. The agent sees container paths, so both
    "/testbed/x/y.py" (copied from tracebacks and shell output) and plain
    relative paths are accepted. Raises if the result escapes root."""
    if path == "/testbed" or path == str(root):
        path = "."
    elif path.startswith("/testbed/"):
        path = path[len("/testbed/"):]
    resolved = (root / path).resolve()
    resolved.relative_to(root.resolve())  # raises ValueError if outside
    return resolved


def list_files(root: Path, path: str = ".") -> str:
    top = _safe_path(root, path)
    if top.is_file():
        return str(top.relative_to(root.resolve()))
    files = []
    for p in sorted(top.rglob("*")):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.parts):
            files.append(str(p.relative_to(root.resolve())))
            if len(files) >= 200:
                files.append("... (truncated at 200 files)")
                break
    return "\n".join(files) if files else "(no files)"


def read(root: Path, path: str, offset: int = 1, limit: int = 0) -> str:
    p = _safe_path(root, path)
    if not p.exists():
        return f"Error: {path} does not exist."
    if p.is_dir():
        return f"Error: {path} is a directory. Use bash to list its contents."
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    numbered = [f"{i+1:5d}\t{line}" for i, line in enumerate(lines)]
    start = max(offset, 1) - 1
    end = start + limit if limit > 0 else len(numbered)
    selected = numbered[start:end]
    if not selected:
        return f"Error: {path} has {len(lines)} lines; offset {offset} is past the end."
    if len(selected) < len(lines):
        selected.append(f"(showing lines {start + 1}-{start + len(selected)} of {len(lines)})")
    return "\n".join(selected)


def write(root: Path, path: str, content: str) -> str:
    p = _safe_path(root, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}."


def edit(root: Path, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    p = _safe_path(root, path)
    if not p.exists():
        return f"Error: {path} does not exist."
    if p.is_dir():
        return f"Error: {path} is a directory."
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {path}."
    if count > 1 and not replace_all:
        return f"Error: old_string appears {count} times in {path}; pass replace_all=true to replace all, or add more context to make it unique."
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"Replaced {count} occurrence(s) in {path}."


def grep(root: Path, pattern: str, path: str = ".") -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    top = _safe_path(root, path)
    if top.is_file():
        files = [top]
    else:
        files = [p for p in top.rglob("*")
                 if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)]
    results = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(root.resolve())
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue  # skip binary / unreadable
    return "\n".join(results) if results else f"No matches for {pattern!r}."


_OPS = {"list_files": list_files, "read": read, "write": write, "edit": edit, "grep": grep}


def dispatch(payload: dict, root: Path = ROOT) -> str:
    """Run one operation described by {"op": name, **kwargs}. Errors come back
    as strings -- the same convention the agent loop uses for tool failures."""
    payload = dict(payload)
    op = payload.pop("op")
    try:
        return _OPS[op](root, **payload)
    except Exception as e:
        return f"Error executing {op}: {type(e).__name__}: {e}"


if __name__ == "__main__" and len(sys.argv) > 1:  # direct CLI use; the piped
    print(dispatch(json.loads(sys.argv[1])), end="")  # form appends its own call
