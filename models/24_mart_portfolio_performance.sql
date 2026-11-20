-- Operating profile of the book.
--
-- The country layer answers "where should a review look". This model answers
-- "how is the book run": what is still live, when the live work was approved,
-- how long operations are planned to run, how concentrated the value is.
-- Every row is a bucket on one dimension, weighted both by count and by value,
-- because a review team cares about the second as much as the first.

DROP TABLE IF EXISTS mart_portfolio_performance;

CREATE TABLE mart_portfolio_performance AS
WITH base AS (
    SELECT
        project_id, status, approval_date, impl_years, total_amt, multi_country,
        CASE WHEN status LIKE 'Active%'   THEN 1 ELSE 0 END AS is_active,
        CASE WHEN status LIKE 'Closed%'   THEN 1 ELSE 0 END AS is_closed,
        CASE WHEN status LIKE 'Pipeline%' THEN 1 ELSE 0 END AS is_pipeline,
        CASE WHEN status LIKE 'Dropped%'  THEN 1 ELSE 0 END AS is_dropped,
        CASE WHEN approval_date IS NULL THEN NULL
             ELSE CAST(substr(approval_date, 1, 4) AS INTEGER) END AS approval_year
    FROM stg_ops
),
total AS (
    SELECT COUNT(*) AS n_ops, SUM(COALESCE(total_amt, 0)) AS value FROM base
),
status_rows AS (
    SELECT
        'status' AS dimension,
        CASE WHEN is_active = 1   THEN 'Active'
             WHEN is_closed = 1   THEN 'Closed'
             WHEN is_pipeline = 1 THEN 'Pipeline'
             WHEN is_dropped = 1  THEN 'Dropped'
             ELSE 'No status recorded' END AS bucket,
        CASE WHEN is_active = 1 THEN 1 WHEN is_closed = 1 THEN 2
             WHEN is_pipeline = 1 THEN 3 WHEN is_dropped = 1 THEN 4 ELSE 5 END AS sort_order,
        COUNT(*) AS n_ops,
        SUM(COALESCE(total_amt, 0)) AS value,
        COUNT(*) * 1.0 / (SELECT n_ops FROM total) AS share_ops,
        SUM(COALESCE(total_amt, 0)) / NULLIF((SELECT value FROM total), 0) AS share_value,
        NULL AS active_share
    FROM base
    GROUP BY 2, 3
),
cohort_rows AS (
    SELECT
        'cohort' AS dimension,
        CASE WHEN approval_year IS NULL THEN 'No approval date'
             WHEN approval_year < 1960 THEN 'Before 1960'
             WHEN approval_year < 1970 THEN '1960s'
             WHEN approval_year < 1980 THEN '1970s'
             WHEN approval_year < 1990 THEN '1980s'
             WHEN approval_year < 2000 THEN '1990s'
             WHEN approval_year < 2010 THEN '2000s'
             WHEN approval_year < 2020 THEN '2010s'
             ELSE '2020 onwards' END AS bucket,
        CASE WHEN approval_year IS NULL THEN 99
             WHEN approval_year < 1960 THEN 1 WHEN approval_year < 1970 THEN 2
             WHEN approval_year < 1980 THEN 3 WHEN approval_year < 1990 THEN 4
             WHEN approval_year < 2000 THEN 5 WHEN approval_year < 2010 THEN 6
             WHEN approval_year < 2020 THEN 7 ELSE 8 END AS sort_order,
        COUNT(*) AS n_ops,
        SUM(COALESCE(total_amt, 0)) AS value,
        COUNT(*) * 1.0 / (SELECT n_ops FROM total) AS share_ops,
        SUM(COALESCE(total_amt, 0)) / NULLIF((SELECT value FROM total), 0) AS share_value,
        SUM(CASE WHEN is_active = 1 THEN COALESCE(total_amt, 0) ELSE 0 END)
            / NULLIF(SUM(COALESCE(total_amt, 0)), 0) AS active_share
    FROM base
    GROUP BY 2, 3
),
duration_rows AS (
    SELECT
        'duration' AS dimension,
        CASE WHEN impl_years IS NULL THEN 'No dates'
             WHEN impl_years < 2 THEN 'Under 2 years'
             WHEN impl_years < 5 THEN '2 to 5 years'
             WHEN impl_years < 10 THEN '5 to 10 years'
             WHEN impl_years < 20 THEN '10 to 20 years'
             ELSE '20 years or more' END AS bucket,
        CASE WHEN impl_years IS NULL THEN 99 WHEN impl_years < 2 THEN 1
             WHEN impl_years < 5 THEN 2 WHEN impl_years < 10 THEN 3
             WHEN impl_years < 20 THEN 4 ELSE 5 END AS sort_order,
        COUNT(*) AS n_ops,
        SUM(COALESCE(total_amt, 0)) AS value,
        COUNT(*) * 1.0 / (SELECT n_ops FROM total) AS share_ops,
        SUM(COALESCE(total_amt, 0)) / NULLIF((SELECT value FROM total), 0) AS share_value,
        NULL AS active_share
    FROM base
    GROUP BY 2, 3
),
ranked AS (
    SELECT total_amt, ROW_NUMBER() OVER (ORDER BY total_amt DESC) AS rn
    FROM base
    WHERE total_amt IS NOT NULL
),
concentration_rows AS (
    SELECT
        'concentration' AS dimension,
        'largest ' || k || ' operations' AS bucket,
        k AS sort_order,
        k AS n_ops,
        (SELECT SUM(total_amt) FROM ranked WHERE rn <= k) AS value,
        k * 1.0 / (SELECT n_ops FROM total) AS share_ops,
        (SELECT SUM(total_amt) FROM ranked WHERE rn <= k)
            / NULLIF((SELECT value FROM total), 0) AS share_value,
        NULL AS active_share
    FROM (SELECT 1 AS k UNION ALL SELECT 5 UNION ALL SELECT 10
          UNION ALL SELECT 25 UNION ALL SELECT 50)
)
SELECT * FROM status_rows
UNION ALL SELECT * FROM cohort_rows
UNION ALL SELECT * FROM duration_rows
UNION ALL SELECT * FROM concentration_rows
ORDER BY dimension, sort_order;
