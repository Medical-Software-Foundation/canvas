# Revenue by Location

Revenue analysis broken down by practice location — charges, payments, and provider/patient counts per site.

## SQL

```sql
SELECT
    pl.id                                                AS location_id,
    pl.full_name                                         AS location_name,
    COUNT(DISTINCT c.id)                                 AS claim_count,
    COUNT(DISTINCT n.provider_id)                        AS provider_count,
    COUNT(DISTINCT n.patient_id)                         AS patient_count,
    SUM(cli.charge)                                      AS total_charges,
    SUM(COALESCE(pay.paid, 0))                           AS total_payments,
    SUM(cli.charge)
      - SUM(COALESCE(pay.paid, 0))
      - SUM(COALESCE(adj.adjusted, 0))                   AS outstanding_balance
FROM api_practicelocation pl
JOIN api_note n ON n.location_id = pl.id
JOIN quality_and_revenue_claim c ON c.note_id = n.id
JOIN quality_and_revenue_queue q ON q.id = c.current_queue_id
JOIN quality_and_revenue_claimlineitem cli ON cli.claim_id = c.id
  AND cli.status = 'active'
  AND cli.proc_code NOT IN ('COPAY', 'UNLINKED')
LEFT JOIN (
    SELECT nlp.billing_line_item_id, SUM(nlp.amount) AS paid
    FROM quality_and_revenue_newlineitempayment nlp
    WHERE nlp.entered_in_error_id IS NULL
    GROUP BY nlp.billing_line_item_id
) pay ON pay.billing_line_item_id = cli.id
LEFT JOIN (
    SELECT nla.billing_line_item_id, SUM(nla.amount) AS adjusted
    FROM quality_and_revenue_newlineitemadjustment nla
    WHERE nla.entered_in_error_id IS NULL AND nla.write_off = TRUE
    GROUP BY nla.billing_line_item_id
) adj ON adj.billing_line_item_id = cli.id
WHERE q.queue_sort_ordering != 10
GROUP BY pl.id, pl.full_name
ORDER BY total_charges DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `location_id` | Internal practice location ID |
| `location_name` | Full name of the practice location |
| `claim_count` | Number of distinct claims at this location |
| `provider_count` | Number of distinct providers at this location |
| `patient_count` | Number of distinct patients seen at this location |
| `total_charges` | Total amount charged |
| `total_payments` | Total payments received |
| `outstanding_balance` | Charges minus payments minus adjustments |

## Notes

- Internal system line items (`COPAY`, `UNLINKED`) are excluded from charge calculations.
- Only active line items on non-trashed claims are included.
- To filter by date range, add `AND n.datetime_of_service BETWEEN '2024-01-01' AND '2024-12-31'`.
