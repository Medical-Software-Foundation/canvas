-- Aggregates current patient balances for all claims associated with each patient.

WITH claims AS (
    SELECT 
        -- Claim and patient details
        c.id AS claim_id, 
        c.externally_exposable_id AS claim_uuid, 
        c.patient_balance, 
        p.key AS patient_key
    FROM 
        quality_and_revenue_claim c
    -- Links claims to notes to retrieve associated patients
    JOIN api_note n ON n.id = c.note_id
    JOIN api_patient p ON p.id = n.patient_id
    -- Links claims to their current processing queue
    INNER JOIN quality_and_revenue_queue q ON c.current_queue_id = q.id
    WHERE 
        -- Exclude claims with a negative balance that are fully processed
        NOT (
            c.id IN (
                SELECT 
                    V0.id 
                FROM 
                    quality_and_revenue_claim V0
                LEFT JOIN quality_and_revenue_baseposting V1 ON V0.id = V1.claim_id
                LEFT JOIN quality_and_revenue_coverageposting V2 ON V1.id = V2.baseposting_ptr_id
                WHERE 
                    V0.patient_balance < 0
                    AND NOT EXISTS (
                        SELECT 1
                        FROM quality_and_revenue_claim U0
                        LEFT JOIN api_coverage U1 ON U0.id = V1.claim_id
                        WHERE U1.id IS NULL AND U0.id = V0.id
                        LIMIT 1
                    )
                GROUP BY 
                    V0.id
                HAVING 
                    COUNT(V1.id) FILTER (
                        WHERE V2.baseposting_ptr_id IS NOT NULL 
                        AND V1.entered_in_error_id IS NULL
                    ) = 0
            )
        )
        -- Exclude claims in "Trash" or "ZeroBalance" queues
        AND q.name NOT IN ('Trash', 'ZeroBalance')
)
-- Summarize total patient balance grouped by patient
SELECT 
    patient_key, 
    SUM(patient_balance) AS total_patient_balance
FROM 
    claims
GROUP BY 
    patient_key;
