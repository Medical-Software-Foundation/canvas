-- Calculates the remittance denial rate for distinct claims based on specific adjustment codes.
-- Includes claims received from the clearinghouse over a rolling 12-month period.

-- Step 1: Identify all claims that have had a remittance posted within the last 12 months.
WITH submitted AS (
    SELECT DISTINCT 
        cl.id AS claim_id,
        'Last 30 Days' AS remit_month,
        0 AS month_order,
        NULL::date AS date_month
    FROM quality_and_revenue_claim cl
    JOIN quality_and_revenue_baseposting bp ON cl.id = bp.claim_id
    JOIN quality_and_revenue_coverageposting cp ON cp.baseposting_ptr_id = bp.id
    WHERE 
        bp.created >= (date_trunc('day', now()) - interval '30 days')
        AND bp.created <= now()
        AND bp.entered_in_error_id IS NULL
        AND cp.remittance_id IS NOT NULL
    
    UNION ALL

    SELECT DISTINCT 
        cl.id AS claim_id,
        to_char(bp.created, 'Mon') AS remit_month,
        1 AS month_order,
        date_trunc('month', bp.created) AS date_month
    FROM quality_and_revenue_claim cl
    JOIN quality_and_revenue_baseposting bp ON cl.id = bp.claim_id
    JOIN quality_and_revenue_coverageposting cp ON cp.baseposting_ptr_id = bp.id
    WHERE 
        date_trunc('day', bp.created) >= (date_trunc('day', now()) - interval '1 year')
        AND bp.created < date_trunc('month', now())
        AND bp.entered_in_error_id IS NOT NULL
),

-- Step 2: Identify distinct claims with denial adjustment codes of interest.
denials AS (
    SELECT DISTINCT 
        sb.claim_id AS id,
        sb.remit_month
    FROM submitted sb
    JOIN quality_and_revenue_claimlineitem cli ON cli.claim_id = sb.claim_id
    JOIN quality_and_revenue_newlineitemadjustment adj ON adj.billing_line_item_id = cli.id
    WHERE 
        adj.group NOT IN ('PR', 'CW') -- Exclude transfers and PR adjustments
        AND adj.code IN ( -- Denial adjustment codes
            '4','5','6','7','8','9','10','11','12','13','14','15','16','17','18','19','20','21','22','26','27','28','29','30','31','32','33',
            /* (More codes truncated for brevity) */
            'D6','D7','D8','P1','P10','P11','P12','P13','P14','P15','P16','P17','P2','P7','P8','P9'
        )
),

-- Step 3: Count the total claims with denials for each month.
count_denials AS (
    SELECT 
        COUNT(id) AS count_denials,
        remit_month
    FROM denials
    GROUP BY remit_month
),

-- Step 4: Count the total number of claims received for each month.
count_claims AS (
    SELECT 
        COUNT(sb.claim_id) AS count_claims,
        sb.remit_month,
        sb.month_order,
        sb.date_month
    FROM submitted sb
    GROUP BY remit_month, month_order, date_month
)

-- Final Calculation: Compute the denial rate by comparing the count of denials to the total claims.
SELECT 
    cc.count_claims,
    cd.count_denials,
    CASE 
        WHEN cd.count_denials IS NULL THEN 0
        ELSE ROUND(((cd.count_denials::numeric / cc.count_claims::numeric) * 100), 2)
    END AS PercentDenied,
    cc.remit_month,
    cc.date_month
FROM 
    count_claims cc
LEFT JOIN count_denials cd ON cd.remit_month = cc.remit_month
ORDER BY 
    cc.month_order ASC, 
    cc.date_month DESC;
