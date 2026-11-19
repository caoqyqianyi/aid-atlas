-- Portfolio-wide health indicators, stored as key/value so the site, the
-- README and the brief can never quote different numbers for the same fact.

DROP TABLE IF EXISTS mart_portfolio_health;

CREATE TABLE mart_portfolio_health AS
WITH ops AS (
    SELECT COUNT(*) AS n_ops, SUM(COALESCE(total_amt, 0)) AS total_value FROM stg_ops
),
status_split AS (
    SELECT
        SUM(CASE WHEN status LIKE 'Active%' THEN 1 ELSE 0 END)               AS n_active,
        SUM(CASE WHEN status LIKE 'Active%' THEN COALESCE(total_amt, 0) END)  AS active_value
    FROM stg_ops
),
duration AS (
    SELECT
        AVG(impl_years)                                   AS mean_years,
        SUM(CASE WHEN impl_years >= 10 THEN 1 ELSE 0 END) AS n_over_10y,
        COUNT(impl_years)                                 AS n_dated
    FROM stg_ops
),
country AS (
    SELECT COUNT(*) AS n_countries_with_ops, SUM(total_commitment) AS country_total
    FROM mart_country
),
need AS (
    SELECT COUNT(*) AS n_with_need FROM mart_country WHERE need_complete = 1
),
concentration AS (
    SELECT SUM(hhi_contrib) AS sector_hhi FROM mart_sector
),
top10 AS (
    SELECT SUM(total_amt) AS top10_value
    FROM (SELECT total_amt FROM stg_ops WHERE total_amt IS NOT NULL
          ORDER BY total_amt DESC LIMIT 10)
)
SELECT 'total_operations'              AS metric, ops.n_ops * 1.0                       AS value, 'count' AS unit FROM ops
UNION ALL SELECT 'active_value_usd',             status_split.active_value,                      'USD'   FROM status_split
UNION ALL SELECT 'total_value_usd',              ops.total_value,                                'USD'   FROM ops
UNION ALL SELECT 'share_operations_active',      status_split.n_active * 1.0 / ops.n_ops,        'ratio' FROM ops, status_split
UNION ALL SELECT 'share_value_active',           status_split.active_value / NULLIF(ops.total_value, 0), 'ratio' FROM ops, status_split
UNION ALL SELECT 'mean_implementation_years',    duration.mean_years,                            'years' FROM duration
UNION ALL SELECT 'share_operations_over_10y',    duration.n_over_10y * 1.0 / NULLIF(duration.n_dated, 0), 'ratio' FROM duration
UNION ALL SELECT 'countries_with_portfolio',     country.n_countries_with_ops * 1.0,             'count' FROM country
UNION ALL SELECT 'countries_with_need_data',     need.n_with_need * 1.0,                         'count' FROM need
UNION ALL SELECT 'sector_hhi',                   concentration.sector_hhi,                       'index' FROM concentration
UNION ALL SELECT 'share_value_top10_operations', top10.top10_value / NULLIF(ops.total_value, 0),  'ratio' FROM top10, ops;
