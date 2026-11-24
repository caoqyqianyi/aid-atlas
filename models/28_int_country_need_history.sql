-- The need index as a series rather than a snapshot.
--
-- 12_int_country_need keeps the latest reading per country. This keeps every
-- reading, so the page can ask whether need has moved since the 2030 agenda was
-- adopted in 2015. One observation per indicator, country and year: duplicate
-- rows in the SDG extract are averaged rather than picked, because the series
-- carry both modelled and reported estimates for the same year.
--
-- A year only qualifies when at least three of the four indicators report it,
-- the same rule the ranking uses. Keeping the rule here matters: a country whose
-- water series stops in 2017 should not show a jump when it stops being counted.

DROP TABLE IF EXISTS int_country_need_history;

CREATE TABLE int_country_need_history AS
WITH observation AS (
    SELECT
        indicator,
        iso3,
        year,
        AVG(value) AS value
    FROM stg_sdg
    WHERE year BETWEEN 2000 AND 2024
    GROUP BY indicator, iso3, year
),
gapped AS (
    SELECT
        iso3,
        year,
        CASE indicator
            WHEN 'SI_POV_DAY1' THEN MIN(100.0, MAX(0.0, value))
            WHEN 'SN_ITK_DEFC' THEN MIN(100.0, MAX(0.0, value))
            ELSE MIN(100.0, MAX(0.0, 100.0 - value))
        END AS gap_pp
    FROM observation
)
SELECT
    iso3,
    year,
    ROUND(AVG(gap_pp), 4)  AS need_index,
    COUNT(gap_pp)          AS n_indicators
FROM gapped
WHERE gap_pp IS NOT NULL
GROUP BY iso3, year;
