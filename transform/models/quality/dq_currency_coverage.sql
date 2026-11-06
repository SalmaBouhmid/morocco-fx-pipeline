-- Q5: when each currency appears and disappears. This explains why the table holds more
-- currencies in total than BAM publishes on one day (e.g. MRO replaced by MRU in 2018).
-- n_missing_days = days when BAM published other currencies but not this one, between
-- this currency's first and last date.

with overall as (

    select min(rate_date) as first_date, max(rate_date) as last_date
    from {{ ref('stg_rates') }}

),

published_days as (

    select distinct rate_date from {{ ref('stg_rates') }}

),

per_currency as (

    select
        currency,
        min(rate_date) as first_date,
        max(rate_date) as last_date,
        count(*)       as n_days
    from {{ ref('stg_rates') }}
    group by currency

)

select
    c.currency,
    c.first_date,
    c.last_date,
    c.n_days,
    (select count(*) from published_days as p
      where p.rate_date between c.first_date and c.last_date) - c.n_days
                                         as n_missing_days,
    case when c.last_date = o.last_date then 'active' else 'discontinued' end
                                         as coverage_status,
    c.first_date > o.first_date          as introduced_later
from per_currency as c
cross join overall as o
