# portfolio-lens

**Where development finance is delivered, and where it is needed.**

[![Python](https://img.shields.io/badge/python-3.11%2B-2f5d7c?style=flat-square)](https://www.python.org/)
[![SQL](https://img.shields.io/badge/marts-SQLite-2f5d7c?style=flat-square)](https://sqlite.org/)
[![Dependencies](https://img.shields.io/badge/runtime%20deps-none-e9e3d1?style=flat-square)](#running-it)
[![Tests](https://img.shields.io/badge/tests-19%20passing-6b8f71?style=flat-square)](#running-it)
[![CI](https://github.com/caoqyqianyi/portfolio-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/caoqyqianyi/portfolio-lens/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/badge/licence-MIT-6b6f66?style=flat-square)](LICENSE)

A reproducible pipeline that places a sovereign development portfolio on the same axis as
measured service need, and ranks the countries where the two diverge. It is built as a
management instrument — a defensible review population for portfolio performance work —
rather than as a map, and the geospatial layer is a reading aid, not the answer.

**Live dashboard:** [caoqyqianyi.github.io/portfolio-lens](https://caoqyqianyi.github.io/portfolio-lens/)

![dashboard](docs/img/dashboard.png)

<p align="center"><em>Single-file interactive output. <code>site/index.html</code>, no server, no build step.</em></p>

---

## Contents

- [What it answers](#what-it-answers)
- [Key findings](#key-findings)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Running it](#running-it)
- [Method, in one page](#method-in-one-page)
- [What this cannot tell you](#what-this-cannot-tell-you)
- [Data provenance](#data-provenance)
- [Licence](#licence)

---

## What it answers

Portfolio reviews usually begin with the money or with the need. Institutions hold both
datasets and rarely put them on one axis, which is why "under-served country" conversations
tend to stall on whose indicator is authoritative.

This repository asks one question — *which country portfolios carry more measured need than
financing?* — and answers it with:

| Output | Definition |
|---|---|
| `allocation_gap` | percentile rank of a country on need minus its percentile rank on financing per person |
| `mart_priority` | the 25 countries with the largest positive gap, with the columns that explain each entry |
| `mart_country` | the full analytic table, one row per country, both layers plus terciles |
| `site/index.html` | the same result as a self-contained interactive page |

Both ranks are size-neutral, so a small island state and a large borrower are compared on
position, not on the size of their economy. That choice is what makes the ranking usable in a
review: it produces a short list that a team of five could actually work through.

## Key findings

Portfolio: **18,917 operations, US$1.59tn committed, US$331.9bn active** across 217 countries.
20.8% of committed value is still live; the median operation runs 5.9 years.

- **110 of 171 countries with measured need carry a positive allocation gap** — more need
  than financing, once both are expressed as ranks.
- **The strongest case is a country that a quadrant view rejects.** The Democratic Republic of
  Congo ranks 8th on the gap (need 87.7 of 100, US$61 per person, gap +0.52) yet holds 180
  operations. It sits in the "aligned" cell of a hard 3×3 because its portfolio tercile is not
  the bottom one. Chad is the same shape at a smaller scale: need 81.0, US$76 per person,
  100 operations, gap +0.46. Both are portfolio-review candidates, not funding gaps.
- **The top of the list is not the same population as the biggest borrowers.** Zimbabwe
  (gap +0.92) and DPR Korea (+0.84) lead on need with no active operations at all, while
  large portfolios such as India and Brazil sit near the middle. Absolute commitment and
  per-capita financing rank countries differently, and only the second answers the question.
- **Sector concentration is moderate**: Herfindahl index 0.120 on classified value, led by
  public administration (17.9%), transport (14.3%), energy and extractives (14.0%) and
  finance and the private sector (12.7%). Health is 5.6%, water and sanitation 8.1%,
  environment and climate 0.5%.
- **The book is slow-moving**: only 13.1% of operations are active, and 4.6% have a planned
  duration over ten years.

## How it works

```
ingest  →  staging  →  SQLite warehouse  →  SQL marts  →  single-file site
```

1. **Ingest** writes checksummed snapshots to `data/raw/` and records a manifest, so every
   downstream number can be reproduced without touching the network again.
2. **Staging** flattens the project register: one row per operation, one row per
   operation–country link, with commitments split evenly across recipients.
3. **Marts** are plain SQL files run in filename order. Intermediates are `int_*`, published
   tables are `mart_*`. Nothing in a mart reads a CSV directly.
4. **Site** embeds the marts and the country geometry into one HTML file. Only D3 is fetched
   from a CDN; there is no runtime API call.

The pipeline is standard library only. No pandas, no ORM, no third-party runtime dependency —
a reviewer can read every line that produces a number.

## Repository layout

```
pipeline/
  ingest.py          snapshot fetchers, retry policy, manifest
  build.py           staging, warehouse load, SQL runner, mart export
  site.py            payload assembly and HTML render
models/
  10_int_country_portfolio.sql
  11_int_country_duration.sql
  12_int_country_need.sql
  20_mart_country.sql
  21_mart_sector.sql
  22_mart_region.sql
  23_mart_portfolio_health.sql
  25_mart_country_gap.sql      percentile ranks, allocation gap
  26_mart_priority.sql         the short list
docs/
  methodology.md      every decision that changes a number
  data_dictionary.md  column-level contract for each table
  sector_taxonomy.md  the 12-group mapping and why it is a rule table
  decisions/          ADRs for the choices that had alternatives
sops/
  refresh-data.md     quarterly refresh, step by step
  add-an-indicator.md extending the need index
  review-a-portfolio.md  how the output is used in a review
tests/test_pipeline.py   reconciliation, bounds and ranking invariants
site/index.html          rendered output
```

## Running it

```bash
python pipeline/ingest.py          # fetch snapshots (≈2 min, needs network)
python pipeline/build.py           # staging → warehouse → marts
python pipeline/site.py            # render site/index.html
python -m unittest discover -s tests
```

`ingest.py --sample` pulls a small slice for a fast end-to-end run; `--force` refetches
everything. The committed `data/` tree is the product of a full run, so `build.py` and
`site.py` alone reproduce the published figures offline.

## Method, in one page

**Delivery layer.** World Bank project register, parsed into country links. Commitments are
split evenly where an operation covers several countries; planned duration runs from board
approval to closing date. Active means the register's status field starts with `Active`.

**Need layer.** Four SDG series chosen because each carries a stated 2030 target of 0% or 100%,
so no threshold has to be invented: poverty (1.1.1), undernourishment (2.1.1), safely managed
drinking water (6.1.1), electricity access (7.1.1). Each becomes percentage points of population
not yet served; the index is their unweighted mean. A country enters the ranking only with
three of the four, so a data-poor state is never silently classified as low-need.

**Bridging.** The three sources key on ISO-2, ISO-3 and UN M49, so a single reference table is
the join key and the only place country identity is defined. Legacy register codes (`ZR`, `RY`,
`GZ`, `TP`) are mapped to their successors and resolved explicitly, including the 4,487
operations that would otherwise drop out.

**Ranking.** Percentile ranks rather than terciles: dozens of countries tie at zero financing,
and a binning method that splits tie groups would label an unfunded country "middle". The
detail, and the alternatives rejected, is in `docs/decisions/`.

## What this cannot tell you

1. **Commitment is not disbursement.** Value here is approved financing, not money that reached
   a country.
2. **It does not attribute outcomes.** A thin portfolio and a large gap can both be symptoms of
   state capacity, access constraints or a division of labour between financiers.
3. **Percentiles are relative, not sufficiency standards.** A country can rank badly while
   receiving more per person in absolute terms than its neighbours.
4. **Polygon coverage.** Natural Earth at 1:110m draws 177 polygons; small island states are in
   the tables and absent from the map.
5. **Two clocks.** Portfolio data is administrative and revised continuously; SDG series are
   statistical and lag by years. The join is a snapshot, not a time series.

## Data provenance

| Source | Used for | Licence |
|---|---|---|
| World Bank Projects API | portfolio, country metadata, population | CC BY 4.0 |
| UN SDG Indicators API | need index | CC BY 4.0 |
| UN M49 / `datasets/country-codes` | country identity table | Public domain |
| Natural Earth 1:110m | geometry | Public domain |

This is an independent analysis of public data. It is not affiliated with, endorsed by, or
produced for any institution named in the sources, and no institutional logo or name is used.
Taiwan is absent from the World Bank country register and its operations (US$0.34bn, 0.02% of
value) are excluded; the exclusion is written to `data/staging/exclusions.json` rather than
silently dropped.

## Licence

MIT. See `LICENSE`.
</content>
</invoke>
