"""Tests for the extract step. No network: the API answers are simulated."""

import json
from datetime import date, datetime, timezone

import pytest
import requests

from morocco_fx import extract
from tests.fakes import SAMPLE_ROWS, FakeResponse, FakeSession


@pytest.fixture
def waits():
    """Replaces time.sleep: records the waits instead of really waiting."""
    recorded = []
    return recorded


def test_fetch_json_success_first_try(waits):
    session = FakeSession([FakeResponse(200, SAMPLE_ROWS)])
    result = extract.fetch_json("u", session=session, sleep=waits.append)
    assert result == SAMPLE_ROWS
    assert len(session.calls) == 1
    assert waits == []


def test_fetch_json_retries_then_succeeds(waits):
    session = FakeSession(
        [
            requests.ConnectionError("down"),
            FakeResponse(503, text="busy"),
            FakeResponse(200, SAMPLE_ROWS),
        ]
    )
    result = extract.fetch_json("u", session=session, sleep=waits.append)
    assert result == SAMPLE_ROWS
    assert len(session.calls) == 3
    assert waits == [2.0, 4.0]  # exponential backoff


def test_fetch_json_gives_up_after_max_attempts(waits):
    session = FakeSession([requests.Timeout("slow")] * 4)
    with pytest.raises(extract.ExtractError, match="after 4 attempts"):
        extract.fetch_json("u", session=session, sleep=waits.append)
    assert len(session.calls) == 4
    assert waits == [2.0, 4.0, 8.0]


def test_fetch_json_does_not_retry_client_error(waits):
    session = FakeSession([FakeResponse(404, text="not found")])
    with pytest.raises(extract.ExtractError, match="HTTP 404"):
        extract.fetch_json("u", session=session, sleep=waits.append)
    assert len(session.calls) == 1
    assert waits == []


def test_fetch_json_rejects_invalid_json(waits):
    session = FakeSession([FakeResponse(200, payload=None, text="<html>")])
    with pytest.raises(extract.ExtractError, match="not valid JSON"):
        extract.fetch_json("u", session=session, sleep=waits.append)


def test_validate_rates_accepts_real_shape():
    assert extract.validate_rates(SAMPLE_ROWS) == SAMPLE_ROWS


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"rates": {}}, "Expected a JSON list"),
        ([], "empty list"),
        ([{"date": "2026-11-05", "base": "MAD", "rate": 1.0}], "keys"),
        ([{"date": "2026-11-05", "base": "EUR", "quote": "USD", "rate": 1.1}], "base"),
        ([{"date": "2026-11-05", "base": "MAD", "quote": "USD", "rate": 0}], "invalid rate"),
        ([{"date": "2026-11-05", "base": "MAD", "quote": "USD", "rate": "1"}], "invalid rate"),
        ([{"date": "05/11/2026", "base": "MAD", "quote": "USD", "rate": 0.1}], "invalid date"),
    ],
)
def test_validate_rates_rejects_bad_payload(payload, message):
    with pytest.raises(extract.ExtractError, match=message):
        extract.validate_rates(payload)


def test_save_raw_writes_timestamped_file(tmp_path):
    now = datetime(2026, 11, 6, 15, 30, 0, tzinfo=timezone.utc)
    path = extract.save_raw(SAMPLE_ROWS, "latest", tmp_path, now)
    assert path.name == "bam_latest_20261106T153000Z.json"
    assert json.loads(path.read_text(encoding="utf-8")) == SAMPLE_ROWS


def test_extract_latest_asks_for_mad_base_and_saves(tmp_path):
    session = FakeSession([FakeResponse(200, SAMPLE_ROWS)])
    path = extract.extract_latest(session=session, raw_dir=tmp_path)
    assert session.calls[0]["url"] == extract.LATEST_URL
    assert session.calls[0]["params"] == {"base": "MAD"}
    assert path.exists()


def test_extract_history_sends_dates(tmp_path):
    session = FakeSession([FakeResponse(200, SAMPLE_ROWS)])
    extract.extract_history(date(2026, 11, 2), date(2026, 11, 5), session=session, raw_dir=tmp_path)
    assert session.calls[0]["url"] == extract.HISTORY_URL
    assert session.calls[0]["params"] == {
        "base": "MAD",
        "providers": "bam",
        "from": "2026-11-02",
        "to": "2026-11-05",
    }


def test_extract_history_rejects_date_before_1999(tmp_path):
    with pytest.raises(extract.ExtractError, match="starts on 1999-01-04"):
        extract.extract_history(date(1998, 12, 31), raw_dir=tmp_path)


def test_main_returns_1_on_failure(monkeypatch):
    def broken():
        raise extract.ExtractError("API down")

    monkeypatch.setattr(extract, "extract_latest", broken)
    assert extract.main(["latest"]) == 1
