-- One reallocation scenario, computed at 5% of active value.
--
-- The point is not that money should move; it is that the arithmetic behind a
-- "what if" is explicit enough to argue with. Two choices carry the whole
-- result and both are stated in docs/reallocation-case.md:
--
--   * the pool is raised pro rata from countries already better financed than
--     their measured need (allocation_gap < 0), so no single portfolio is
--     singled out;
--   * it is paid out pro rata to population across the 25 short-listed
--     countries, which makes the gain per person identical in each of them.
--
-- The page recomputes the same formula for any share on the slider; this
-- table is the canonical 5% row the memo and the README quote, and the test
-- suite checks that the two agree.

DROP TABLE IF EXISTS mart_reallocation;

CREATE TABLE mart_reallocation AS
WITH params AS (
    SELECT 0.05 AS share
),
active AS (
    SELECT SUM(active_commitment) AS active_value FROM mart_country
),
donors AS (
    SELECT iso3, active_commitment, population
    FROM mart_country
    WHERE active_commitment > 0
      AND allocation_gap < 0
),
recipients AS (
    SELECT iso3, population FROM mart_priority
)
SELECT
    params.share                                              AS share,
    params.share * active.active_value                         AS pool_usd,
    (SELECT COUNT(*) FROM donors)                              AS n_donors,
    (SELECT SUM(active_commitment) FROM donors)                AS donor_value,
    (SELECT COUNT(*) FROM recipients)                          AS n_recipients,
    (SELECT SUM(COALESCE(population, 0)) FROM recipients)      AS recipient_population,
    params.share * active.active_value
        / NULLIF((SELECT SUM(COALESCE(population, 0)) FROM recipients), 0)
                                                               AS gain_per_person,
    (SELECT SUM(COALESCE(population, 0)) FROM donors)          AS donor_population,
    params.share * active.active_value
        / NULLIF((SELECT SUM(COALESCE(population, 0)) FROM donors), 0)
                                                               AS donor_loss_per_person
FROM params, active;
