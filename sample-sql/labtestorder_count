-- Retrieves lab test counts grouped by test name, sorted in descending order by count.

SELECT
    -- Lab test details
    lt.ontology_test_name,

    -- Count of lab tests for each ontology test name
    COUNT(lt.ontology_test_name) AS test_count
FROM
    api_laborder lo
-- Links lab orders to lab tests
LEFT JOIN public.api_labtest lt ON lo.id = lt.order_id
GROUP BY
    lt.ontology_test_name
ORDER BY
    -- Sort by the count of tests in descending order
    test_count DESC;
