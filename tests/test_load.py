"""Tests for the load step: DuckDB, watermark, upsert, idempotence. No network."""

from datetime import date

import pytest

from morocco_fx import extract, load
from tests.fakes import FakeResponse, FakeSession


def make_rows(day, rates):
    """API-shaped rows for one day; includes the MAD -> MAD line like the real API."""
    rows = [{"date": day, "base": "MAD", "quote": "MAD", "rate": 1.0}]
    rows += [{"date": day, "base": "MAD", "quote": q, "rate": r} for q, r in rates.items()]
    return rows


DAY1 = make_rows("2026-11-04", {"EUR": 0.0912, "USD": 0.1049})
DAY2 = make_rows("2026-11-05", {"EUR": 0.09125, "USD": 0.1025})


@pytest.fixture
def con(tmp_path):
    connection = load.connect(tmp_path / "test.duckdb")
    yield connection
    connection.close()


def all_rows(con):
    return con.execute(
        "SELECT rate_date, base, currency, rate FROM rates ORDER BY rate_date, currency"
    ).fetchall()


def test_watermark_is_none_on_empty_table(con):
    assert load.get_watermark(con) is None


def test_upsert_skips_mad_to_mad_line(con):
    assert load.upsert_rates(con, DAY1) == 2
    assert [r[2] for r in all_rows(con)] == ["EUR", "USD"]


def test_watermark_is_last_loaded_date(con):
    load.upsert_rates(con, DAY1 + DAY2)
    assert load.get_watermark(con) == date(2026, 11, 5)


def test_loading_twice_gives_same_rows(con):
    """Idempotence: running the same load again creates no duplicate."""
    load.upsert_rates(con, DAY1 + DAY2)
    first = all_rows(con)
    load.upsert_rates(con, DAY1 + DAY2)
    assert all_rows(con) == first
    assert len(first) == 4


def test_upsert_updates_a_corrected_rate(con):
    load.upsert_rates(con, DAY2)
    corrected = make_rows("2026-11-05", {"EUR": 0.0999})
    load.upsert_rates(con, corrected)
    eur = con.execute(
        "SELECT rate FROM rates WHERE rate_date = '2026-11-05' AND currency = 'EUR'"
    ).fetchall()
    assert eur == [(0.0999,)]
    assert len(all_rows(con)) == 2


def test_upsert_rejects_duplicate_key_in_answer(con):
    with pytest.raises(extract.ExtractError, match="twice"):
        load.upsert_rates(con, DAY1 + DAY1)
    assert all_rows(con) == []


def test_upsert_rejects_bad_payload_and_loads_nothing(con):
    bad = DAY1 + [{"date": "2026-11-04", "base": "MAD", "quote": "GBP", "rate": -1}]
    with pytest.raises(extract.ExtractError):
        load.upsert_rates(con, bad)
    assert all_rows(con) == []


def test_update_on_empty_table_starts_in_1999(con, tmp_path):
    session = FakeSession([FakeResponse(200, DAY1)])
    load.run_update(con, session=session, raw_dir=tmp_path / "raw")
    assert session.calls[0]["params"]["from"] == "1999-01-04"


def test_update_asks_only_from_watermark(con, tmp_path):
    load.upsert_rates(con, DAY1)
    session = FakeSession([FakeResponse(200, DAY1 + DAY2)])
    load.run_update(con, session=session, raw_dir=tmp_path / "raw")
    assert session.calls[0]["params"]["from"] == "2026-11-04"
    assert load.get_watermark(con) == date(2026, 11, 5)
    assert len(all_rows(con)) == 4


def test_update_twice_same_day_creates_no_duplicate(con, tmp_path):
    answers = [FakeResponse(200, DAY1 + DAY2), FakeResponse(200, DAY2)]
    session = FakeSession(answers)
    load.run_update(con, session=session, raw_dir=tmp_path / "raw")
    before = all_rows(con)
    load.run_update(con, session=session, raw_dir=tmp_path / "raw")
    assert all_rows(con) == before


def test_backfill_twice_gives_same_rows(con, tmp_path):
    session = FakeSession([FakeResponse(200, DAY1 + DAY2), FakeResponse(200, DAY1 + DAY2)])
    load.run_backfill(con, session=session, raw_dir=tmp_path / "raw")
    first = all_rows(con)
    load.run_backfill(con, session=session, raw_dir=tmp_path / "raw")
    assert all_rows(con) == first
    assert session.calls[1]["params"]["from"] == "1999-01-04"


def test_main_returns_1_when_api_fails(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise extract.ExtractError("API down")

    monkeypatch.setattr(load, "run_update", broken)
    assert load.main(["update", "--db", str(tmp_path / "x.duckdb")]) == 1
