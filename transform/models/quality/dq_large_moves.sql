-- Q5: alerts - daily moves of more than 5 % (in either direction) for one currency.
-- A big move is not always an error (devaluation, crisis), but it must be looked at.

{% set threshold_pct = 5 %}

with daily as (

    select
        rate_date,
        currency,
        mad_per_unit,
        pct_change_1d,
        lag(rate_date) over (partition by currency order by rate_date) as previous_date
    from {{ ref('fct_daily_rates') }}

)

select
    rate_date,
    currency,
    previous_date,
    mad_per_unit,
    pct_change_1d,
    {{ threshold_pct }}  as threshold_pct
from daily
where abs(pct_change_1d) > {{ threshold_pct }}
