-- Q5: every calendar day WITHOUT any published rate, between the first and the last
-- loaded date, with the most likely reason:
--   weekend                    : Saturday or Sunday (BAM never publishes on week-ends)
--   public_holiday             : fixed-date Moroccan public holiday (seed ma_public_holidays)
--   public_holiday_estimated   : within 1 day of an Islamic holiday whose date the source
--                                only estimates (moon sighting can move it by 1 day)
--   business_day_without_quote : none of the above. Maybe a holiday or a closure we do not
--                                know, maybe missing data: we do NOT claim which one.

with recursive bounds as (

    select min(rate_date) as first_date, max(rate_date) as last_date
    from {{ ref('stg_rates') }}

),

calendar_days as (

    select first_date as calendar_date from bounds
    union all
    select cast({{ dbt.dateadd('day', 1, 'calendar_date') }} as date)
    from calendar_days
    where calendar_date < (select last_date from bounds)

),

published_days as (

    select distinct rate_date from {{ ref('stg_rates') }}

),

holidays as (

    select holiday_date, holiday_name, is_estimated
    from {{ ref('ma_public_holidays') }}

),

missing_days as (

    select c.calendar_date, extract(dow from c.calendar_date) as day_of_week
    from calendar_days as c
    left join published_days as p
      on p.rate_date = c.calendar_date
    where p.rate_date is null

),

classified as (

    select
        m.calendar_date,
        m.day_of_week,
        (select max(h.holiday_name) from holidays as h
          where h.holiday_date = m.calendar_date and not h.is_estimated)  as fixed_holiday,
        (select max(h.holiday_name) from holidays as h
          where h.is_estimated
            and h.holiday_date between {{ dbt.dateadd('day', -1, 'm.calendar_date') }}
                                   and {{ dbt.dateadd('day', 1, 'm.calendar_date') }}) as estimated_holiday
    from missing_days as m

)

select
    calendar_date,
    cast(day_of_week as integer)                         as day_of_week,  -- 0 = Sunday
    case
        when day_of_week in (0, 6)          then 'weekend'
        when fixed_holiday is not null      then 'public_holiday'
        when estimated_holiday is not null  then 'public_holiday_estimated'
        else 'business_day_without_quote'
    end                                                  as gap_reason,
    coalesce(fixed_holiday, estimated_holiday)           as holiday_name
from classified
