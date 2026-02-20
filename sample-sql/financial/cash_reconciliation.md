# Cash Reconciliation

Daily collections vs. amounts actually posted to claims, broken down by payment method. Defaults to the last 7 days.

Useful for identifying unposted payments and reconciling daily cash intake.

## SQL

```sql
SELECT
    d.report_date,
    COALESCE(collections.total_collected, 0)             AS total_collected,
    COALESCE(collections.cash_collected, 0)              AS cash_collected,
    COALESCE(collections.check_collected, 0)             AS check_collected,
    COALESCE(collections.card_collected, 0)              AS card_collected,
    COALESCE(collections.other_collected, 0)             AS other_collected,
    COALESCE(collections.collection_count, 0)            AS number_of_payments,
    COALESCE(posted.total_posted_payments, 0)            AS total_posted_to_claims,
    COALESCE(collections.total_collected, 0)
      - COALESCE(posted.total_posted_payments, 0)        AS unposted_variance
FROM (
    SELECT generate_series(
        CURRENT_DATE - INTERVAL '6 days',
        CURRENT_DATE,
        '1 day'
    )::date AS report_date
) d
LEFT JOIN (
    SELECT
        pc.created::date                                 AS collection_date,
        SUM(pc.total_collected)                          AS total_collected,
        SUM(CASE WHEN pc.method = 'cash'  THEN pc.total_collected ELSE 0 END) AS cash_collected,
        SUM(CASE WHEN pc.method = 'check' THEN pc.total_collected ELSE 0 END) AS check_collected,
        SUM(CASE WHEN pc.method = 'card'  THEN pc.total_collected ELSE 0 END) AS card_collected,
        SUM(CASE WHEN pc.method = 'other' THEN pc.total_collected ELSE 0 END) AS other_collected,
        COUNT(*)                                         AS collection_count
    FROM quality_and_revenue_paymentcollection pc
    WHERE pc.entered_in_error_id IS NULL
    GROUP BY pc.created::date
) collections ON collections.collection_date = d.report_date
LEFT JOIN (
    SELECT
        bp.created::date                                 AS posting_date,
        SUM(nlp.amount)                                  AS total_posted_payments
    FROM quality_and_revenue_baseposting bp
    JOIN quality_and_revenue_newlineitempayment nlp ON nlp.posting_id = bp.id
    WHERE bp.entered_in_error_id IS NULL
      AND nlp.entered_in_error_id IS NULL
    GROUP BY bp.created::date
) posted ON posted.posting_date = d.report_date
ORDER BY d.report_date;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `report_date` | The date |
| `total_collected` | Total amount collected across all payment methods |
| `cash_collected` | Cash collections |
| `check_collected` | Check collections |
| `card_collected` | Credit/debit card collections |
| `other_collected` | Other payment method collections |
| `number_of_payments` | Count of payment collections for the day |
| `total_posted_to_claims` | Total amount actually posted to claims |
| `unposted_variance` | Difference between collected and posted (unposted amount) |

## Tips

- Change `INTERVAL '6 days'` to `'29 days'` for a monthly view, or `'89 days'` for a quarterly view.
- A positive `unposted_variance` means money was collected but not yet applied to claims.
- Days with no collections or postings will show $0 (not be omitted).

## Notes

- Entered-in-error payment collections and postings are excluded.
- Collections are matched to postings by date — a timing mismatch (collected one day, posted the next) will show as variance.
