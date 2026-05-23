"""
Episode 2 — Tools

Adds a few more general primitives (read, write, grep), a tiny @tool/schema
helper to remove the boilerplate from Ep 1, and "skills" as named Python
helpers composed from those primitives.

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
