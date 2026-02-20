# Prescription Status Report

Counts prescriptions by their current e-prescribing status, with date ranges and patient/prescriber counts.

## SQL

```sql
SELECT
    p.status,
    COUNT(*)                                 AS total,
    COUNT(DISTINCT p.patient_id)             AS unique_patients,
    COUNT(DISTINCT p.prescriber_id)          AS unique_prescribers,
    MIN(p.written_date)                      AS earliest_written,
    MAX(p.written_date)                      AS latest_written
FROM api_prescription p
WHERE p.deleted = false
  AND p.committer_id IS NOT NULL
  AND p.entered_in_error_id IS NULL
GROUP BY p.status
ORDER BY total DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `status` | Prescription status code (see reference below) |
| `total` | Number of prescriptions in this status |
| `unique_patients` | Number of distinct patients |
| `unique_prescribers` | Number of distinct prescribers |
| `earliest_written` | Oldest written date in this status |
| `latest_written` | Most recent written date in this status |

## Status Reference

| Status | Meaning |
|--------|---------|
| `open` | Newly created, not yet transmitted |
| `pending` | Awaiting pharmacy response |
| `ultimately-accepted` | Accepted by pharmacy |
| `error` | Transmission or processing error |
| `cancel-requested` | Cancellation has been requested |
| `canceled` | Successfully cancelled |
| `cancel-denied` | Pharmacy denied the cancellation |
| `received` | Received by the e-prescribing network |
| `signed` | Signed by the prescriber |
| `inqueue` | Queued for transmission |
| `transmitted` | Sent to the pharmacy |
| `delivered` | Confirmed delivered to the pharmacy |
