-- Country-level "need" layer, built from the four UN SDG series.
--
-- Each indicator becomes a gap in percentage points of population not yet
-- served, against the target in the 2030 framework:
--   poverty, undernourishment -> target 0%,   gap = value
--   water, electricity        -> target 100%, gap = 100 - value
-- The index is the mean of the available gaps. Countries with fewer than
-- three of four observations are flagged rather than silently averaged.

DROP TABLE IF EXISTS int_country_need;

CREATE TABLE int_country_need AS
WITH latest AS (
    SELECT
        s.indicator,
        s.iso3,
        s.value,
        s.year,
        ROW_NUMBER() OVER (PARTITION BY s.indicator, s.iso3 ORDER BY s.year DESC) AS rn
    FROM stg_sdg s
),
wide AS (
    SELECT
        iso3,
        MAX(CASE WHEN indicator = 'SI_POV_DAY1' AND rn = 1 THEN value END) AS poverty_rate,
        MAX(CASE WHEN indicator = 'SN_ITK_DEFC' AND rn = 1 THEN value END) AS undernourishment,
        MAX(CASE WHEN indicator = 'SH_H2O_SAFE' AND rn = 1 THEN value END) AS water_access,
        MAX(CASE WHEN indicator = 'EG_ACS_ELEC' AND rn = 1 THEN value END) AS electricity_access,
        MAX(CASE WHEN rn = 1 THEN year END)                                AS latest_year,
        SUM(CASE WHEN rn = 1 THEN 1 ELSE 0 END)                            AS n_indicators
    FROM latest
    GROUP BY iso3
),
gapped AS (
    SELECT
        iso3, poverty_rate, undernourishment, water_access, electricity_access,
        latest_year, n_indicators,
        CASE WHEN poverty_rate       IS NULL THEN NULL ELSE MIN(100.0, MAX(0.0, poverty_rate))       END AS gap_poverty,
        CASE WHEN undernourishment   IS NULL THEN NULL ELSE MIN(100.0, MAX(0.0, undernourishment))   END AS gap_hunger,
        CASE WHEN water_access       IS NULL THEN NULL ELSE 100.0 - water_access                     END AS gap_water,
        CASE WHEN electricity_access IS NULL THEN NULL ELSE 100.0 - electricity_access               END AS gap_energy
    FROM wide
)
SELECT
    *,
    (COALESCE(gap_poverty, 0) + COALESCE(gap_hunger, 0)
     + COALESCE(gap_water, 0) + COALESCE(gap_energy, 0))
        / NULLIF(n_indicators, 0) AS sdg_gap_index
FROM gapped;
