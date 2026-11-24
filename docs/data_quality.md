# Data quality gate

`pipeline/dq.py` runs a fixed list of checks over the warehouse and the derived tables, writes
`data/marts/mart_dq.csv`, and returns a non-zero exit code if any check fails. The render step
reads that file, so the site cannot quote a number that the gate has not seen; CI runs the gate
before the render, and a failure stops the build before the page is regenerated.

```
make build      # rebuild staging, warehouse and marts
python pipeline/dq.py
```

Output is one row per check:

| Column | Meaning |
|---|---|
| `check_id` | stable id, `dq_01` … — cited in commit messages and review notes |
| `category` | Integrity, Reconciliation, Coverage, Completeness, Bounds, Uniqueness, Scenario |
| `check` | the assertion in plain language; this is the name the site shows |
| `value` | the measured quantity, so a reviewer can see how much headroom is left |
| `threshold` | the pass condition as written |
| `status` | `PASS` or `FAIL` |
| `detail` | the same fact in words, with counts and the layers being compared |

## The checks

| ID | Category | Assertion | Threshold | Why this threshold |
|---|---|---|---|---|
| dq_01 | Integrity | One row per project in staging | duplicates = 0 | A duplicate key silently doubles a commitment and every downstream total; zero is the only defensible value |
| dq_02 | Integrity | Every country link resolves to a known ISO-3 | orphans = 0 | An unknown key would drop out of the country layer without a trace, shrinking the book |
| dq_03 | Reconciliation | Split amounts equal the register total | < $0.01 | Exact arithmetic on purpose: splitting a commitment across recipients must be lossless |
| dq_04 | Reconciliation | Country layer equals the portfolio total | < 0.5% | A tolerance, not zero, because the two layers round independently; one part in 200 is far below any figure quoted on the page |
| dq_05 | Reconciliation | Active value agrees between country layer and health | < 0.5% | Same reasoning as dq_04; this is the number the scenario and the per-capita ranking both start from |
| dq_06 | Coverage | Register records retained in staging | ≥ 75% | 18,917 of 22,671 records (83.4%). The remainder carry no resolvable country code, are regional entries or repeat across pages; a drop below 75% would mean the parser, not the register, changed |
| dq_07 | Completeness | Operations with an approval date | ≥ 75% | 3,752 operations carry no date (80.2% dated). Cohorts and duration bands depend on this field, so a collapse would quietly move value into "No approval date" |
| dq_08 | Completeness | Value with a sector classification | ≥ 75% | 19.9% of value is unclassified. The sector view excludes it from the denominator rather than pooling it into an "other" bar; above a quarter unclassified the view stops describing the book |
| dq_09 | Coverage | Countries carrying a need index | ≥ 150 countries | 167 of 217. The ranking excludes countries with fewer than three of the four series, which is deliberate; the floor guards against the indicator API returning less than the agreed four |
| dq_10 | Bounds | Allocation gap inside [-1, 1] | ≤ 1.0 | The gap is a difference of two percentile ranks, so it is bounded by construction; a breach would mean the rank scale was rebuilt |
| dq_11 | Uniqueness | Short-list ranks are 1…25 without gaps | 25 distinct | The site prints "the 25 on the short list"; a gap or duplicate would make that sentence false |
| dq_12 | Scenario | Pool equals the stated share of live value | < 1% | The page lets a reader move the share; the mart row and the recomputed pool must agree so the slider and the static text cannot drift apart |
| dq_13 | Reconciliation | Operating buckets sum to the portfolio total | < $0.01 | Status, duration and cohort are meant to partition the book; this is the check that keeps them exhaustive |
| dq_14 | Bounds | SDG observations are numeric and inside 0–100 | bad rows = 0 | The indicator API returns `NaN` for the current-year placeholder row, and `float('NaN')` does not raise, so a text `nan` reached the staging table. The clamp turned it into 100 and pushed 169 countries to a full hunger gap; this check is the one that would have caught it in CI rather than in a chart |

## What happens on a failure

The exit code is 1 and the step prints the failing rows with their measured value. The gate is
placed before `pipeline/site.py` in `make all` and in `.github/workflows/ci.yml`, so a failing
snapshot never reaches the page. Workflow:

1. read the `detail` column — it names the two layers being compared;
2. decide which layer moved: re-run `pipeline/build.py` alone and compare the staging counts;
3. if the change is real and intended (a new snapshot, a widened source), update the threshold
   in the same commit and say why, rather than loosening it silently later.

## What this gate does not do

- It does not detect schema drift in the source. A field that stops arriving shows up as a
  completeness check falling, not as an error.
- It does not test code paths. Parsers, date handling and the country split have unit tests;
  the gate only asserts properties of the data that came out.
- It does not judge the analysis. A passing gate means the numbers are internally consistent,
  not that the interpretation in `methodology.md` is right.
- Thresholds are floors and tolerances chosen for this snapshot. They are documented here so a
  reviewer can disagree with the choice rather than guess at it.
