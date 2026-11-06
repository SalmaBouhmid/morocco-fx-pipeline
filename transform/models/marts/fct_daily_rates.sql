-- Q1: rate of the day and its change over 1 day, 1 week and 1 month.
-- "1 week ago" = the last published rate on or before (date - 7 days), because there is
-- no rate on week-ends and holidays. Same idea for "1 month ago".
-- Only portable SQL (DuckDB and Postgres): dbt.dateadd writes the date maths for each database.

with rates as (

    select rate_date, currency, rate, mad_per_unit
    from {{ ref('stg_rates') }}

),

with_previous_day as (

    select
        *,
        lag(mad_per_unit) over (partition by currency order by rate_date) as prev_mad_per_unit
    from rates

),

week_ref as (

    -- latest published day between 7 and 14 days before
    select d.rate_date, d.currency, max(p.rate_date) as ref_date
    from rates d
    join rates p
      on p.currency = d.currency
     and p.rate_date <= {{ dbt.dateadd('day', -7, 'd.rate_date') }}
     and p.rate_date >  {{ dbt.dateadd('day', -14, 'd.rate_date') }}
    group by d.rate_date, d.currency

),

month_ref as (

    -- latest published day between 1 month and 1 month + 10 days before
    select d.rate_date, d.currency, max(p.rate_date) as ref_date
    from rates d
    join rates p
      on p.currency = d.currency
     and p.rate_date <= {{ dbt.dateadd('month', -1, 'd.rate_date') }}
     and p.rate_date >  {{ dbt.dateadd('day', -10, dbt.dateadd('month', -1, 'd.rate_date')) }}
    group by d.rate_date, d.currency

)

select
    r.rate_date,
    r.currency,
    r.rate,
    r.mad_per_unit,
    100.0 * (r.mad_per_unit / r.prev_mad_per_unit - 1)  as pct_change_1d,
    100.0 * (r.mad_per_unit / w.mad_per_unit - 1)       as pct_change_1w,
    100.0 * (r.mad_per_unit / m.mad_per_unit - 1)       as pct_change_1m
from with_previous_day r
left join week_ref wr
  on wr.rate_date = r.rate_date and wr.currency = r.currency
left join rates w
  on w.rate_date = wr.ref_date and w.currency = r.currency
left join month_ref mr
  on mr.rate_date = r.rate_date and mr.currency = r.currency
left join rates m
  on m.rate_date = mr.ref_date and m.currency = r.currency
