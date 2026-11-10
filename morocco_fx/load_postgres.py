"""Load step for the "company" mode: same logic as load.py, but into PostgreSQL.

Used by the Airflow DAG (airflow/dags/morocco_fx_daily.py), in Docker.
Same rules as with DuckDB:
  - incremental: start from the last loaded date (watermark),
  - idempotent: upsert on (rate_date, currency), so running twice adds no duplicate,
  - the raw API answer is saved first (extract step), then loaded.

Connection settings come from environment variables (set in docker-compose.yml from the
.env file): FX_PG_HOST, FX_PG_PORT, FX_PG_USER, FX_PG_PASSWORD, FX_PG_DB.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from morocco_fx import extract
from morocco_fx.load import prepare_rows

RAW_SCHEMA = os.environ.get("FX_RAW_SCHEMA", "raw")

logger = logging.getLogger("morocco_fx.load_postgres")

CREATE_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA};
CREATE TABLE IF NOT EXISTS {RAW_SCHEMA}.rates (
    rate_date DATE             NOT NULL,
    base      VARCHAR(3)       NOT NULL,
    currency  VARCHAR(3)       NOT NULL,
    rate      DOUBLE PRECISION NOT NULL,
    loaded_at TIMESTAMP        NOT NULL DEFAULT now(),
    PRIMARY KEY (rate_date, currency)
);
"""

UPSERT_SQL = f"""
INSERT INTO {RAW_SCHEMA}.rates (rate_date, base, currency, rate) VALUES %s
ON CONFLICT (rate_date, currency) DO UPDATE SET
    base = excluded.base,
    rate = excluded.rate,
    loaded_at = now()
"""


def connect():
    """Open a connection from the FX_PG_* environment variables and create the table."""
    con = psycopg2.connect(
        host=os.environ.get("FX_PG_HOST", "localhost"),
        port=int(os.environ.get("FX_PG_PORT", "5432")),
        user=os.environ.get("FX_PG_USER", "fx"),
        password=os.environ.get("FX_PG_PASSWORD", ""),
        dbname=os.environ.get("FX_PG_DB", "fx"),
    )
    with con, con.cursor() as cur:
        cur.execute(CREATE_SQL)
    return con


def get_watermark(con) -> date | None:
    """Last loaded date, or None if the table is empty."""
    with con.cursor() as cur:
        cur.execute(f"SELECT max(rate_date) FROM {RAW_SCHEMA}.rates")
        return cur.fetchone()[0]


def count_rows(con) -> int:
    with con.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {RAW_SCHEMA}.rates")
        return cur.fetchone()[0]


def upsert_rates(con, rows: list[dict]) -> int:
    """Upsert API rows in one transaction (all rows or none). Returns the rows sent."""
    incoming = prepare_rows(rows)
    values = list(
        zip(incoming["date"], incoming["base"], incoming["quote"], incoming["rate"], strict=True)
    )
    with con, con.cursor() as cur:  # `with con` = commit at the end, rollback on error
        execute_values(cur, UPSERT_SQL, values, page_size=5000)
    return len(values)


def extract_missing_days(con, *, raw_dir: Path = extract.RAW_DIR) -> Path:
    """Call the API from the watermark (or from 1999 if empty); return the raw file path."""
    watermark = get_watermark(con)
    start = watermark or extract.FIRST_AVAILABLE_DATE
    logger.info("Watermark: %s -> asking the API from %s", watermark, start)
    return extract.extract_history(start, raw_dir=raw_dir)


def load_raw_file(con, raw_path: Path) -> int:
    rows = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    count = upsert_rates(con, rows)
    logger.info("Upserted %d rows from %s; table has %d rows", count, raw_path, count_rows(con))
    return count
