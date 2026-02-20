# Active Coverages

Retrieves details of active patients and their insurance coverage, including care team lead information.

Only includes patients who are currently active, with coverage in an active state and no end date (indicating ongoing coverage).

## SQL

```sql
SELECT
    -- Patient details
    ap.key AS patient_key,
    ap.first_name AS patient_firstname,
    ap.last_name AS patient_lastname,
    ap.birth_date,

    -- Coverage details
    c.patient_relationship_to_subscriber,
    c.coverage_rank,
    c.state AS coverage_state,
    tr.payer_id,
    tr.name AS coverage_name,
    tr.type,
    c.id_number AS coverage_id,
    c.plan,
    c.group,
    c.coverage_start_date,
    c.coverage_end_date,

    -- Care team information
    st.first_name || ' ' || st.last_name AS team_lead
FROM api_coverage c
LEFT JOIN quality_and_revenue_transactor tr ON c.issuer_id = tr.id
LEFT JOIN api_patient ap ON c.patient_id = ap.id
LEFT JOIN api_careteammembership ac ON ap.id = ac.patient_id AND ac.lead = 'true'
LEFT JOIN api_staff st ON ac.staff_id = st.id
WHERE
    c.state ILIKE 'active'
    AND ap.active = 'true'
    AND c.coverage_end_date IS NULL
ORDER BY
    ap.key DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `patient_key` | Unique identifier for the patient |
| `patient_firstname` | Patient's first name |
| `patient_lastname` | Patient's last name |
| `birth_date` | Patient's date of birth |
| `patient_relationship_to_subscriber` | Relationship of the patient to the coverage subscriber |
| `coverage_rank` | Rank of the coverage (e.g., primary, secondary) |
| `coverage_state` | Current state of the coverage |
| `payer_id` | Identifier for the payer organization |
| `coverage_name` | Name of the insurance coverage |
| `type` | Type of coverage (e.g., commercial, Medicaid) |
| `coverage_id` | Insurance ID number for the patient |
| `plan` | Plan name or description |
| `group` | Group name or number |
| `coverage_start_date` | Start date of the coverage |
| `coverage_end_date` | End date of the coverage (NULL indicates active coverage) |
| `team_lead` | Name of the patient's care team lead |

## Notes

- Results are sorted by patient key descending (most recent patients first).
- Only coverage records without an end date are included.
