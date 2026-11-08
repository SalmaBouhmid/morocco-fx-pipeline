"""Tests for the dashboard calculations. No network, no Streamlit: small hand-made tables."""

import pandas as pd

from dashboard import fx_data


def monthly_table(currency, months, values):
    return pd.DataFrame(
        {
            "month_start": pd.to_datetime(months),
            "currency": currency,
            "n_days": 20,
            "avg_mad_per_unit": values,
        }
    )


def test_latest_snapshot_keeps_only_the_last_day():
    daily = pd.DataFrame(
        {
            "rate_date": pd.to_datetime(["2026-11-04", "2026-11-05", "2026-11-05"]),
            "currency": ["EUR", "USD", "EUR"],
            "mad_per_unit": [10.9, 9.7, 10.95],
        }
    )
    snapshot = fx_data.latest_snapshot(daily)
    assert list(snapshot["currency"]) == ["EUR", "USD"]
    assert (snapshot["rate_date"] == pd.Timestamp("2026-11-05")).all()


def test_best_and_worst_months_ignore_the_unfinished_last_month():
    monthly = monthly_table(
        "EUR",
        ["2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01"],
        [10.8, 11.0, 10.9, 12.0],  # November is not finished: its 12.0 must be ignored
    )
    best, worst = fx_data.best_and_worst_months(monthly, "EUR", n=1)
    assert best["month_start"].iloc[0] == pd.Timestamp("2026-09-01")
    assert worst["month_start"].iloc[0] == pd.Timestamp("2026-08-01")


def test_seasonality_uses_full_years_only():
    months = pd.date_range("2024-01-01", "2025-12-01", freq="MS").append(
        pd.DatetimeIndex(["2026-01-01", "2026-02-01"])  # 2026 is not a full year
    )
    # every year: March is 2 % above the other months
    values = [10.2 if m.month == 3 else 10.0 for m in months]
    season = fx_data.seasonality(monthly_table("EUR", months, values), "EUR", since_year=2024)
    assert len(season) == 12
    assert (season["n_years"] == 2).all()
    march = season.set_index("month").loc[3, "avg_gap_pct"]
    january = season.set_index("month").loc[1, "avg_gap_pct"]
    assert march > 1.5 and january < 0


def test_gaps_per_year_counts_days_by_reason():
    gaps = pd.DataFrame(
        {
            "calendar_date": pd.to_datetime(["2025-01-04", "2025-01-05", "2026-01-01"]),
            "gap_reason": ["weekend", "weekend", "public_holiday"],
        }
    )
    counts = fx_data.gaps_per_year(gaps).set_index(["year", "gap_reason"])["n_days"]
    assert counts[(2025, "weekend")] == 2
    assert counts[(2026, "public_holiday")] == 1


def test_load_table_from_a_folder_converts_and_sorts_dates(tmp_path):
    days = [pd.Timestamp(d).date() for d in ("2026-11-05", "2026-11-03", "2026-11-04")]
    pd.DataFrame({"rate_date": days, "currency": "EUR", "rate": [0.09, 0.08, 0.07]}).to_parquet(
        tmp_path / "fct_daily_rates.parquet"
    )
    table = fx_data.load_table("fct_daily_rates", str(tmp_path))
    assert pd.api.types.is_datetime64_any_dtype(table["rate_date"])
    assert table["rate_date"].is_monotonic_increasing  # unsorted rows would draw a messy line
