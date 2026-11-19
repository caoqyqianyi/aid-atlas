-- Country-level portfolio aggregates.
-- Amounts are split across co-financed countries upstream, so summing this
-- table reproduces the global portfolio total exactly.

DROP TABLE IF EXISTS int_country_portfolio;

CREATE TABLE int_country_portfolio AS
SELECT
    link.iso3,
    COUNT(DISTINCT link.project_id)                           AS n_ops,
    SUM(link.amount_share)                                    AS total_commitment,
    SUM(CASE WHEN link.is_active THEN link.amount_share END)  AS active_commitment,
    SUM(link.is_active)                                       AS n_active,
    AVG(link.impl_years)                                      AS mean_impl_years,
    MIN(link.approval_date)                                   AS first_approval,
    MAX(link.approval_date)                                   AS latest_approval
FROM (
    SELECT
        c.iso3,
        c.project_id,
        c.amount_share,
        o.impl_years,
        o.approval_date,
        CASE WHEN o.status LIKE 'Active%' THEN 1 ELSE 0 END AS is_active
    FROM stg_op_country c
    JOIN stg_ops o ON o.project_id = c.project_id
) link
GROUP BY link.iso3;
