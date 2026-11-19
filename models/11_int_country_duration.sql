-- Median implementation duration per country.
-- SQLite has no median(), so this uses the standard two-row average of the
-- ranked series, which is exact for both odd and even counts.

DROP TABLE IF EXISTS int_country_duration;

CREATE TABLE int_country_duration AS
WITH ranked AS (
    SELECT
        c.iso3,
        o.impl_years,
        ROW_NUMBER() OVER (PARTITION BY c.iso3 ORDER BY o.impl_years) AS rn,
        COUNT(*)     OVER (PARTITION BY c.iso3)                        AS cnt
    FROM stg_op_country c
    JOIN stg_ops o ON o.project_id = c.project_id
    WHERE o.impl_years IS NOT NULL
)
SELECT
    iso3,
    AVG(CASE WHEN rn BETWEEN (cnt + 1) / 2 AND (cnt + 2) / 2 THEN impl_years END) AS median_impl_years,
    MAX(cnt) AS n_with_dates
FROM ranked
GROUP BY iso3;
