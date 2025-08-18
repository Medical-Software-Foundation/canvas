-- Retrieves details of active patients and their insurance coverage, including team lead information.

SELECT
    -- Patient details
    ap.key AS patient_key, -- Unique identifier for the patient
    ap.first_name AS patient_firstname, 
    ap.last_name AS patient_lastname,
    ap.birth_date, -- Patient's date of birth
    
    -- Coverage details
    c.patient_relationship_to_subscriber, -- Relationship of the patient to the coverage subscriber
    c.coverage_rank, -- Rank of the coverage (e.g., primary, secondary)
    c.state AS coverage_state, -- Current state of the coverage
    tr.payer_id, -- Identifier for the payer organization
    tr.name AS coverage_name, -- Name of the insurance coverage
    tr.type, -- Type of coverage (e.g., commercial, Medicaid)
    c.id_number AS coverage_id, -- Insurance ID number for the patient
    c.plan, -- Plan name or description
    c.group, -- Group name or number
    c.coverage_start_date, -- Start date of the coverage
    c.coverage_end_date, -- End date of the coverage (NULL indicates active coverage)
    
    -- Care team information
    st.first_name || ' ' || st.last_name AS team_lead -- Name of the patient's care team lead
FROM api_coverage c
-- Joins to connect coverage with payer information
LEFT JOIN quality_and_revenue_transactor tr ON c.issuer_id = tr.id
-- Joins to retrieve patient information
LEFT JOIN api_patient ap ON c.patient_id = ap.id
-- Joins to find the care team lead for the patient
LEFT JOIN api_careteammembership ac ON ap.id = ac.patient_id AND ac.lead = 'true'
LEFT JOIN api_staff st ON ac.staff_id = st.id
WHERE 
    -- Include only active coverage
    c.state ILIKE 'active'
    -- Include only active patients
    AND ap.active = 'true'
    -- Exclude coverage records with an end date
    AND c.coverage_end_date IS NULL
ORDER BY 
    -- Sort by patient key in descending order for easier review of recent records
    ap.key DESC;
