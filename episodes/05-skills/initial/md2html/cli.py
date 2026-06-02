"""md2html CLI entry point.

Usage:

    md2html INPUT_FILE [-o OUTPUT_FILE] [--stdout]
            [--no-extensions] [--extensions LIST]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, render
from .extensions import available_extensions, default_extensions, resolve_extensions


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="md2html",
        description="Convert a Markdown file to HTML.",
    )
    p.add_argument("input", metavar="INPUT_FILE", help="Path to a .md file.")
    out = p.add_mutually_exclusive_group()
    out.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT_FILE",
        help="Output .html path (default: replace .md with .html).",
    )
    out.add_argument(
        "--stdout",
        action="store_true",
        help="Write to stdout instead of a file.",
    )
    ext = p.add_mutually_exclusive_group()
    ext.add_argument(
        "--no-extensions",
        action="store_true",
        help="Disable all extensions (core markdown only).",
    )
    ext.add_argument(
        "--extensions",
        metavar="LIST",
        help=(
            "Comma-separated list of extensions to enable "
            f"(available: {', '.join(available_extensions())})."
        ),
    )
    p.add_argument("--version", action="version", version=f"md2html {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"md2html: input file not found: {in_path}", file=sys.stderr)
        return 2
    source = in_path.read_text(encoding="utf-8")

    if args.no_extensions:
        exts = []
    elif args.extensions:
        try:
            exts = resolve_extensions(args.extensions)
        except ValueError as e:
            print(f"md2html: {e}", file=sys.stderr)
            return 2
    else:
        exts = default_extensions()

    html = render(source, extensions=exts)

    if args.stdout:
        sys.stdout.write(html)
        if not html.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    out_path = Path(args.output) if args.output else in_path.with_suffix(".html")
    out_path.write_text(html + ("\n" if not html.endswith("\n") else ""), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
