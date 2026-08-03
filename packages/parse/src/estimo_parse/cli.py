"""CLI: `estimo-parse <brd.docx>` → parsed requirements table as JSON on stdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from estimo_parse.segment import parse_brd


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="estimo-parse",
        description="Parse a BRD (.docx) into a stable-ID requirements table (JSON).",
    )
    parser.add_argument("path", type=Path, help="Path to the .docx BRD")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    if not args.path.exists():
        parser.error(f"file not found: {args.path}")
    try:
        parsed = parse_brd(args.path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(parsed.model_dump_json(indent=args.indent))


if __name__ == "__main__":
    main()
