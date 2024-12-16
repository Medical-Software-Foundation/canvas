-- Retrieves Health Gorilla order codes, including associated order names and lab names.

SELECT
    -- Order details
    hgl.order_code AS health_gorilla_order_code,
    hgl.order_name,
    
    -- Lab details
    lab.name AS lab_name
FROM 
    health_gorilla_labtest hgl
-- Links lab tests to their associated labs
LEFT JOIN health_gorilla_lab lab ON hgl.lab_id = lab.id
WHERE 
    -- Include only rows where the order code is not null
    hgl.order_code IS NOT NULL;
