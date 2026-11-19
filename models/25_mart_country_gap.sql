-- Adds the allocation gap to the country mart.
--
-- gap = percentile rank on need  -  percentile rank on financing per person,
-- computed over countries that meet the three-of-four rule. Positive means the
-- country's need position is higher than its financing position. Two
-- statements because SQLite will not window over the table it is updating.

ALTER TABLE mart_country ADD COLUMN allocation_gap REAL;

WITH ranked AS (
    SELECT
        iso3,
        PERCENT_RANK() OVER (ORDER BY sdg_gap_index)                    AS need_pct,
        PERCENT_RANK() OVER (ORDER BY COALESCE(financing_pc, 0))        AS financing_pct
    FROM mart_country
    WHERE need_complete = 1
)
UPDATE mart_country
SET allocation_gap = (
    SELECT ROUND(r.need_pct - r.financing_pct, 4)
    FROM ranked r
    WHERE r.iso3 = mart_country.iso3
);
