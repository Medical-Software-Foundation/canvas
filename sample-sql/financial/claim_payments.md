# Claim Payments

Aggregates payment amounts per claim and references the check number for ERAs (Electronic Remittance Advice) with multiple patients.

## SQL

```sql
SELECT
    ap.first_name || ' ' || ap.last_name AS patient_name,
    ap.key AS patient_key,
    cl.account_number AS claimaccount,
    cl.externally_exposable_id AS claim_external_id,
    pc.check_number AS check_number,
    pc.check_date AS check_date,
    SUM(nlp.amount) AS total_amount
FROM
    quality_and_revenue_newlineitempayment nlp
LEFT JOIN public.quality_and_revenue_baseposting bp ON nlp.posting_id = bp.id
LEFT JOIN quality_and_revenue_paymentcollection pc ON bp.payment_collection_id = pc.id
LEFT JOIN quality_and_revenue_claim cl ON bp.claim_id = cl.id
LEFT JOIN public.api_note an ON cl.note_id = an.id
LEFT JOIN public.api_patient ap ON an.patient_id = ap.id
GROUP BY
    ap.first_name, ap.last_name, ap.key,
    cl.account_number, pc.check_number, pc.check_date,
    cl.externally_exposable_id;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `patient_name` | Patient's full name |
| `patient_key` | Unique patient identifier |
| `claimaccount` | Claim account number |
| `claim_external_id` | External UUID for the claim |
| `check_number` | Check number from the payment collection (ERA) |
| `check_date` | Date of the check |
| `total_amount` | Sum of all line item payments for this claim/check combination |

## Notes

- Payments are grouped by patient, claim, and check — so a single claim may have multiple rows if it received payments from different checks.
