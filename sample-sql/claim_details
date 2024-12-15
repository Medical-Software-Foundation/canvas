-- Retrieves claim information, including claim ID, associated procedure codes, diagnosis codes, place of service (POS), and the current queue.

SELECT
    -- Claim details
    c.id AS claim_id,
    c.externally_exposable_id AS claim_uuid,

    -- Procedure code details
    cli.place_of_service AS cpt_pos,
    cli.proc_code AS cpt,

    -- Diagnosis code details
    cdx.code AS icd10_code,
    cdx.display AS condition,

    -- Current queue details
    q.description AS current_queue
FROM
    quality_and_revenue_claim c
LEFT JOIN public.quality_and_revenue_claimlineitem cli ON c.id = cli.claim_id
LEFT JOIN quality_and_revenue_claimdiagnosiscode cdx ON c.id = cdx.claim_id
LEFT JOIN public.quality_and_revenue_queue q ON c.current_queue_id = q.id;
