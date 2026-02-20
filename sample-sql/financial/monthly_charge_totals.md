# Monthly Charge Totals

Calculates the total charges from claims for the last 12 months, excluding charges in the Trash queue.

Ensures that months with no charges are displayed as $0 in the output by generating a full list of the last 12 months and left-joining to actual charge data.

## SQL

```sql
WITH all_months AS (
    SELECT date_trunc('month', now()) AS month
    UNION ALL
    SELECT date_trunc('month', now() - interval '1 month')
    UNION ALL
    SELECT date_trunc('month', now() - interval '2 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '3 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '4 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '5 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '6 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '7 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '8 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '9 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '10 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '11 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '12 months')
),

ordered_months AS (
    SELECT
        SUM(cli.charge) AS charge_total,
        date_trunc('month', note.datetime_of_service) AS month_of_service
    FROM quality_and_revenue_claim cl
    JOIN quality_and_revenue_claimlineitem cli ON cli.claim_id = cl.id
    JOIN api_note note ON note.id = cl.note_id
    LEFT JOIN quality_and_revenue_queue q ON q.id = cl.current_queue_id
    WHERE
        q.name <> 'Trash'
        AND cli.proc_code != 'UNLINKED'
        AND cli.status = 'active'
        AND date_trunc('month', note.datetime_of_service) >= date_trunc('month', now()) - interval '1 year'
        AND note.datetime_of_service <= now()
    GROUP BY date_trunc('month', note.datetime_of_service)
    ORDER BY date_trunc('month', note.datetime_of_service) DESC
)

SELECT
    COALESCE(om.charge_total, 0) AS charge_total,
    TO_CHAR(am.month, 'Mon YYYY') AS month_of_service
FROM
    all_months am
LEFT JOIN ordered_months om ON am.month = om.month_of_service
ORDER BY
    am.month DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `charge_total` | Total charges for the month ($0 if no charges) |
| `month_of_service` | Month and year in "Mon YYYY" format (e.g., "Dec 2024") |

## Notes

- Claims in the Trash queue are excluded.
- Unlinked procedure codes (`UNLINKED`) and inactive line items are excluded.
- The query covers the current month plus the previous 12 months (13 months total).
