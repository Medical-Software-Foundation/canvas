# Claims Status Report

Claims grouped by their current queue/status, with balance breakdowns. Gives a snapshot of where all claims sit in the billing workflow.

## SQL

```sql
SELECT
    q.display_name                                       AS queue_status,
    q.queue_sort_ordering                                AS queue_order,
    COUNT(c.id)                                          AS claim_count,
    SUM(c.patient_balance)                               AS total_patient_balance,
    SUM(c.aggregate_coverage_balance)                    AS total_insurance_balance,
    SUM(c.patient_balance + c.aggregate_coverage_balance) AS total_balance
FROM quality_and_revenue_queue q
LEFT JOIN quality_and_revenue_claim c ON c.current_queue_id = q.id
WHERE q.queue_sort_ordering != 10   -- exclude trashed
GROUP BY q.id, q.display_name, q.queue_sort_ordering
ORDER BY q.queue_sort_ordering;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `queue_status` | Display name of the claim workflow queue |
| `queue_order` | Sort order of the queue in the workflow |
| `claim_count` | Number of claims currently in this queue |
| `total_patient_balance` | Sum of patient balances for claims in this queue |
| `total_insurance_balance` | Sum of insurance balances for claims in this queue |
| `total_balance` | Combined patient + insurance balance |

## Queue Reference

| Queue Order | Status |
|-------------|--------|
| 1 | Appointment |
| 2 | Needs Clinician Review |
| 3 | Needs Coding Review |
| 4 | Queued for Submission |
| 5 | Filed / Awaiting Response |
| 6 | Rejected / Needs Review |
| 7 | Adjudicated / Open Balance |
| 8 | Patient Balance |
| 9 | Zero Balance |

## Notes

- Trashed claims (queue order 10) are excluded.
- The LEFT JOIN ensures all queues appear even if they have zero claims.
