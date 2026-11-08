"""Data access and small calculations for the dashboard (no Streamlit here, so pytest can test it).

The daily pipeline (GitHub Actions) publishes the tables as Parquet files on the `data` branch.
The dashboard reads them:
  - online (Streamlit Cloud): from raw.githubusercontent.com, i.e. the `data` branch;
  - on your PC: from a folder, if the environment variable FX_DATA_DIR is set
    (e.g. FX_DATA_DIR=data/export after running the pipeline locally).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import requests

DATA_BRANCH_URL = "https://raw.githubusercontent.com/SalmaBouhmid/morocco-fx-pipeline/data/"

TABLES = (
    "fct_daily_rates",
    "fct_monthly_rates",
    "fct_volatility",
    "mad_basket_index",
    "data_quality_report",
    "dq_large_moves",
    "dq_calendar_gaps",
    "dq_currency_coverage",
)

MONTH_NAMES_FR = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)


def data_source() -> str:
    """Folder from FX_DATA_DIR if set, else the URL of the `data` branch."""
    return os.environ.get("FX_DATA_DIR") or DATA_BRANCH_URL


def is_date_column(name: str) -> bool:
    return name.endswith("_date") or name in ("month_start", "weights_valid_from")


def load_table(name: str, source: str | None = None, *, timeout: float = 30.0) -> pd.DataFrame:
    """Read one Parquet table from a folder or from a URL (the `data` branch).

    Date columns are converted to pandas datetimes, so charts and filters work the same way,
    and rows are sorted by date (then currency).
    """
    source = source or data_source()
    if source.startswith(("http://", "https://")):
        response = requests.get(source.rstrip("/") + f"/{name}.parquet", timeout=timeout)
        response.raise_for_status()
        table = pd.read_parquet(io.BytesIO(response.content))
    else:
        table = pd.read_parquet(Path(source) / f"{name}.parquet")
    for column in table.columns:
        if is_date_column(column):
            table[column] = pd.to_datetime(table[column])
    # Parquet files keep no order: sort by date so that line charts are drawn left to right.
    sort_keys = [c for c in ("rate_date", "month_start", "calendar_date", "currency") if c in table]
    return table.sort_values(sort_keys).reset_index(drop=True) if sort_keys else table


def latest_snapshot(daily: pd.DataFrame) -> pd.DataFrame:
    """Rows of the last published day, one per currency, sorted by currency."""
    last_day = daily["rate_date"].max()
    return daily[daily["rate_date"] == last_day].sort_values("currency").reset_index(drop=True)


def complete_months(monthly: pd.DataFrame, currency: str) -> pd.DataFrame:
    """Monthly rows of one currency, without the last month (it is usually not finished)."""
    rows = monthly[monthly["currency"] == currency].sort_values("month_start")
    return rows[rows["month_start"] < rows["month_start"].max()].reset_index(drop=True)


def best_and_worst_months(
    monthly: pd.DataFrame, currency: str, n: int = 5
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Months with the highest / lowest average MAD per unit.

    For someone who SELLS this currency (an exporter paid in euros), the best month is the one
    where one unit gave the most dirhams.
    """
    rows = complete_months(monthly, currency)
    best = rows.nlargest(n, "avg_mad_per_unit").reset_index(drop=True)
    worst = rows.nsmallest(n, "avg_mad_per_unit").reset_index(drop=True)
    return best, worst


def seasonality(monthly: pd.DataFrame, currency: str, since_year: int) -> pd.DataFrame:
    """Average gap (in %) between each calendar month and its year's average.

    Only full years (12 months) from `since_year` are used, so a missing month cannot bias a year.
    Returns one row per month 1..12 with columns month, month_name, avg_gap_pct, n_years.
    """
    rows = complete_months(monthly, currency)
    rows = rows.copy()
    rows["year"] = rows["month_start"].dt.year
    rows["month"] = rows["month_start"].dt.month
    rows = rows[rows["year"] >= since_year]
    full_years = rows.groupby("year")["month"].nunique()
    rows = rows[rows["year"].isin(full_years[full_years == 12].index)]
    year_avg = rows.groupby("year")["avg_mad_per_unit"].transform("mean")
    rows = rows.assign(gap_pct=(rows["avg_mad_per_unit"] / year_avg - 1) * 100)
    result = (
        rows.groupby("month")
        .agg(avg_gap_pct=("gap_pct", "mean"), n_years=("year", "nunique"))
        .reset_index()
    )
    result["month_name"] = result["month"].map(lambda m: MONTH_NAMES_FR[m - 1])
    return result[["month", "month_name", "avg_gap_pct", "n_years"]]


def gaps_per_year(gaps: pd.DataFrame) -> pd.DataFrame:
    """Number of days without quote, per year and reason (for a stacked bar chart)."""
    dates = pd.to_datetime(gaps["calendar_date"])
    return (
        gaps.assign(year=dates.dt.year)
        .groupby(["year", "gap_reason"])
        .size()
        .reset_index(name="n_days")
    )
