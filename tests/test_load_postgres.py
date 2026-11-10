"""Tests for the PostgreSQL load (company mode). They need a running PostgreSQL, so they are
skipped unless FX_PG_HOST is set. Run them inside the Airflow container:

    docker compose exec airflow python -m pytest /opt/project/tests/test_load_postgres.py -q

They use a separate schema (test_raw), so the real data in "raw" is never touched.
"""

import importlib
import os

import pytest

pytest.importorskip("psycopg2")
if not os.environ.get("FX_PG_HOST"):
    pytest.skip("FX_PG_HOST not set: no PostgreSQL to test against", allow_module_level=True)

ROWS = [
    {"date": "2026-11-05", "base": "MAD", "quote": "EUR", "rate": 0.0912},
    {"date": "2026-11-05", "base": "MAD", "quote": "USD", "rate": 0.1025},
    {"date": "2026-11-05", "base": "MAD", "quote": "MAD", "rate": 1.0},  # skipped
]


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("FX_RAW_SCHEMA", "test_raw")
    from morocco_fx import load_postgres

    module = importlib.reload(load_postgres)  # re-read FX_RAW_SCHEMA
    con = module.connect()
    with con, con.cursor() as cur:
        cur.execute("TRUNCATE test_raw.rates")
    yield module, con
    with con, con.cursor() as cur:
        cur.execute("DROP SCHEMA test_raw CASCADE")
    con.close()
    monkeypatch.delenv("FX_RAW_SCHEMA")
    importlib.reload(load_postgres)


def test_load_twice_gives_no_duplicate(pg):
    module, con = pg
    assert module.upsert_rates(con, ROWS) == 2  # the MAD -> MAD line is not loaded
    module.upsert_rates(con, ROWS)
    assert module.count_rows(con) == 2


def test_corrected_rate_is_updated_and_watermark_moves(pg):
    module, con = pg
    module.upsert_rates(con, ROWS)
    corrected = [{"date": "2026-11-05", "base": "MAD", "quote": "EUR", "rate": 0.0915}]
    module.upsert_rates(con, corrected)
    with con.cursor() as cur:
        cur.execute("SELECT rate FROM test_raw.rates WHERE currency = 'EUR'")
        assert cur.fetchone()[0] == pytest.approx(0.0915)
    assert str(module.get_watermark(con)) == "2026-11-05"
