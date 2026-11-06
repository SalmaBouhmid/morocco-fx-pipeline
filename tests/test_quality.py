"""Tests for the quality gate. No network, no dbt: we write a small fake report."""

import duckdb
import pytest

from morocco_fx import quality


def make_db(path, statuses):
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA quality")
    con.execute(
        "CREATE TABLE quality.data_quality_report (check_order INTEGER, check_name VARCHAR, "
        "metric_value DOUBLE, status VARCHAR, details VARCHAR)"
    )
    for i, status in enumerate(statuses, start=1):
        con.execute(
            "INSERT INTO quality.data_quality_report VALUES (?, ?, ?, ?, ?)",
            [i, f"check_{i}", 1.0, status, "details"],
        )
    con.close()


@pytest.mark.parametrize(
    ("statuses", "expected_exit"),
    [
        (["ok", "info"], 0),
        (["ok", "warn"], 0),  # a warning is shown but does not stop the pipeline
        (["ok", "error"], 1),
        (["warn", "error", "error"], 1),
    ],
)
def test_exit_code_follows_worst_status(tmp_path, statuses, expected_exit):
    db = tmp_path / "fx.duckdb"
    make_db(db, statuses)
    assert quality.main(["--db", str(db)]) == expected_exit


def test_empty_report_fails(tmp_path):
    db = tmp_path / "fx.duckdb"
    make_db(db, [])
    assert quality.main(["--db", str(db)]) == 1


def test_missing_report_table_fails(tmp_path):
    db = tmp_path / "fx.duckdb"
    duckdb.connect(str(db)).close()
    assert quality.main(["--db", str(db)]) == 1


def test_missing_database_fails(tmp_path):
    assert quality.main(["--db", str(tmp_path / "nope.duckdb")]) == 1
