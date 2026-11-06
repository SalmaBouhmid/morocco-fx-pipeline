-- Non-blocking check: every "warn" line of the quality report shows up as a WARN in
-- dbt build (recent moves above 5 %, recent unexplained gaps, publication 5-7 days late).
{{ config(severity='warn') }}

select check_name, metric_value, details
from {{ ref('data_quality_report') }}
where status = 'warn'
