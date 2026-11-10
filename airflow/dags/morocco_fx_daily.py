"""Airflow DAG: the same daily pipeline as GitHub Actions, in "company" mode (PostgreSQL).

    extract  ->  load  ->  dbt_build
    (API -> raw JSON)  (upsert in PostgreSQL)  (models + tests, including the quality gate)

- Runs every day at 17:00 UTC (18:00 in Morocco).
- If a task fails, Airflow tries it again 2 times, 5 minutes apart.
- dbt_build fails if a data test with severity "error" fails (for example a publication
  delay of more than 7 days): the failure is then visible in red in the Airflow UI.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

DBT_COMMAND = (
    "cd /opt/project/transform && "
    "/home/airflow/dbt-venv/bin/dbt build --target postgres --profiles-dir ."
)


@dag(
    dag_id="morocco_fx_daily",
    schedule="0 17 * * *",
    start_date=datetime(2026, 11, 1),
    catchup=False,  # do not replay the past days: the watermark already handles them
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["morocco-fx"],
    doc_md=__doc__,
)
def morocco_fx_daily():
    @task
    def extract() -> str:
        """Ask the API only for the missing days; save the raw answer; return its path."""
        from morocco_fx import load_postgres

        con = load_postgres.connect()
        try:
            return str(load_postgres.extract_missing_days(con))
        finally:
            con.close()

    @task
    def load(raw_path: str) -> int:
        """Upsert the raw file into PostgreSQL (no duplicates, even if run twice)."""
        from morocco_fx import load_postgres

        con = load_postgres.connect()
        try:
            return load_postgres.load_raw_file(con, raw_path)
        finally:
            con.close()

    dbt_build = BashOperator(task_id="dbt_build", bash_command=DBT_COMMAND)

    load(extract()) >> dbt_build


morocco_fx_daily()
