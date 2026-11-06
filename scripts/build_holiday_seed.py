"""Write the dbt seed of Moroccan public holidays (transform/seeds/ma_public_holidays.csv).

Source: the open-source `holidays` Python package (https://github.com/vacanza/holidays),
country code MA. We do not type any date by hand.
Islamic holidays (Eid, Islamic New Year, Prophet's Birthday) depend on the moon: the
package computes them and marks them "(estimated)". The real day can differ by 1 day.

Usage:
    python scripts/build_holiday_seed.py
"""

import csv
from pathlib import Path

import holidays

FIRST_YEAR = 1999
LAST_YEAR = 2027
SEED_PATH = (
    Path(__file__).resolve().parent.parent / "transform" / "seeds" / "ma_public_holidays.csv"
)
ESTIMATED_MARK = "(estimated)"


def build_rows(first_year: int = FIRST_YEAR, last_year: int = LAST_YEAR) -> list[dict]:
    calendar = holidays.country_holidays(
        "MA", years=range(first_year, last_year + 1), language="en_US"
    )
    source = f"python-holidays {holidays.__version__}, country MA"
    rows = []
    for day, names in sorted(calendar.items()):
        # one date can hold several holidays, joined by "; "
        rows.append(
            {
                "holiday_date": day.isoformat(),
                "holiday_name": names.replace(f" {ESTIMATED_MARK}", ""),
                "is_estimated": ESTIMATED_MARK in names,
                "source": source,
            }
        )
    return rows


def main() -> None:
    rows = build_rows()
    with SEED_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} holidays ({FIRST_YEAR}-{LAST_YEAR}) to {SEED_PATH}")


if __name__ == "__main__":
    main()
