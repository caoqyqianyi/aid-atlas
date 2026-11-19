-- Sector mix and concentration.
-- A Herfindahl index on value share separates a diversified book from a
-- handful of large operations wearing a portfolio hat.

DROP TABLE IF EXISTS mart_sector;

CREATE TABLE mart_sector AS
WITH totals AS (
    -- Shares are of classified value. About a fifth of the book carries no
    -- sector in the source; dividing by it would understate every bar.
    SELECT SUM(total_amt) AS grand_total
    FROM stg_ops
    WHERE sector_group NOT IN ('Unclassified', 'Other')
),
by_sector AS (
    SELECT
        sector_group    AS sector,
        COUNT(*)        AS n_ops, 
        SUM(total_amt) AS total_value,
        AVG(total_amt) AS mean_value
    FROM stg_ops
    WHERE total_amt IS NOT NULL AND sector_group IN (SELECT DISTINCT sector_group FROM stg_ops WHERE sector_group NOT IN ('Unclassified','Other'))
    GROUP BY sector_group
)
SELECT
    b.sector,
    b.n_ops,
    b.total_value,
    b.mean_value,
    b.total_value / NULLIF(t.grand_total, 0)           AS value_share,
    (b.total_value / NULLIF(t.grand_total, 0))
        * (b.total_value / NULLIF(t.grand_total, 0))   AS hhi_contrib,
    RANK() OVER (ORDER BY b.total_value DESC)          AS value_rank
FROM by_sector b
CROSS JOIN totals t
ORDER BY b.total_value DESC;
