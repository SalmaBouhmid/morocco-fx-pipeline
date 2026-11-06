-- Staging: clean types, one row per (rate_date, currency).
-- The load step already prevents duplicates (primary key), but staging must not trust
-- its input: if a duplicate ever appears, we keep the most recently loaded row.

with source as (

    select * from {{ source('raw', 'rates') }}

),

typed as (

    select
        cast(rate_date as date)                 as rate_date,
        upper(trim(base))                       as base_currency,
        upper(trim(currency))                   as currency,
        cast(rate as double precision)          as rate,
        cast(loaded_at as timestamp)            as loaded_at
    from source
    where rate is not null
      and rate > 0
      and upper(trim(currency)) <> upper(trim(base))

),

ranked as (

    select
        *,
        row_number() over (
            partition by rate_date, currency
            order by loaded_at desc
        ) as row_num
    from typed

)

select
    rate_date,
    base_currency,
    currency,
    rate,                                       -- units of currency for 1 MAD
    1.0 / rate          as mad_per_unit,        -- MAD for 1 unit of currency (e.g. 1 EUR = 10.96 MAD)
    loaded_at
from ranked
where row_num = 1
