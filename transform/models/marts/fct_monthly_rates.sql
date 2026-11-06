-- Q3: monthly view of each currency (average, lowest, highest, month-end rate).

with daily as (

    select
        {{ dbt.date_trunc('month', 'rate_date') }}  as month_start,
        rate_date,
        currency,
        mad_per_unit
    from {{ ref('fct_daily_rates') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by currency, month_start
            order by rate_date desc
        ) as rank_from_end
    from daily

)

select
    cast(month_start as date)                                as month_start,
    currency,
    count(*)                                                 as n_days,
    avg(mad_per_unit)                                        as avg_mad_per_unit,
    min(mad_per_unit)                                        as min_mad_per_unit,
    max(mad_per_unit)                                        as max_mad_per_unit,
    max(case when rank_from_end = 1 then mad_per_unit end)   as close_mad_per_unit
from ranked
group by month_start, currency
