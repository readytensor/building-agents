"""
Episode 5 — Orchestration

Multi-agent: a planner agent + executor agents spawned via a delegate(subtask)
tool on the parent. Minimal message-passing between them.

See ../../README.md and ../../../spec/md2html.md for context.
"""
import shutil
from pathlib import Path

INITIAL = Path("initial")
SANDBOX = Path("sandbox")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)

# TODO: implement
