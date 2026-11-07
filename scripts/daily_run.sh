#!/usr/bin/env bash
# Daily pipeline, same steps locally and in GitHub Actions.
# Stops at the first failing step (set -e): the run is then marked as failed.
set -euo pipefail

PYTHON="${PYTHON:-python}"
DBT="${DBT:-dbt}"
EXPORT_DIR="${EXPORT_DIR:-data/export}"

echo "== 1/5 restore previous data from ${EXPORT_DIR}"
"$PYTHON" -m morocco_fx.state restore --from "$EXPORT_DIR"

echo "== 2/5 extract + load the missing days (watermark, upsert)"
"$PYTHON" -m morocco_fx.load update

echo "== 3/5 dbt build (models + tests)"
(cd transform && "$DBT" build)

echo "== 4/5 quality gate"
"$PYTHON" -m morocco_fx.quality

echo "== 5/5 export Parquet files to ${EXPORT_DIR}"
"$PYTHON" -m morocco_fx.state export --to "$EXPORT_DIR"
