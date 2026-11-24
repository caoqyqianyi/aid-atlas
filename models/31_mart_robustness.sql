-- Six ways to read the same four indicators, ranked side by side.
--
-- The baseline averages poverty, hunger, water and electricity with equal
-- weight. Any single weighting is a choice, so this re-runs the ranking under
-- five alternatives: drop each indicator in turn, and take the worst single
-- dimension instead of the mean. A country that holds its place under all six
-- is telling you something; one that enters under exactly one reading is
-- telling you something else.
--
-- The population is held fixed at the 171 countries with three or more
-- indicators, so a rank change here is a change in definition and nothing else.
-- Ranks are 1-based on the allocation gap, as the short list is.

DROP TABLE IF EXISTS mart_robustness;

CREATE TABLE mart_robustness AS
WITH component AS (
    SELECT
        n.iso3,
        n.gap_poverty,
        n.gap_hunger,
        n.gap_water,
        n.gap_energy,
        COALESCE(c.financing_pc, 0) AS financing_pc,
        (CASE WHEN n.gap_poverty IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN n.gap_hunger IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN n.gap_water IS NOT NULL THEN 1 ELSE 0 END)
        + (CASE WHEN n.gap_energy IS NOT NULL THEN 1 ELSE 0 END) AS n_ind
    FROM int_country_need n
    JOIN mart_country c USING (iso3)
    WHERE n.n_indicators >= 3
),
variant AS (
    SELECT
        iso3, financing_pc, 'equal' AS variant,
        (COALESCE(gap_poverty, 0) + COALESCE(gap_hunger, 0)
         + COALESCE(gap_water, 0) + COALESCE(gap_energy, 0)) * 1.0 / NULLIF(n_ind, 0) AS need
    FROM component

    UNION ALL
    SELECT
        iso3, financing_pc, 'no_poverty',
        (COALESCE(gap_hunger, 0) + COALESCE(gap_water, 0) + COALESCE(gap_energy, 0)) * 1.0
        / NULLIF(n_ind - (CASE WHEN gap_poverty IS NOT NULL THEN 1 ELSE 0 END), 0)
    FROM component

    UNION ALL
    SELECT
        iso3, financing_pc, 'no_hunger',
        (COALESCE(gap_poverty, 0) + COALESCE(gap_water, 0) + COALESCE(gap_energy, 0)) * 1.0
        / NULLIF(n_ind - (CASE WHEN gap_hunger IS NOT NULL THEN 1 ELSE 0 END), 0)
    FROM component

    UNION ALL
    SELECT
        iso3, financing_pc, 'no_water',
        (COALESCE(gap_poverty, 0) + COALESCE(gap_hunger, 0) + COALESCE(gap_energy, 0)) * 1.0
        / NULLIF(n_ind - (CASE WHEN gap_water IS NOT NULL THEN 1 ELSE 0 END), 0)
    FROM component

    UNION ALL
    SELECT
        iso3, financing_pc, 'no_energy',
        (COALESCE(gap_poverty, 0) + COALESCE(gap_hunger, 0) + COALESCE(gap_water, 0)) * 1.0
        / NULLIF(n_ind - (CASE WHEN gap_energy IS NOT NULL THEN 1 ELSE 0 END), 0)
    FROM component

    UNION ALL
    SELECT
        iso3, financing_pc, 'worst',
        NULLIF(MAX(COALESCE(gap_poverty, -1), COALESCE(gap_hunger, -1),
                   COALESCE(gap_water, -1), COALESCE(gap_energy, -1)), -1)
    FROM component
),
scored AS (
    SELECT
        variant,
        iso3,
        need,
        PERCENT_RANK() OVER (PARTITION BY variant ORDER BY need)       AS need_pct,
        PERCENT_RANK() OVER (PARTITION BY variant ORDER BY financing_pc) AS financing_pct
    FROM variant
    WHERE need IS NOT NULL
),
ranked AS (
    SELECT
        variant,
        iso3,
        need,
        ROUND(need_pct - financing_pct, 4) AS allocation_gap,
        -- Row numbers rather than RANK(): a tie at the 25th place would
        -- otherwise put 26 countries in the top 25 and make the matrix count
        -- disagree with the table.
        ROW_NUMBER() OVER (
            PARTITION BY variant
            ORDER BY need_pct - financing_pct DESC, need DESC, iso3
        ) AS rank
    FROM scored
)
SELECT
    r.variant,
    r.iso3,
    c.name,
    ROUND(r.need, 2)          AS need_index,
    r.allocation_gap,
    r.rank,
    CASE WHEN r.rank <= 25 THEN 1 ELSE 0 END AS in_top25,
    b.rank                    AS baseline_rank,
    ROUND(r.rank - b.rank, 0) AS rank_shift,
    -- The published short-list rank, so the matrix and the table above it
    -- cannot disagree about what number a country carries.
    p.priority_rank           AS shortlist_rank
FROM ranked r
JOIN mart_country c USING (iso3)
JOIN ranked b ON b.iso3 = r.iso3 AND b.variant = 'equal'
LEFT JOIN mart_priority p USING (iso3)
ORDER BY r.variant, r.rank;
