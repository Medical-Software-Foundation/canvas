# Claim Payments with Allowed Amounts

Aggregates payment amounts per claim, broken down by patient payments, coverage (insurance) payments, allowed amounts, and outstanding balances.

## SQL

```sql
SELECT
    ap.first_name || ' ' || ap.last_name AS patient_name,
    ap.key AS patient_key,
    cl.externally_exposable_id AS claim_uuid,
    cl.id AS claim_id,

    SUM(CASE
        WHEN pp.baseposting_ptr_id IS NOT NULL THEN nlp.amount
        ELSE 0
    END) AS patient_payment,

    SUM(CASE
        WHEN cp.baseposting_ptr_id IS NOT NULL THEN nlp.amount
        ELSE 0
    END) AS coverage_payment,

    SUM(CASE
        WHEN la.posting_id IS NOT NULL THEN la.amount
        ELSE 0
    END) AS allowed_amount,

    cl.patient_balance AS patient_balance,
    cl.aggregate_coverage_balance AS aggregate_coverage_balance
FROM
    quality_and_revenue_newlineitempayment nlp
LEFT JOIN public.quality_and_revenue_baseposting bp ON nlp.posting_id = bp.id
LEFT JOIN quality_and_revenue_paymentcollection pc ON bp.payment_collection_id = pc.id
LEFT JOIN quality_and_revenue_patientposting pp ON bp.id = pp.baseposting_ptr_id
LEFT JOIN quality_and_revenue_coverageposting cp ON bp.id = cp.baseposting_ptr_id
LEFT JOIN quality_and_revenue_lineitemallowed la ON bp.id = la.posting_id
LEFT JOIN quality_and_revenue_claim cl ON bp.claim_id = cl.id
LEFT JOIN public.api_note an ON cl.note_id = an.id
LEFT JOIN public.api_patient ap ON an.patient_id = ap.id
GROUP BY
    ap.first_name, ap.last_name, ap.key,
    cl.externally_exposable_id, cl.patient_balance,
    cl.aggregate_coverage_balance, cl.id;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `patient_name` | Patient's full name |
| `patient_key` | Unique patient identifier |
| `claim_uuid` | External UUID for the claim |
| `claim_id` | Internal claim identifier |
| `patient_payment` | Total payments posted from the patient |
| `coverage_payment` | Total payments posted from insurance |
| `allowed_amount` | Total allowed amounts from the payer |
| `patient_balance` | Current outstanding patient balance on the claim |
| `aggregate_coverage_balance` | Current outstanding insurance balance on the claim |

## Notes

- Payment type (patient vs. coverage) is determined by which posting subtype exists — `patientposting` or `coverageposting`.
- The `allowed_amount` comes from the `lineitemallowed` table and represents what the payer considers the allowable charge.
