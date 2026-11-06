-- Q2: is the dirham stable? Rolling 30-day volatility of each currency against the MAD.
-- daily_log_return   = ln(today / previous published day)
-- volatility_30d_pct = standard deviation of the daily returns over the last 30 calendar
--                      days, in %. Left empty when the window has fewer than 10 returns.

with returns as (

    select
        rate_date,
        currency,
        mad_per_unit,
        ln(mad_per_unit / lag(mad_per_unit) over (partition by currency order by rate_date))
            as daily_log_return
    from {{ ref('fct_daily_rates') }}

),

windowed as (

    select
        rate_date,
        currency,
        mad_per_unit,
        daily_log_return,
        count(daily_log_return) over last_30_days       as n_returns_30d,
        stddev_samp(daily_log_return) over last_30_days as stddev_30d
    from returns
    window last_30_days as (
        partition by currency
        order by rate_date
        range between interval '29 days' preceding and current row
    )

)

select
    rate_date,
    currency,
    mad_per_unit,
    daily_log_return,
    n_returns_30d,
    case when n_returns_30d >= 10 then 100.0 * stddev_30d end as volatility_30d_pct
from windowed
