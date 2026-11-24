# 0007 — Reject non-finite SDG values at ingest, not at the clamp

**Status:** accepted

## Context

The UN SDG API returns a bare `NaN` — the three letters, not a missing field — for a cell it
does not have. Two shapes matter here: the 2025 row of `SN_ITK_DEFC`, which is a placeholder
for all 169 countries that report the series, and a scatter of single-country `NaN`s in earlier
years and in `EG_ACS_ELEC`. 231 rows in the committed snapshot. `float("nan")` does not raise:
it parses cleanly and is written to the snapshot, to staging, and finally to the warehouse as
SQLite's text `'nan'` rather than a number.

The clamp in `12_int_country_need.sql` then read that cell as a value:

```sql
MIN(100, MAX(0, gap))      -- 'nan' sorts high, so this returns 100.0
```

Every country with a 2025 hunger row got a full 100-point hunger gap — 169 of them — which
raised the need index by 25 points and inflated the allocation gap of nearly every country
in the ranking. Nothing failed: every check passed, the page rendered, the tests were green,
because the defect was upstream of everything that was being asserted.

## Decision

Treat non-finite values as missing at the boundary, in both directions:

- `pipeline/ingest.py` skips a record whose value is not finite, before it reaches the snapshot.
- `pipeline/build.py` applies the same guard when reading the snapshot, and counts what it
  dropped (`sdg_nonfinite`) into the staging summary line.
- `dq_14` asserts that every value in `stg_sdg` is numeric and inside 0–100, so a future
  placeholder row fails the gate instead of moving a chart.

## Consequences

- The ranking population falls from 171 to 167 countries; the maximum need index from ~90 to
  77.1, and the largest hunger gap from 100 to 56.5. These are corrections, not regressions —
  the earlier figures were artefacts of a text cell being read as a number.
- The guard is at the boundary rather than at the clamp, because clamping is a policy
  (`MIN(100, ...)`) and silently absorbing a type error inside a policy is how the defect
  survived thirteen checks.
- `dq_14` is the cheapest possible test of the class of defect: it does not know which indicator
  or which year, only that a value has to be a number in range.

## Alternatives rejected

- **Filter the placeholder year (2025) by name.** The API's placeholder behaviour is not
  documented, and the year moves.
- **Treat `NaN` as zero.** It would have produced a plausible-looking page: a country with no
  hunger data would score as having no hunger gap, which is the exact error the three-of-four
  coverage rule exists to prevent.
