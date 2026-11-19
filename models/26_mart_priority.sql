-- The short list this analysis exists to produce.
--
-- A hard 3x3 cell would be cleaner to draw but would discard the countries
-- just outside it. Instead the list ranks by the allocation gap built in
-- model 25: percentile on need minus percentile on financing per person.

DROP TABLE IF EXISTS mart_priority;

CREATE TABLE mart_priority AS
WITH scored AS (
    SELECT
        name, iso3, region, income_level,
        sdg_gap_index, need_tercile, portfolio_tercile, allocation_gap,
        financing_pc, population, population_year,
        n_ops, active_commitment, total_commitment,
        median_impl_years, quadrant
    FROM mart_country
    WHERE need_complete = 1
)
SELECT
    name, iso3, region, income_level,
    sdg_gap_index, need_tercile, portfolio_tercile, quadrant,
    financing_pc, population, population_year,
    n_ops, active_commitment, total_commitment, median_impl_years,
    allocation_gap,
    ROW_NUMBER() OVER (ORDER BY allocation_gap DESC) AS priority_rank
FROM scored
ORDER BY allocation_gap DESC
LIMIT 25;
