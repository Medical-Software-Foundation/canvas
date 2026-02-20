# Revenue by CPT Code

Shows revenue breakdown by procedure code — total charges, payments received, write-off adjustments, and outstanding balance per CPT.

## SQL

```sql
SELECT
    cli.proc_code                                        AS cpt_code,
    COALESCE(NULLIF(cli.display, ''), cli.proc_code)     AS description,
    COUNT(DISTINCT c.id)                                 AS claim_count,
    SUM(cli.units)                                       AS total_units,
    SUM(cli.charge)                                      AS total_charges,
    SUM(COALESCE(pay.paid, 0))                           AS total_payments,
    SUM(COALESCE(adj.adjusted, 0))                       AS total_adjustments,
    SUM(cli.charge)
      - SUM(COALESCE(pay.paid, 0))
      - SUM(COALESCE(adj.adjusted, 0))                   AS outstanding_balance
FROM quality_and_revenue_claimlineitem cli
JOIN quality_and_revenue_claim c ON c.id = cli.claim_id
JOIN quality_and_revenue_queue q ON q.id = c.current_queue_id
LEFT JOIN (
    SELECT nlp.billing_line_item_id,
           SUM(nlp.amount) AS paid
    FROM quality_and_revenue_newlineitempayment nlp
    WHERE nlp.entered_in_error_id IS NULL
    GROUP BY nlp.billing_line_item_id
) pay ON pay.billing_line_item_id = cli.id
LEFT JOIN (
    SELECT nla.billing_line_item_id,
           SUM(nla.amount) AS adjusted
    FROM quality_and_revenue_newlineitemadjustment nla
    WHERE nla.entered_in_error_id IS NULL
      AND nla.write_off = TRUE
    GROUP BY nla.billing_line_item_id
) adj ON adj.billing_line_item_id = cli.id
WHERE cli.status = 'active'
  AND q.queue_sort_ordering != 10   -- exclude trashed claims
  AND cli.proc_code NOT IN ('COPAY', 'UNLINKED')
GROUP BY cli.proc_code, COALESCE(NULLIF(cli.display, ''), cli.proc_code)
ORDER BY total_charges DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `cpt_code` | CPT procedure code |
| `description` | Display name for the procedure (falls back to code if blank) |
| `claim_count` | Number of distinct claims using this CPT code |
| `total_units` | Total units billed across all claims |
| `total_charges` | Total amount charged |
| `total_payments` | Total payments received |
| `total_adjustments` | Total write-off adjustments |
| `outstanding_balance` | Charges minus payments minus adjustments |

## Notes

- Internal system line items (`COPAY`, `UNLINKED`) are excluded.
- Only active line items on non-trashed claims are included.
- Only write-off adjustments are counted (contractual adjustments); non-write-off adjustments are excluded.
- To filter by date range, add `AND n.datetime_of_service BETWEEN '2024-01-01' AND '2024-12-31'` (join `api_note n ON n.id = c.note_id` first).
