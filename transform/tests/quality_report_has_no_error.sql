-- Blocking check: any "error" in the quality report fails dbt build
-- (for example: no new rate for more than 7 days).
{{ config(severity='error') }}

select check_name, metric_value, details
from {{ ref('data_quality_report') }}
where status = 'error'
