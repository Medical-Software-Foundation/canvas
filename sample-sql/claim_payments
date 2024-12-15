-- Aggregates payment amounts per claim and references the check number for ERAs with multiple patients.

SELECT
    -- Patient details
    ap.first_name || ' ' || ap.last_name AS patient_name,
    ap.key AS patient_key,

    -- Claim details
    cl.account_number AS claimaccount,
    cl.externally_exposable_id as claim_external_id,

    -- Payment collection details
    pc.check_number AS check_number,
    pc.check_date AS check_date,

    -- Aggregated payment amount
    SUM(nlp.amount) AS total_amount
FROM
    quality_and_revenue_newlineitempayment nlp
LEFT JOIN public.quality_and_revenue_baseposting bp ON nlp.posting_id = bp.id
LEFT JOIN quality_and_revenue_paymentcollection pc ON bp.payment_collection_id = pc.id
LEFT JOIN quality_and_revenue_claim cl ON bp.claim_id = cl.id
LEFT JOIN public.api_note an ON cl.note_id = an.id
LEFT JOIN public.api_patient ap ON an.patient_id = ap.id
GROUP BY
    ap.first_name,
    ap.last_name,
    ap.key,
    cl.account_number,
    pc.check_number,
    pc.check_date,
    cl.externally_exposable_id;
