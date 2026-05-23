"""
Episode 3 — Context

Adds rolling-summary compaction (history compressed when token usage crosses
a threshold) and a done tool (explicit TaskComplete signal, replacing the
naive stop from Ep 1). Both serve the same theme: making long-running tasks
reliable.

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
