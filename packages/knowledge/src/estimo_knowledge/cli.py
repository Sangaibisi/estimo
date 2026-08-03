"""CLI: `estimo-ledger-import <seed.csv|xlsx>` — seed-set import with a bad-row report."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from estimo_knowledge.importer import ImportReport, import_seed


async def _run(path: Path, taxonomy: set[str] | None, report_path: Path | None) -> int:
    database_url = os.environ.get("ESTIMO_DATABASE_URL")
    if not database_url:
        print("error: ESTIMO_DATABASE_URL is not set", file=sys.stderr)
        return 2
    engine = create_async_engine(database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            report: ImportReport = await import_seed(session, path, taxonomy=taxonomy)
    finally:
        await engine.dispose()
    print(report.summary())
    if report_path is not None:
        report_path.write_text(
            json.dumps(report.__dict__, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return 0 if report.imported > 0 or report.total_rows == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="estimo-ledger-import",
        description="Import a seed set (CSV/XLSX) into the estimate ledger.",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--taxonomy",
        help="Comma-separated known module names; unknown ones go to the review queue",
    )
    parser.add_argument("--report", type=Path, help="Write the JSON import report here")
    args = parser.parse_args()
    if not args.path.exists():
        parser.error(f"file not found: {args.path}")
    taxonomy = {m.strip() for m in args.taxonomy.split(",") if m.strip()} if args.taxonomy else None
    sys.exit(asyncio.run(_run(args.path, taxonomy, args.report)))


if __name__ == "__main__":
    main()
