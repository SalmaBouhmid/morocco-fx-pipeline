"""Extract step: download Bank Al-Maghrib exchange rates from the Frankfurter API.

Frankfurter (https://frankfurter.dev) aggregates the official Bank Al-Maghrib (BAM) rates.
This module only does the "E" of ETL:
  1. call the API (with retries and a growing wait if it fails),
  2. check that the answer has the expected shape,
  3. save the raw JSON answer, timestamped, in the raw layer (data/raw/).

Usage:
    python -m morocco_fx.extract latest
    python -m morocco_fx.extract history --from 2026-11-01 [--to 2026-11-05]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

API_BASE_URL = "https://api.frankfurter.dev/v2"
LATEST_URL = f"{API_BASE_URL}/providers/bam/rates"
HISTORY_URL = f"{API_BASE_URL}/rates"
BASE_CURRENCY = "MAD"
PROVIDER = "bam"
FIRST_AVAILABLE_DATE = date(1999, 1, 4)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 2.0  # waits 2 s, 4 s, 8 s between attempts
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

REQUIRED_KEYS = {"date", "base", "quote", "rate"}

logger = logging.getLogger("morocco_fx.extract")


class ExtractError(RuntimeError):
    """Raised when the API cannot give us usable data. The pipeline must stop."""


def fetch_json(
    url: str,
    params: dict[str, str] | None = None,
    *,
    session: requests.Session | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    backoff_seconds: float = BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET a URL and return the decoded JSON, retrying on temporary failures.

    Temporary failures (network error, timeout, HTTP 429 or 5xx) are retried with an
    exponential wait. Other HTTP errors (e.g. 404 bad URL) fail immediately: retrying
    would not help.
    """
    http = session or requests.Session()
    for attempt in range(1, max_attempts + 1):
        try:
            response = http.get(url, params=params, timeout=TIMEOUT_SECONDS)
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason = f"network error: {exc}"
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ExtractError(f"API answer is not valid JSON: {exc}") from exc
            if response.status_code not in RETRYABLE_STATUS:
                raise ExtractError(
                    f"API returned HTTP {response.status_code} for {response.url}: "
                    f"{response.text[:200]}"
                )
            reason = f"HTTP {response.status_code}"

        if attempt == max_attempts:
            raise ExtractError(f"API still failing after {max_attempts} attempts ({reason})")
        wait = backoff_seconds * 2 ** (attempt - 1)
        logger.warning(
            "Attempt %d/%d failed (%s). Retrying in %.0f s.", attempt, max_attempts, reason, wait
        )
        sleep(wait)

    raise AssertionError("unreachable")  # pragma: no cover


def validate_rates(payload: Any) -> list[dict[str, Any]]:
    """Check the API answer: a non-empty list of {date, base, quote, rate} rows.

    Real shape (checked by a live call on 2026-11-06):
        [{"date": "2026-11-05", "base": "MAD", "quote": "EUR", "rate": 0.090873}, ...]
    """
    if not isinstance(payload, list):
        raise ExtractError(f"Expected a JSON list, got {type(payload).__name__}")
    if not payload:
        raise ExtractError("API returned an empty list: no rates for this request")

    for i, row in enumerate(payload):
        if not isinstance(row, dict) or not REQUIRED_KEYS <= row.keys():
            raise ExtractError(f"Row {i} does not have the keys {sorted(REQUIRED_KEYS)}: {row}")
        if row["base"] != BASE_CURRENCY:
            raise ExtractError(f"Row {i} has base {row['base']!r}, expected {BASE_CURRENCY!r}")
        rate = row["rate"]
        if isinstance(rate, bool) or not isinstance(rate, int | float) or rate <= 0:
            raise ExtractError(f"Row {i} has an invalid rate: {rate!r}")
        try:
            date.fromisoformat(row["date"])
        except (TypeError, ValueError) as exc:
            raise ExtractError(f"Row {i} has an invalid date: {row['date']!r}") from exc
    return payload


def save_raw(payload: Any, kind: str, raw_dir: Path = RAW_DIR, now: datetime | None = None) -> Path:
    """Save the API answer as-is in a timestamped JSON file (the raw layer)."""
    now = now or datetime.now(timezone.utc)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"bam_{kind}_{now:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def summarize(rows: list[dict[str, Any]]) -> str:
    dates = sorted({row["date"] for row in rows})
    currencies = {row["quote"] for row in rows} - {BASE_CURRENCY}
    return (
        f"{len(rows)} rows, {len(dates)} day(s) from {dates[0]} to {dates[-1]}, "
        f"{len(currencies)} foreign currencies"
    )


def extract_latest(*, session: requests.Session | None = None, raw_dir: Path = RAW_DIR) -> Path:
    """Download the latest published day and save it in the raw layer."""
    # base=MAD is required: without it the API answers with EUR as base.
    payload = fetch_json(LATEST_URL, {"base": BASE_CURRENCY}, session=session)
    path = save_raw(payload, "latest", raw_dir)
    rows = validate_rates(payload)
    logger.info("Latest rates: %s. Saved to %s", summarize(rows), path)
    return path


def extract_history(
    start: date,
    end: date | None = None,
    *,
    session: requests.Session | None = None,
    raw_dir: Path = RAW_DIR,
) -> Path:
    """Download every published day from `start` (to `end`, default: latest)."""
    if start < FIRST_AVAILABLE_DATE:
        raise ExtractError(f"BAM data starts on {FIRST_AVAILABLE_DATE}, got {start}")
    if end is not None and end < start:
        raise ExtractError(f"End date {end} is before start date {start}")

    params = {"base": BASE_CURRENCY, "providers": PROVIDER, "from": start.isoformat()}
    if end is not None:
        params["to"] = end.isoformat()
    payload = fetch_json(HISTORY_URL, params, session=session)
    path = save_raw(payload, "history", raw_dir)
    rows = validate_rates(payload)
    logger.info("History: %s. Saved to %s", summarize(rows), path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Bank Al-Maghrib FX rates (raw layer).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("latest", help="latest published day")
    history = sub.add_parser("history", help="every day from a start date")
    history.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    history.add_argument("--to", dest="end", type=date.fromisoformat)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s"
    )
    try:
        if args.command == "latest":
            extract_latest()
        else:
            extract_history(args.start, args.end)
    except ExtractError as exc:
        logger.error("Extraction failed: %s", exc)
        return 1  # non-zero exit code: the failure is visible to cron / Airflow
    return 0


if __name__ == "__main__":
    sys.exit(main())
