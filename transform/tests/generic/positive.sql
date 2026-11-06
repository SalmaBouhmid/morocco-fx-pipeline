{% test positive(model, column_name) %}
-- Fails for every row where the column is zero or negative (nulls are not checked here).
select *
from {{ model }}
where {{ column_name }} <= 0
{% endtest %}
