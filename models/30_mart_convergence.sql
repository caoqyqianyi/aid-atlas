-- Did measured need move, and did financing move with it?
--
-- One row per country that reports at least three indicators both in 2015
-- (the year the SDG framework was adopted) and in 2021 or later. The later
-- reading is each country's own most recent qualifying year, because the series
-- end unevenly - 2024 is still sparse. delta_pp is in percentage points of
-- population not yet served: negative means need fell.
--
-- The money column covers the same window, approved 2015 onward, per person.
-- It is deliberately a flow against a change, not a level against a level,
-- because comparing the 2024 stock of commitments with the 2024 need reading
-- would mix an eleven-year book with a one-year measurement.

DROP TABLE IF EXISTS mart_convergence;

CREATE TABLE mart_convergence AS
WITH baseline AS (
    SELECT iso3, need_index AS need_2015
    FROM int_country_need_history
    WHERE year = 2015 AND n_indicators >= 3
),
late_ranked AS (
    SELECT
        iso3,
        year,
        need_index,
        ROW_NUMBER() OVER (PARTITION BY iso3 ORDER BY year DESC) AS rn
    FROM int_country_need_history
    WHERE year >= 2021 AND n_indicators >= 3
),
late AS (
    SELECT iso3, year AS latest_year, need_index AS need_latest
    FROM late_ranked
    WHERE rn = 1
)
SELECT
    c.iso3,
    c.name,
    c.region,
    c.income_level,
    c.population,
    b.need_2015,
    l.need_latest,
    l.latest_year,
    ROUND(l.need_latest - b.need_2015, 2)                       AS delta_pp,
    CASE WHEN l.need_latest - b.need_2015 <= -2 THEN 1 ELSE 0 END AS improved,
    CASE WHEN l.need_latest - b.need_2015 >=  2 THEN 1 ELSE 0 END AS worsened,
    COALESCE(p.n_ops_post2015, 0)                               AS post2015_ops,
    COALESCE(p.post2015_value, 0)                               AS post2015_value,
    ROUND(COALESCE(p.post2015_value, 0) / NULLIF(c.population, 0), 2) AS post2015_pc,
    c.financing_pc,
    c.allocation_gap,
    pr.priority_rank
FROM mart_country c
JOIN baseline b USING (iso3)
JOIN late l USING (iso3)
LEFT JOIN int_country_post2015 p USING (iso3)
LEFT JOIN mart_priority pr USING (iso3)
ORDER BY delta_pp;
