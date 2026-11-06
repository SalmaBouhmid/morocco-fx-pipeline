{% macro generate_schema_name(custom_schema_name, node) -%}
    {#- Use "staging" / "marts" / "reference" as schema names (instead of "main_staging"). -#}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
