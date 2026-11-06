"""Quality gate: read the dbt data_quality_report and fail loudly if something is wrong.

Run it after `dbt build`. Exit code:
    0 = every check is ok / info / warn (warnings are printed)
    1 = at least one check has status "error", or the report cannot be read

Usage:
    python -m morocco_fx.quality [--db data/fx_rates.duckdb]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from morocco_fx.load import DB_PATH

REPORT_TABLE = "quality.data_quality_report"

logger = logging.getLogger("morocco_fx.quality")


def read_report(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = con.execute(
        f"SELECT check_name, metric_value, status, details FROM {REPORT_TABLE} ORDER BY check_order"
    ).fetchall()
    return [
        {"check_name": name, "metric_value": value, "status": status, "details": details}
        for name, value, status, details in rows
    ]


def evaluate(report: list[dict]) -> int:
    """Log every check and return the exit code (1 if any error, else 0)."""
    if not report:
        logger.error("The quality report is empty: run `dbt build` first.")
        return 1
    n_errors = 0
    for check in report:
        line = "%-38s %10s  %-5s  %s"
        args = (
            check["check_name"],
            f"{check['metric_value']:g}",
            check["status"],
            check["details"],
        )
        if check["status"] == "error":
            n_errors += 1
            logger.error(line, *args)
        elif check["status"] == "warn":
            logger.warning(line, *args)
        else:
            logger.info(line, *args)
    if n_errors:
        logger.error("%d quality check(s) failed.", n_errors)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail if the data quality report has errors.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="DuckDB file path")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if not args.db.exists():
        logger.error("Database not found: %s", args.db)
        return 1
    try:
        with duckdb.connect(str(args.db), read_only=True) as con:
            report = read_report(con)
    except duckdb.Error as exc:
        logger.error("Cannot read %s (did dbt build run?): %s", REPORT_TABLE, exc)
        return 1
    return evaluate(report)


if __name__ == "__main__":
    sys.exit(main())
