-- Q4: how does the dirham move against its official basket?
-- Weights come from the seed basket_weights.csv, copied from Bank Al-Maghrib
-- (EUR 60 % / USD 40 % since 2015-04-13; link in the source_url column of the seed).
--
-- IMPORTANT: this is OUR illustrative reconstruction, not the official central rate
-- (the BAM page gives the weights but not the formula). Method: weighted geometric index
--   basket_index = 100 * exp( sum of weight * ln(rate_t / rate_on_first_day) )
-- with rate = units of currency for 1 MAD, and 100 = first published day of the period.
-- Above 100: 1 MAD buys more of the basket than on that day (the dirham is stronger).
-- Only the period starting 2015-04-13 is in the seed: earlier weights are not loaded.

with weights as (

    select valid_from, currency, weight
    from {{ ref('basket_weights') }}

),

periods as (

    select
        valid_from,
        lead(valid_from) over (order by valid_from) as valid_to
    from (select distinct valid_from from weights) as p

),

rates_in_period as (

    select d.rate_date, d.currency, d.rate, w.weight, w.valid_from
    from {{ ref('fct_daily_rates') }} as d
    join weights as w
      on w.currency = d.currency
    join periods as p
      on p.valid_from = w.valid_from
     and d.rate_date >= p.valid_from
     and (p.valid_to is null or d.rate_date < p.valid_to)

),

first_days as (

    select valid_from, min(rate_date) as first_date
    from rates_in_period
    group by valid_from

),

base_rates as (

    select r.valid_from, r.currency, r.rate as base_rate
    from rates_in_period as r
    join first_days as f
      on f.valid_from = r.valid_from and f.first_date = r.rate_date

),

basket_size as (

    select valid_from, count(*) as n_currencies
    from weights
    group by valid_from

),

per_day as (

    select
        r.rate_date,
        r.valid_from,
        count(*)                                   as n_currencies,
        sum(r.weight * ln(r.rate / b.base_rate))   as weighted_log_change
    from rates_in_period as r
    join base_rates as b
      on b.valid_from = r.valid_from and b.currency = r.currency
    group by r.rate_date, r.valid_from

)

select
    d.rate_date,
    d.valid_from                           as weights_valid_from,
    100.0 * exp(d.weighted_log_change)     as basket_index
from per_day as d
join basket_size as s
  on s.valid_from = d.valid_from
-- keep only days where every basket currency was published
where d.n_currencies = s.n_currencies
