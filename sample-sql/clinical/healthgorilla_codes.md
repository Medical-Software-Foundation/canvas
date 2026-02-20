# Health Gorilla Order Codes

Retrieves Health Gorilla lab order codes, including associated order names and lab names.

Only includes records where the order code is not null.

## SQL

```sql
SELECT
    hgl.order_code AS health_gorilla_order_code,
    hgl.order_name,
    lab.name AS lab_name
FROM
    health_gorilla_labtest hgl
LEFT JOIN health_gorilla_lab lab ON hgl.lab_id = lab.id
WHERE
    hgl.order_code IS NOT NULL;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `health_gorilla_order_code` | The Health Gorilla order code for the lab test |
| `order_name` | Name of the lab order |
| `lab_name` | Name of the laboratory |
