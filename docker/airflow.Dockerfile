# Airflow image + what the pipeline needs.
FROM apache/airflow:3.3.2-python3.12

# Pipeline code: requests, pandas, duckdb. pytest: to run the PostgreSQL tests in the container.
# Pinning apache-airflow to its own version stops pip from upgrading or downgrading Airflow.
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" requests pandas duckdb pytest

# dbt gets its own virtual environment, so its packages never conflict with Airflow's.
# Exact versions: the same dbt-core as on the laptop (requirements-dbt.txt), no beta.
RUN python -m venv /home/airflow/dbt-venv \
    && /home/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core==1.12.6" "dbt-postgres==1.11.0"
