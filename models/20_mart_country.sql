-- The main mart: one row per country, portfolio on the left, need on the right.
-- Terciles are computed on the ACTIVE portfolio: allocation is a question about
-- live money, not the forty-year history of a lending book.
-- Terciles are computed on the analytic population only (countries with at
-- least three of four SDG indicators), so a missing data point never gets
-- silently classified as "low need".

DROP TABLE IF EXISTS mart_country;

CREATE TABLE mart_country AS
WITH base AS (
    SELECT
        c.iso3,
        c.iso2,
        c.name,
        c.region,
        c.income_level,
        COALESCE(p.n_ops, 0)             AS n_ops,
        COALESCE(p.total_commitment, 0)  AS total_commitment,
        COALESCE(p.active_commitment, 0) AS active_commitment,
        COALESCE(p.n_active, 0)          AS n_active,
        p.mean_impl_years,
        d.median_impl_years,
        n.sdg_gap_index,
        n.gap_poverty,
        n.gap_hunger,
        n.gap_water,
        n.gap_energy,
        n.n_indicators,
        n.latest_year,
        pop.population,
        pop.year AS population_year
    FROM stg_country c
    LEFT JOIN int_country_portfolio p ON p.iso3 = c.iso3
    LEFT JOIN int_country_duration  d ON d.iso3 = c.iso3
    LEFT JOIN int_country_need      n ON n.iso3 = c.iso3
    LEFT JOIN stg_pop             pop ON pop.iso3 = c.iso3
),
scored AS (
    SELECT
        *,
        -- Financing per person is the size-neutral allocation measure: absolute
        -- portfolio value ranks countries by the size of their economy, not by
        -- how much they receive per person in need.
        CASE WHEN population > 0
             THEN active_commitment / population END AS financing_pc,
        LN(1 + COALESCE(active_commitment, 0)) AS ln_commitment,
        CASE WHEN sdg_gap_index IS NOT NULL AND n_indicators >= 3 THEN 1 ELSE 0 END AS need_complete,
        CASE WHEN population > 0 AND active_commitment > 0
             THEN LN(1 + active_commitment / population) END AS ln_financing_pc
    FROM base
),
-- Percentile ranks rather than NTILE: dozens of countries tie at zero
-- financing, and NTILE splits a tie group across terciles, which would label
-- an unfinanced country "middle". PERCENT_RANK keeps ties together.
portfolio_ranked AS (
    SELECT s.*,
           CASE WHEN PERCENT_RANK() OVER (ORDER BY COALESCE(ln_financing_pc, 0)) < 0.3333 THEN 1
                WHEN PERCENT_RANK() OVER (ORDER BY COALESCE(ln_financing_pc, 0)) < 0.6667 THEN 2
                ELSE 3 END AS portfolio_tercile
    FROM scored s
),
need_ranked AS (
    SELECT iso3,
           CASE WHEN PERCENT_RANK() OVER (ORDER BY sdg_gap_index) < 0.3333 THEN 1
                WHEN PERCENT_RANK() OVER (ORDER BY sdg_gap_index) < 0.6667 THEN 2
                ELSE 3 END AS need_tercile
    FROM scored
    WHERE need_complete = 1
)
SELECT
    p.iso3, p.iso2, p.name, p.region, p.income_level,
    p.population, p.population_year, p.financing_pc,
    p.n_ops, p.total_commitment, p.active_commitment, p.n_active,
    p.mean_impl_years, p.median_impl_years,
    p.sdg_gap_index, p.gap_poverty, p.gap_hunger, p.gap_water, p.gap_energy,
    p.n_indicators, p.latest_year, p.ln_commitment, p.need_complete,
    p.portfolio_tercile,
    nr.need_tercile,
    CASE
        WHEN nr.need_tercile IS NULL THEN 'insufficient need data'
        WHEN nr.need_tercile = 3 AND p.portfolio_tercile = 1 THEN 'high need / thin portfolio'
        WHEN nr.need_tercile = 1 AND p.portfolio_tercile = 3 THEN 'low need / heavy portfolio'
        ELSE 'aligned'
    END AS quadrant,
    -- Signed rank gap: positive means the need tercile outruns the portfolio
    -- tercile, i.e. the country carries more need than delivery.
    CASE WHEN nr.need_tercile IS NULL THEN NULL
         ELSE nr.need_tercile - p.portfolio_tercile
    END AS need_vs_portfolio_gap
FROM portfolio_ranked p
LEFT JOIN need_ranked nr ON nr.iso3 = p.iso3
ORDER BY p.total_commitment DESC;
