"""Load step: put the raw API answers into one DuckDB file, incrementally and idempotently.

- Incremental: we read the last loaded date (the "watermark") and only ask the API for
  the days from that date onwards.
- Idempotent: rows are upserted on the key (rate_date, currency). Loading the same data
  twice gives exactly the same table, without duplicates.
- Backfill: reload the whole history from 1999-01-04 (the first BAM date in the API).

Usage:
    python -m morocco_fx.load update     # daily run: only the missing days
    python -m morocco_fx.load backfill   # full history 1999-01-04 -> today
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests

from morocco_fx import extract

# Same variable as in transform/profiles.yml, so Python and dbt use the same file.
DB_PATH = Path(
    os.environ.get(
        "FX_DUCKDB_PATH", Path(__file__).resolve().parent.parent / "data" / "fx_rates.duckdb"
    )
)

logger = logging.getLogger("morocco_fx.load")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rates (
    rate_date DATE    NOT NULL,
    base      VARCHAR NOT NULL,
    currency  VARCHAR NOT NULL,
    rate      DOUBLE  NOT NULL,
    loaded_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (rate_date, currency)
)
"""

# Upsert: insert each new row, or update it if (rate_date, currency) already exists.
# `incoming` is a pandas DataFrame that DuckDB reads directly (fast, no row-by-row insert).
UPSERT_SQL = """
INSERT INTO rates (rate_date, base, currency, rate)
SELECT CAST(date AS DATE), base, quote, rate FROM incoming
ON CONFLICT (rate_date, currency) DO UPDATE SET
    base = excluded.base,
    rate = excluded.rate,
    loaded_at = now()
"""


def connect(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) the DuckDB file and make sure the table exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(CREATE_TABLE_SQL)
    return con


def get_watermark(con: duckdb.DuckDBPyConnection) -> date | None:
    """Return the last loaded date, or None if the table is empty."""
    return con.execute("SELECT max(rate_date) FROM rates").fetchone()[0]


def prepare_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Validate API rows and keep the ones to load (shared by DuckDB and PostgreSQL).

    The API also returns the line MAD -> MAD = 1.0 every day: it is not an exchange
    rate, so we skip it. The same (date, currency) twice is refused.
    """
    incoming = pd.DataFrame(extract.validate_rates(rows), columns=["date", "base", "quote", "rate"])
    incoming = incoming[incoming["quote"] != incoming["base"]].reset_index(drop=True)
    if incoming.duplicated(["date", "quote"]).any():
        raise extract.ExtractError("API answer contains the same (date, currency) twice")
    return incoming


def upsert_rates(con: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]]) -> int:
    """Upsert API rows into the rates table. Returns the number of rows sent."""
    incoming = prepare_rows(rows)
    con.execute("BEGIN TRANSACTION")
    try:
        con.register("incoming", incoming)
        con.execute(UPSERT_SQL)
        con.unregister("incoming")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(incoming)


def load_raw_file(con: duckdb.DuckDBPyConnection, raw_path: Path) -> int:
    """Read a raw JSON file (written by the extract step) and upsert it."""
    rows = json.loads(raw_path.read_text(encoding="utf-8"))
    return upsert_rates(con, rows)


def table_summary(con: duckdb.DuckDBPyConnection) -> str:
    n_rows, n_days, n_currencies, first, last = con.execute(
        "SELECT count(*), count(DISTINCT rate_date), count(DISTINCT currency), "
        "min(rate_date), max(rate_date) FROM rates"
    ).fetchone()
    return f"{n_rows} rows, {n_days} days, {n_currencies} currencies, from {first} to {last}"


def run_update(
    con: duckdb.DuckDBPyConnection,
    *,
    session: requests.Session | None = None,
    raw_dir: Path = extract.RAW_DIR,
) -> int:
    """Daily incremental load: ask the API only from the watermark onwards.

    We start AT the watermark (not the day after): the API always has that day, so the
    answer is never empty, and the upsert makes the overlap harmless.
    """
    watermark = get_watermark(con)
    if watermark is None:
        logger.info("Empty table: no watermark, starting from %s", extract.FIRST_AVAILABLE_DATE)
        start = extract.FIRST_AVAILABLE_DATE
    else:
        logger.info("Watermark (last loaded date): %s", watermark)
        start = watermark
    raw_path = extract.extract_history(start, session=session, raw_dir=raw_dir)
    count = load_raw_file(con, raw_path)
    logger.info("Upserted %d rows. Table now: %s", count, table_summary(con))
    return count


def run_backfill(
    con: duckdb.DuckDBPyConnection,
    *,
    session: requests.Session | None = None,
    raw_dir: Path = extract.RAW_DIR,
) -> int:
    """Reload the whole history (1999-01-04 -> today). Safe to run again: upsert."""
    raw_path = extract.extract_history(
        extract.FIRST_AVAILABLE_DATE, session=session, raw_dir=raw_dir
    )
    count = load_raw_file(con, raw_path)
    logger.info("Backfill upserted %d rows. Table now: %s", count, table_summary(con))
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load BAM FX rates into DuckDB.")
    parser.add_argument("command", choices=["update", "backfill"])
    parser.add_argument("--db", type=Path, default=DB_PATH, help="DuckDB file path")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s"
    )
    try:
        con = connect(args.db)
        try:
            if args.command == "update":
                run_update(con)
            else:
                run_backfill(con)
        finally:
            con.close()
    except (extract.ExtractError, duckdb.Error) as exc:
        logger.error("Load failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
