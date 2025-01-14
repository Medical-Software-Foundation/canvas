-- Aggregates payment amounts per claim with patient payments, coverage payments, allowed amounts, and outstanding balances.

SELECT
    -- Patient details
    ap.first_name || ' ' || ap.last_name AS patient_name,
    ap.key AS patient_key,

    -- Claim details
    cl.externally_exposable_id AS claim_uuid,
    cl.id AS claim_id,

    -- Aggregated payment details
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

    -- Outstanding balances from the claim table
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
    ap.first_name,
    ap.last_name,
    ap.key,
    cl.externally_exposable_id,
    cl.patient_balance,
    cl.aggregate_coverage_balance,
    cl.id;
