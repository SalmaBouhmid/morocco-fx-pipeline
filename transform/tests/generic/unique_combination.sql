{% test unique_combination(model, columns) %}
-- Fails if the same combination of `columns` appears more than once.
select {{ columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
