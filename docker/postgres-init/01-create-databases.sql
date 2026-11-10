-- Runs once, when the PostgreSQL volume is created.
-- The server already has the "fx" database (the data warehouse, POSTGRES_DB).
-- Airflow keeps its own bookkeeping (DAG runs, task states) in a separate database.
CREATE DATABASE airflow;
