-- Retrieves records from the Charge Description Master table along with payer-specific charge details.
-- Orders the results by the Charge Description Master ID in ascending order.

SELECT
    -- Charge Description Master details
    cdm.cpt_code AS CPT,
    cdm.name AS charge_name,
    cdm.charge_amount AS charge_amount,
    cdm.eff_date AS charge_startdate,
    cdm.end_date AS charge_enddate,

    -- Payer-specific charge details
    t.name AS payor,
    psc.charge_amount AS payorspecific_charge_amount,
    psc.eff_date AS payorspecific_charge_startdate,
    psc.end_date AS payorspecific_charge_enddate,
    psc.part_of_capitated_set AS payorspecific_charge_capitated
FROM
    quality_and_revenue_chargedescriptionmaster cdm
-- Links Charge Description Master to payer-specific charges
LEFT JOIN public.quality_and_revenue_payorspecificcharge psc ON cdm.id = psc.charge_id
-- Links payer-specific charges to transactor (payer) details
LEFT JOIN public.quality_and_revenue_transactor t ON psc.transactor_id = t.id
ORDER BY
    cdm.id ASC;
