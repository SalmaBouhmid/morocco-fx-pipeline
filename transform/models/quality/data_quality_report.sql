-- Q5: one row per quality check, with a status the pipeline can act on:
--   ok / info : nothing to do
--   warn      : someone should look (pipeline continues)
--   error     : the data cannot be trusted (pipeline must fail)
-- Rules:
--   publication_delay_days : days between the last rate and today. <= 4 ok (a Monday run
--                            sees Friday's rate: 3 days), <= 7 warn, > 7 error.
--   unexplained gaps / large moves : warn when one happened in the last 30 days of data.

with last_load as (

    select max(rate_date) as last_date from {{ ref('stg_rates') }}

),

delay as (

    select
        last_date,
        {{ dbt.datediff('last_date', 'current_date', 'day') }} as delay_days
    from last_load

),

gaps as (

    select
        sum(case when gap_reason = 'weekend' then 1 else 0 end)                    as n_weekend,
        sum(case when gap_reason = 'public_holiday' then 1 else 0 end)             as n_holiday,
        sum(case when gap_reason = 'public_holiday_estimated' then 1 else 0 end)   as n_holiday_est,
        sum(case when gap_reason = 'business_day_without_quote' then 1 else 0 end) as n_unexplained,
        sum(case when gap_reason = 'business_day_without_quote'
                  and calendar_date > {{ dbt.dateadd('day', -30, '(select last_date from last_load)') }}
                 then 1 else 0 end)                                                as n_unexplained_recent
    from {{ ref('dq_calendar_gaps') }}

),

moves as (

    select
        count(*) as n_moves,
        sum(case when rate_date > {{ dbt.dateadd('day', -30, '(select last_date from last_load)') }}
                 then 1 else 0 end) as n_moves_recent
    from {{ ref('dq_large_moves') }}

),

coverage as (

    select
        count(*)                                                        as n_total,
        sum(case when coverage_status = 'active' then 1 else 0 end)     as n_active,
        sum(case when coverage_status = 'discontinued' then 1 else 0 end) as n_discontinued,
        sum(n_missing_days)                                             as n_currency_missing
    from {{ ref('dq_currency_coverage') }}

),

checks as (

    select 1 as check_order, 'publication_delay_days' as check_name,
           cast(delay_days as double precision) as metric_value,
           case when delay_days <= 4 then 'ok' when delay_days <= 7 then 'warn' else 'error' end
               as status,
           'last rate date: ' || cast(last_date as varchar) as details
    from delay

    union all
    select 2, 'missing_days_weekend', cast(n_weekend as double precision), 'info',
           'Saturdays and Sundays: BAM does not publish' from gaps

    union all
    select 3, 'missing_days_public_holiday', cast(n_holiday as double precision), 'info',
           'fixed-date Moroccan holidays (python-holidays, MA)' from gaps

    union all
    select 4, 'missing_days_public_holiday_estimated', cast(n_holiday_est as double precision),
           'info', 'within 1 day of an estimated Islamic holiday' from gaps

    union all
    select 5, 'missing_days_unexplained', cast(n_unexplained as double precision),
           case when n_unexplained_recent > 0 then 'warn' else 'info' end,
           'business days without quote (probable holiday or missing data); in the last 30 days: '
               || cast(n_unexplained_recent as varchar) from gaps

    union all
    select 6, 'large_moves_over_5pct', cast(n_moves as double precision),
           case when n_moves_recent > 0 then 'warn' else 'info' end,
           'daily moves above 5 % (see dq_large_moves); in the last 30 days: '
               || cast(n_moves_recent as varchar) from moves

    union all
    select 7, 'currencies_total', cast(n_total as double precision), 'info',
           'active: ' || cast(n_active as varchar)
               || ', discontinued: ' || cast(n_discontinued as varchar) from coverage

    union all
    select 8, 'currency_missing_on_published_day', cast(n_currency_missing as double precision),
           'info', 'one currency absent while BAM published others (see dq_currency_coverage)'
    from coverage

)

select check_order, check_name, metric_value, status, details
from checks
