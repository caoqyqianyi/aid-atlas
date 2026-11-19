# Data dictionary

Column-level contract for every table the pipeline writes. Types are those of the CSV
export; in SQLite the same columns are `TEXT`, `REAL` or `INTEGER`. Empty cells are `NULL`,
never zero-filled — the distinction matters for `active_commitment` and for any country
outside the analytic population.

## Snapshots (`data/raw/`)

| File | Structure | Notes |
|---|---|---|
| `worldbank_projects.json.gz` | `{total, rows, projects: {id: {...}}}` | 18 declared fields per operation; the API returns more, and undeclared fields are dropped before writing (snapshot is 1.2 MB instead of 28 MB) |
| `worldbank_countries.json.gz` | `{rows: [...]}` | region, income level, ISO-3 |
| `worldbank_population.json.gz` | `{rows: [{iso3, year, population}]}` | `SP.POP.TOTL`, latest non-empty year |
| `un_sdg_series.json.gz` | `{indicators: {code: {...}}, series: {code: [{m49, year, value}]}}` | national totals only |
| `country_codes.json` / `.csv` | `{rows: [{iso3, iso2, m49, name}]}` | the single join key for country identity |
| `ne_110m_admin_0_countries.json.gz` | `{features, geojson}` | geometry, embedded into the site payload |
| `manifest.json` | list of `{file, bytes, sha256, retrieved_at, built}` | written after every ingest |

## Staging (`data/staging/`)

### `ops.csv` — one row per operation

| Column | Type | Definition |
|---|---|---|
| `project_id` | text | register identifier |
| `project_name` | text | as published |
| `status` | text | `projectstatusdisplay`, falling back to `status` |
| `approval_date` | date | board approval |
| `closing_date` | date | planned closing |
| `impl_years` | real | `(closing − approval)/365.25`, `NULL` if either date is missing |
| `total_amt` | real | total project cost, `"200,000,000"` → `200000000.0` |
| `commit_amt` | real | lending commitment |
| `grant_amt` | real | grant component |
| `region` | text | borrower region, trimmed |
| `sector` | text | raw operational label, `Unclassified` where empty |
| `sector_group` | text | one of the 12 taxonomy groups, or `Other` / `Unclassified` |
| `implementing_agency` | text | as published |
| `product_line` | text | lending instrument |
| `fiscal_year` | int | register fiscal year |
| `multi_country` | 0/1 | operation covers more than one recipient |

### `op_country.csv` — one row per operation–country link

| Column | Type | Definition |
|---|---|---|
| `project_id` | text | foreign key to `ops.csv` |
| `iso3` | text | resolved recipient |
| `amount_share` | real | `total_amt / n_countries`; sums exactly to the operation total |

### `sdg_observations.csv` — one row per country–indicator–year

| Column | Type | Definition |
|---|---|---|
| `indicator` | text | SDG series code |
| `iso3` | text | resolved from M49 through the reference table |
| `year` | int | observation year, 2005 onwards |
| `value` | real | percentage of population |

### `population.csv`

| Column | Type | Definition |
|---|---|---|
| `iso3` | text | country |
| `year` | int | year of the observation used |
| `population` | real | total population |

### `exclusions.json`

Territories present in the portfolio but absent from the country register, with the value
dropped. Written so that an exclusion can be audited rather than inferred.

## Marts (`data/marts/`)

### `mart_country.csv` — one row per country (217)

| Column | Type | Definition |
|---|---|---|
| `iso3`, `iso2`, `name` | text | identity, from the reference table |
| `region`, `income_level` | text | World Bank classification |
| `population`, `population_year` | real/int | latest non-empty total population |
| `financing_pc` | real | `active_commitment / population`; `NULL` without population |
| `n_ops` | int | operations with this country as a recipient |
| `total_commitment` | real | lifetime commitment, split across recipients |
| `active_commitment` | real | commitment on operations whose status starts `Active`; 0 where none |
| `n_active` | int | count of active operations |
| `mean_impl_years` | real | mean planned duration, operations in this country |
| `median_impl_years` | real | median planned duration |
| `sdg_gap_index` | real | 0–100, mean of available SDG gaps |
| `gap_poverty`, `gap_hunger`, `gap_water`, `gap_energy` | real | component gaps, percentage points |
| `n_indicators` | int | 0–4, how many components are present |
| `latest_year` | int | most recent SDG observation used |
| `ln_commitment` | real | `ln(1+total_commitment)`, retained for continuity |
| `need_complete` | 0/1 | 1 when `n_indicators >= 3`, the condition to enter the ranking |
| `portfolio_tercile` | 1–3 | tercile of `ln(1+financing_pc)`, tie-aware cut at 0.3333/0.6667 |
| `need_tercile` | 1–3, null | tercile of `sdg_gap_index`, complete countries only |
| `quadrant` | text | `high need / thin portfolio`, `low need / heavy portfolio`, `aligned`, `insufficient need data` |
| `need_vs_portfolio_gap` | −2…2 | `need_tercile − portfolio_tercile`, the 3×3 map's index |
| `allocation_gap` | −1…1 | `need_percentile − financing_percentile`, the published ranking |

### `mart_priority.csv` — the short list (25)

`name`, `iso3`, `region`, `income_level`, `sdg_gap_index`, `need_tercile`,
`portfolio_tercile`, `quadrant`, `financing_pc`, `population`, `population_year`, `n_ops`,
`active_commitment`, `total_commitment`, `median_impl_years`, `allocation_gap`,
`priority_rank` (1 = largest positive gap). Restricted to `need_complete = 1`.

### `mart_sector.csv` — sector mix (12)

| Column | Type | Definition |
|---|---|---|
| `sector` | text | taxonomy group |
| `n_ops` | int | operations in the group |
| `total_value` | real | lifetime commitment |
| `mean_value` | real | mean operation size |
| `value_share` | real | share of **classified** value, sums to 1 |
| `hhi_contrib` | real | `value_share²`, summed to the portfolio's Herfindahl index |
| `value_rank` | int | 1 = largest |

### `mart_region.csv` — regional balance (7)

`region`, `n_countries`, `n_ops`, `total_commitment`, `value_share`, `mean_need_gap`
(mean `sdg_gap_index` of countries with need data), `n_blindspots` (countries in the
high-need / thin-financing quadrant).

### `mart_portfolio_health.csv` — key/value

| Metric | Unit | Definition |
|---|---|---|
| `total_operations` | count | operations in the register |
| `total_value_usd` | USD | lifetime commitment |
| `active_value_usd` | USD | commitment on active operations |
| `share_operations_active` | ratio | active share by count |
| `share_value_active` | ratio | active share by value |
| `mean_implementation_years` | years | mean planned duration |
| `share_operations_over_10y` | ratio | operations planned beyond ten years |
| `countries_with_portfolio` | count | countries with at least one operation |
| `countries_with_need_data` | count | countries with `need_complete = 1` |
| `sector_hhi` | index | sum of squared classified sector shares |
| `share_value_top10_operations` | ratio | concentration in the ten largest operations |
