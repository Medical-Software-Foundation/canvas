# Payment Report

Pulls all active line-item payments with the associated claim, billing code, and posting date.

## SQL

```sql
SELECT
    c.id                        AS claim_id,
    pmt.amount                  AS paid_amount,
    bp.created                  AS posted_date,
    cli.proc_code               AS billing_code
FROM quality_and_revenue_newlineitempayment pmt
JOIN quality_and_revenue_baseposting bp
    ON bp.id = pmt.posting_id
JOIN quality_and_revenue_claim c
    ON c.id = bp.claim_id
JOIN quality_and_revenue_claimlineitem cli
    ON cli.id = pmt.billing_line_item_id
WHERE pmt.entered_in_error_id IS NULL
  AND bp.entered_in_error_id IS NULL
ORDER BY bp.created DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `claim_id` | Internal claim identifier |
| `paid_amount` | Payment amount applied to the line item |
| `posted_date` | Date/time the posting was created (not the check date) |
| `billing_code` | CPT/procedure code from the claim line item |

## Notes

- Only active payments are included — entered-in-error payments and postings are excluded.
- These queries have not been validated against a live database.
- To filter by date range, add `AND bp.created >= '2024-01-01'`.
