"""Tests for saving / restoring the data as Parquet. No network."""

from datetime import date

import pytest

from morocco_fx import load, state

ROWS = [
    {"date": "2026-11-04", "base": "MAD", "quote": "EUR", "rate": 0.0912},
    {"date": "2026-11-04", "base": "MAD", "quote": "USD", "rate": 0.1049},
    {"date": "2026-11-05", "base": "MAD", "quote": "EUR", "rate": 0.09125},
    {"date": "2026-11-05", "base": "MAD", "quote": "USD", "rate": 0.1025},
]


def rows_of(con):
    return con.execute(
        "SELECT rate_date, base, currency, rate FROM rates ORDER BY rate_date, currency"
    ).fetchall()


@pytest.fixture
def exported(tmp_path):
    """A first 'run': load rows, export rates.parquet, return (rows, export dir)."""
    con = load.connect(tmp_path / "run1.duckdb")
    load.upsert_rates(con, ROWS)
    out = tmp_path / "export"
    state.export_tables(con, out, {"main.rates": state.RATES_FILE})
    expected = rows_of(con)
    con.close()
    return expected, out


def test_export_then_restore_gives_same_rows(tmp_path, exported):
    expected, out = exported
    con = load.connect(tmp_path / "run2.duckdb")  # new empty machine
    assert state.restore_rates(con, out / state.RATES_FILE) == 4
    assert rows_of(con) == expected
    assert load.get_watermark(con) == date(2026, 11, 5)


def test_restore_twice_adds_nothing(tmp_path, exported):
    expected, out = exported
    con = load.connect(tmp_path / "run2.duckdb")
    state.restore_rates(con, out / state.RATES_FILE)
    assert state.restore_rates(con, out / state.RATES_FILE) == 0
    assert rows_of(con) == expected


def test_restore_without_file_is_a_first_run(tmp_path):
    code = state.main(["--db", str(tmp_path / "x.duckdb"), "restore", "--from", str(tmp_path)])
    assert code == 0


def test_export_fails_visibly_when_a_table_is_missing(tmp_path):
    # the marts do not exist: dbt has not run, so export must fail (exit code 1)
    code = state.main(["--db", str(tmp_path / "x.duckdb"), "export", "--to", str(tmp_path)])
    assert code == 1
