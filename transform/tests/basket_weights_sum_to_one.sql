-- Each basket period must have weights that add up to 100 %.
select valid_from, sum(weight) as total_weight
from {{ ref('basket_weights') }}
group by valid_from
having abs(sum(weight) - 1.0) > 0.000001
