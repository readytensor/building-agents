"""
Episode 4 — Planning & Reflection

Adds a lightweight plan step before the loop (agent writes a TODO scratchpad
it can refer to and revise) and a reflect step triggered on tool error or
repeated identical tool calls (forces the agent to pause and reconsider).

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
