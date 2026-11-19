-- Regional view: where the money sits versus where the need sits.

DROP TABLE IF EXISTS mart_region;

CREATE TABLE mart_region AS
WITH grand AS (SELECT SUM(total_commitment) AS total FROM mart_country)
SELECT
    c.region,
    COUNT(DISTINCT c.iso3)                AS n_countries,
    SUM(m.n_ops)                          AS n_ops,
    SUM(m.total_commitment)               AS total_commitment,
    SUM(m.total_commitment) / NULLIF(g.total, 0) AS value_share,
    AVG(CASE WHEN m.need_complete = 1 THEN m.sdg_gap_index END) AS mean_need_gap,
    SUM(CASE WHEN m.quadrant = 'high need / thin portfolio' THEN 1 ELSE 0 END) AS n_blindspots
FROM mart_country m
JOIN stg_country c ON c.iso3 = m.iso3
CROSS JOIN grand g
GROUP BY c.region, g.total
ORDER BY total_commitment DESC;
