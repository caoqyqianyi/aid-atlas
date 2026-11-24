-- Financing approved since the 2030 agenda started, per recipient.
--
-- mart_country sums the whole register, which mixes 2005 approvals with last
-- month's. To compare delivery with the drift in need over the same window this
-- isolates what was approved from 2015 onward, split across recipients exactly
-- as the country layer does. Commitments, not disbursements: the register does
-- not publish a disbursement series.

DROP TABLE IF EXISTS int_country_post2015;

CREATE TABLE int_country_post2015 AS
SELECT
    c.iso3,
    COUNT(DISTINCT o.project_id)        AS n_ops_post2015,
    SUM(o.commit_amt)                   AS post2015_value
FROM stg_ops o
JOIN stg_op_country c USING (project_id)
WHERE o.approval_date IS NOT NULL
  AND CAST(substr(o.approval_date, 1, 4) AS INTEGER) >= 2015
GROUP BY c.iso3;
