# Claim Details

Retrieves claim information, including claim ID, associated procedure codes (CPT), diagnosis codes (ICD-10), place of service, and the current workflow queue.

## SQL

```sql
SELECT
    c.id AS claim_id,
    c.externally_exposable_id AS claim_uuid,
    cli.place_of_service AS cpt_pos,
    cli.proc_code AS cpt,
    cdx.code AS icd10_code,
    cdx.display AS condition,
    q.description AS current_queue
FROM
    quality_and_revenue_claim c
LEFT JOIN public.quality_and_revenue_claimlineitem cli ON c.id = cli.claim_id
LEFT JOIN quality_and_revenue_claimdiagnosiscode cdx ON c.id = cdx.claim_id
LEFT JOIN public.quality_and_revenue_queue q ON c.current_queue_id = q.id;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `claim_id` | Internal claim identifier |
| `claim_uuid` | External UUID for the claim |
| `cpt_pos` | Place of service code on the line item |
| `cpt` | Procedure (CPT) code |
| `icd10_code` | Diagnosis (ICD-10) code |
| `condition` | Display name of the diagnosis |
| `current_queue` | Description of the current claim workflow queue |

## Notes

- This query returns all claims with no filters applied. You may want to add WHERE clauses to filter by queue, date range, or other criteria.
- Claims with multiple line items or diagnosis codes will appear as multiple rows.
