# Methodology

Every decision that changes a number is stated here, so a reader can disagree with the
reasoning instead of guessing at it.

## 1. What question the model answers

Portfolio allocation is usually discussed with one of two datasets: money committed, or need
measured. Institutions hold both and rarely place them on the same axis. The model puts a
country's **portfolio position** and its **measured service gap** in one frame and asks which
countries sit where need exceeds delivery.

This is an organisational-effectiveness question, not an attribution exercise. The output is a
review population, not a recommendation to reallocate.

## 2. Unit of analysis

| Layer | Grain | Source |
|---|---|---|
| Delivery | operation × country | World Bank project register |
| Need | country × indicator (latest year) | UN SDG indicator API |
| Population | country × year (latest non-empty) | World Bank `SP.POP.TOTL` |
| Geometry | country polygon | Natural Earth 1:110m |
| Identity | one row per country, ISO-3 keyed | UN M49 / ISO reference table |

### Multi-country operations

An operation can list several recipient countries. Splitting the commitment evenly across them
keeps `sum(country commitments) == sum(operation commitments)`, which
`tests/test_pipeline.py` asserts. The cost is that a regional programme's per-country amount is
an approximation; `stg_ops.multi_country` marks those rows so they can be excluded in a
sensitivity check.

Rejected alternative: counting the full amount in every country. It inflates small countries'
portfolios and breaks reconciliation.

### Territories without a country row

Some locations appear in the portfolio but not in the sovereign country register. Their links
cannot be attributed to a country row, so they are dropped before the split is written and
recorded in `data/staging/exclusions.json` (currently one territory, 0.02% of committed value).
Silent loss is the failure mode this avoids.

### Status

`projectstatusdisplay` is used where present, falling back to `status`. "Active" is matched on
prefix because the register uses both `Active` and longer labels. Active is the analytic
population for financing, because allocation is a question about live money, not the history of
a lending book.

## 3. Country identity

The three sources key differently: the register uses ISO-2, the SDG API uses UN M49, geometry
uses ISO-3. A single reference table is the only place country identity is defined; no name
matching is used anywhere.

Two classes of code are resolved explicitly rather than filtered by guesswork:

- **Legacy register codes** (`ZR`→COD, `RY`→YEM, `GZ`→PSE, `XK`→XKX, `TP`→TLS, `YF`→SRB).
  Unresolved, these drop 4,487 operations — including every operation in the Democratic
  Republic of Congo, Yemen and Gaza.
- **Numeric pseudo-codes** (`3A`, `1W`, `7E`, …) are regional and global aggregates. They are
  removed by an anchored pattern, not by a list, because the register keeps adding them.

`YU` (Yugoslavia) has no unambiguous successor and is dropped rather than assigned.

## 4. The need index

Four series were chosen because each carries a **2030 target of 0% or 100%**, so no threshold
has to be invented:

| SDG | Series | Target | Gap |
|---|---|---|---|
| 1.1.1 | `SI_POV_DAY1` population below the international poverty line | 0% | value |
| 2.1.1 | `SN_ITK_DEFC` prevalence of undernourishment | 0% | value |
| 6.1.1 | `SH_H2O_SAFE` safely managed drinking water | 100% | 100 − value |
| 7.1.1 | `EG_ACS_ELEC` access to electricity | 100% | 100 − value |

The index is the **unweighted mean of available gaps**, in percentage points of population. It
is an ordinal severity measure, not a service-quality measure: it does not say whether a
country's water is safely managed *well*, only what share of the population is reached at all.

### Filters applied at ingest

- `dimensions.Location` must be the national total (`ALLAREA` or absent). Urban, rural and
  sex-disaggregated rows are dropped so no population is counted twice.
- `geoAreaCode` must appear in the M49 whitelist from the reference table. This removes regional
  and global aggregates, which otherwise appear as countries.
- Observations before 2005 are dropped; the latest year per country is used.

### Coverage rule

A country enters the ranking only with **three or more of the four** indicators. Countries with
one or two are reported with `need_complete = 0` and no rank. They are visible on the map as
grey rather than classified as low-need, which would bias the result toward exactly the data-poor
states that matter.

## 5. Financing per person, and why not absolute value

Financing is `active_commitment / population`, with population taken as the latest non-empty
`SP.POP.TOTL` observation. The reason is visible in the data: absolute commitment ranks by the
size of the economy, so the largest borrowers occupy the top tercile almost mechanically and a
review of "thin portfolios" collapses to a handful of tiny states.

Per-capita financing spans five orders of magnitude — from zero active operations to five
figures per inhabitant — so the rank is taken on `ln(1 + financing_pc)`. A country with no active
operation ranks at the bottom; there is no imputation and no smoothing.

## 6. Percentile ranks rather than terciles

Terciles were the first design and are still used for the 3×3 map, but they carry a defect that
matters for this data: dozens of countries tie at exactly zero financing. `NTILE` splits a tie
group across bins, so part of that block was labelled "middle" — an unfunded country described
as averagely financed. `PERCENT_RANK` keeps ties together, and zero falls entirely into the
bottom third.

The published ranking therefore uses continuous percentile ranks:

```
allocation_gap = need_percentile − financing_percentile
```

in the range (−1, 1). Positive means the country carries more need than financing. Ranks are
size-neutral, so a small state and a large borrower are compared on position. The cut points
0.3333 and 0.6667 reproduce the terciles exactly and are exported by construction, so the site
and any reader use the same boundaries.

`mart_priority` ranks by `allocation_gap` alone, not by a hard quadrant. A 3×3 cell is easier to
defend in a slide and discards the countries just outside it: the Democratic Republic of Congo
and Chad both fall into "aligned" by tercile pair while ranking 6th and 15th on the gap.

### Six readings, not one weighting

The index is an unweighted mean, which is a design decision rather than a measurement.
`mart_robustness` therefore reruns the whole ranking under six readings — dropping each of the
four gaps in turn, plus a variant that scores a country on its single worst gap — and publishes
all six. Each country keeps its rank under every reading, so a reviewer can see whether a
country is on the short list because of its condition or because of the weight given to one
indicator.

Two properties make this a reading rather than a second model. Every variant scores all 167
countries, and the `equal` variant reproduces `mart_country.allocation_gap` to four decimal
places (asserted in `tests/`), so a disagreement between the matrix and the table above it is a
test failure rather than a footnote. Ranks are row numbers with a declared tiebreak (financing,
then need, then ISO-3) rather than `RANK()`, because a tie at the 25th place would otherwise
seat 26 countries and make "25 of 25" false.

The matrix is informative in both directions: 14 of the 25 hold their place under every reading,
and the entries that do move name the indicator doing the work — Russia falls 85 places when the
water gap is removed, Niger leaves the list once water or energy is dropped.

## 7. Sector taxonomy

The register's sector field is an operational classification with 158 distinct values, of which
about a fifth of committed value is null. It is collapsed into 12 comparable groups by a keyword
rule table, and the original label is retained alongside so the mapping can be audited. See
`sector_taxonomy.md`.

Sector shares are computed on **classified value only**. Dividing by the full book would
understate every bar by the unclassified fifth; pooling it into an "other" column would make that
column the largest single category and hide the problem.

## 8. Duration

`impl_years = (closing − approval) / 365.25`, planned duration, not actual. It is `NULL` where
either date is missing or unparseable. Country medians use the two-row average of the ranked
series, which is exact for odd and even counts.

This is a **planned** duration. A register that extends a closing date rewrites history; the
metric therefore measures stated ambition and slippage-adjusted scheduling, not realised
delivery time.

## 9. Known limitations

1. **Commitment ≠ disbursement.** Approved financing is not money that reached a country.
   Disbursement ratio is the obvious next field.
2. **Population is a denominator, not a need measure.** A large country with a modest
   per-capita figure can still carry a large absolute gap.
3. **Polygon coverage.** Natural Earth at 1:110m draws 177 polygons. Small island states are in
   the data but not on the map; the tables and marts are complete.
4. **Comparability across register and indicators.** Portfolio data is administrative and
   continuously revised; SDG series are statistical and lag by years. The two layers are joined
   by country and read as a snapshot, not a time series.
5. **Drift is a two-point reading.** `mart_convergence` compares 2015 with each country's
   latest reporting year, which ranges from 2021 to 2024. It measures whether the index moved,
   not when; the half-life figure quoted on the page assumes that the average change over those
   nine years repeats at a constant rate, which is a projection, not an observation.
6. **Proxy portfolio.** The register used here is one large sovereign portfolio, not the
   portfolio of any single agency. It answers the question at the level of the development
   finance system; an institutional portfolio would need its own adapter, which the ingest layer
   is structured to take.
7. **Not an evaluative claim.** The gap is a triage device. Treating it as evidence of
   misallocation would be a category error.

### From stock to flow

The ranking is a stock comparison: everything ever committed, against need as measured today.
Two additional tables turn it into something a reviewer can act on.

`mart_convergence` isolates the **flow** — commitments approved from 2015 onward, per country
and per person — and sets the change in need beside it. The correlation is +0.15 across the 82
countries that received anything, which is the finding the table exists to expose rather than
to bury: money and measured progress are close to independent at this level of aggregation.

The two tables are deliberately not merged. The stock ranking answers *where the gap is
largest*; the flow layer answers *whether the gap is closing, and what has been spent trying*.
A country can score badly on both and appear in each table for a different reason, which is
the distinction between a portfolio review and an evaluation.

## 10. Reproducibility

`data/raw/` holds checksummed snapshots with a retrieval timestamp; `data/raw/manifest.json`
records the SHA-256 of every file. Downstream stages never touch the network, so the published
figures are reproducible from the committed snapshot alone:

```bash
python pipeline/build.py && python pipeline/site.py && python -m unittest discover -s tests
```
