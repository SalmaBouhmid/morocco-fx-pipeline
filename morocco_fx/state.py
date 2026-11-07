"""Save and restore the pipeline data as compact Parquet files.

In the cloud (GitHub Actions) every run starts on an empty machine. So:
  - `restore` rebuilds the `rates` table from the previous run's rates.parquet,
  - the pipeline then loads only the missing days (watermark) and runs dbt,
  - `export` writes the source table and the dashboard tables as Parquet files.
The workflow keeps these files on a separate `data` branch, rewritten each day as ONE
commit (force-push), so the repository does not grow without end.

Usage:
    python -m morocco_fx.state restore --from data/export
    python -m morocco_fx.state export  --to   data/export
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from morocco_fx import load

EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "export"
RATES_FILE = "rates.parquet"

# table in DuckDB -> file name. rates.parquet is the source of truth for the next run;
# the others are what the dashboard reads.
EXPORT_TABLES = {
    "main.rates": RATES_FILE,
    "marts.fct_daily_rates": "fct_daily_rates.parquet",
    "marts.fct_monthly_rates": "fct_monthly_rates.parquet",
    "marts.fct_volatility": "fct_volatility.parquet",
    "marts.mad_basket_index": "mad_basket_index.parquet",
    "quality.data_quality_report": "data_quality_report.parquet",
    "quality.dq_large_moves": "dq_large_moves.parquet",
    "quality.dq_calendar_gaps": "dq_calendar_gaps.parquet",
    "quality.dq_currency_coverage": "dq_currency_coverage.parquet",
}

logger = logging.getLogger("morocco_fx.state")


def _sql_path(path: Path) -> str:
    """Path written inside a SQL string: forward slashes, quotes escaped."""
    return path.resolve().as_posix().replace("'", "''")


def restore_rates(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    """Insert the rows of a previous rates.parquet into the rates table.

    Rows already in the table are kept as they are (ON CONFLICT DO NOTHING), so running
    restore twice changes nothing.
    """
    before = con.execute("SELECT count(*) FROM rates").fetchone()[0]
    con.execute(
        "INSERT INTO rates (rate_date, base, currency, rate, loaded_at) "
        "SELECT rate_date, base, currency, rate, loaded_at "
        f"FROM read_parquet('{_sql_path(parquet_path)}') "
        "ON CONFLICT (rate_date, currency) DO NOTHING"
    )
    added = con.execute("SELECT count(*) FROM rates").fetchone()[0] - before
    logger.info(
        "Restored %d rows from %s. Table now: %s", added, parquet_path, load.table_summary(con)
    )
    return added


def export_tables(
    con: duckdb.DuckDBPyConnection, out_dir: Path, tables: dict[str, str] = EXPORT_TABLES
) -> list[Path]:
    """Write each table as a zstd-compressed Parquet file (overwriting the old one)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for table, file_name in tables.items():
        path = out_dir / file_name
        con.execute(
            f"COPY (SELECT * FROM {table}) TO '{_sql_path(path)}' "
            "(FORMAT parquet, COMPRESSION zstd)"
        )
        logger.info("Exported %s -> %s (%d KB)", table, path, path.stat().st_size // 1024)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save / restore pipeline data as Parquet.")
    sub = parser.add_subparsers(dest="command", required=True)
    restore = sub.add_parser("restore", help="rebuild the rates table from rates.parquet")
    restore.add_argument("--from", dest="src", type=Path, default=EXPORT_DIR)
    export = sub.add_parser("export", help="write rates + dashboard tables as Parquet")
    export.add_argument("--to", dest="dst", type=Path, default=EXPORT_DIR)
    parser.add_argument("--db", type=Path, default=load.DB_PATH, help="DuckDB file path")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s"
    )

    try:
        con = load.connect(args.db)
        try:
            if args.command == "restore":
                source = args.src / RATES_FILE
                if not source.exists():
                    logger.warning("No %s: first run, the load step will backfill.", source)
                    return 0
                restore_rates(con, source)
            else:
                export_tables(con, args.dst)
        finally:
            con.close()
    except duckdb.Error as exc:
        logger.error("State %s failed: %s", args.command, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
