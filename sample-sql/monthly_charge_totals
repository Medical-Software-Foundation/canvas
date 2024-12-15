-- Calculates the total charges from claims for the last 12 months, excluding charges in the Trash queue.
-- Ensures that months with no charges are displayed as $0 in the output.

-- Step 1: Generate a list of the last 12 months dynamically.
WITH all_months AS (
    SELECT date_trunc('month', now()) AS month
    UNION ALL
    SELECT date_trunc('month', now() - interval '1 month')
    UNION ALL
    SELECT date_trunc('month', now() - interval '2 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '3 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '4 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '5 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '6 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '7 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '8 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '9 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '10 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '11 months')
    UNION ALL
    SELECT date_trunc('month', now() - interval '12 months')
),

-- Step 2: Calculate the total charges per month.
ordered_months AS (
    SELECT
        SUM(cli.charge) AS charge_total, -- Total charges for the month
        date_trunc('month', note.datetime_of_service) AS month_of_service -- Service month
    FROM quality_and_revenue_claim cl
    -- Links claims to their line items
    JOIN quality_and_revenue_claimlineitem cli ON cli.claim_id = cl.id
    -- Links claims to their associated notes
    JOIN api_note note ON note.id = cl.note_id
    -- Links claims to their current queue
    LEFT JOIN quality_and_revenue_queue q ON q.id = cl.current_queue_id
    WHERE
        q.name <> 'Trash' -- Exclude claims in the Trash queue
        AND cli.proc_code != 'UNLINKED' -- Exclude unlinked procedure codes
        AND cli.status = 'active' -- Include only active line items
        AND date_trunc('month', note.datetime_of_service) >= date_trunc('month', now()) - interval '1 year'
        AND note.datetime_of_service <= now()
    GROUP BY date_trunc('month', note.datetime_of_service)
    ORDER BY date_trunc('month', note.datetime_of_service) DESC
)

-- Step 3: Combine the charge data with all months to ensure $0 for months without charges.
SELECT
    COALESCE(om.charge_total, 0) AS charge_total, -- Total charges or $0 if no charges
    TO_CHAR(am.month, 'Mon YYYY') AS month_of_service -- Month and year in "Dec 2024" format
FROM
    all_months am
LEFT JOIN ordered_months om ON am.month = om.month_of_service
ORDER BY
    am.month DESC; -- Sort by month in descending order
