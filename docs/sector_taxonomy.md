# Sector taxonomy

The register's sector field is an operational classification: 157 distinct labels across
18,917 operations, with no hierarchy and no stable identifier. Reporting on it directly
produces a table with 157 rows, of which the largest single entry is a null.

This document defines the 12-group mapping used by `mart_sector`, and the audit trail that
makes it reviewable.

## Coverage

| | Share of committed value |
|---|---|
| Classified into one of the 12 groups | 79.3% |
| Null in the source (`Unclassified`) | 19.9% |
| Label present but matched no rule (`Other`) | 0.7% |

Sector shares in the site and in `mart_sector` are computed on **classified value**, not on the
full book. Two alternatives were rejected:

- *Divide by the full book.* Every bar shrinks by a fifth and the bars no longer sum to 100%,
  so a reader comparing two sectors silently compares two diluted numbers.
- *Pool the nulls into "Other".* That column becomes the largest category and the real
  question — which sectors the portfolio actually holds — disappears behind a residual.

The `Other` residual is kept in staging, excluded from `mart_sector`, and reported here. It is
small enough (0.7%) that no rule is worth adding for it.

## The rule table

Matching is case-insensitive substring matching against the raw label, evaluated in the
order below. Order matters: `water` before `sanitation` would file water supply under the
wrong group, and `social protection` must precede `protection`-style matches.

| Group | Keywords |
|---|---|
| Health | health, nutrition, disease, hiv, malaria |
| Education | education, school, tertiary, literacy, training |
| Water & sanitation | water, sanitation, sewerage, flood |
| Energy & extractives | energy, power, electricity, oil, gas, mining, renewable, thermal, hydro, transmission, distribution |
| Transport | transport, road, rail, port, aviation, airport, highway, shipping |
| Agriculture & food | agric, irrigation, fishing, fisheries, forestry, livestock, food, crops, fertilizer |
| Social protection & labour | social protection, social safety, pension, labor, labour, welfare |
| Public administration | public administration, government, judicial, law, tax, public financial, civil service, procurement, statistics, economic management, public sector |
| Finance & private sector | finance, banking, insurance, capital market, payment, competitiveness, industry, trade, services, tourism, msme, non-bank financial, industrial adjustment |
| Digital & ICT | information, communication, ict, telecom, digital, broadband |
| Urban & housing | urban, housing, cadastre, land administration, municipal |
| Environment & climate | environment, climate, biodiversity, pollution, carbon, waste management, wastewater |

## Legacy labels

Labels created before 2012 carry a `(Historic)` prefix — `(Historic)Thermal`,
`(Historic)Economic management`, `(Historic)Industrial adjustment`. The prefix records the
vintage of the code list, not the sector, so it is stripped before matching and the remainder
runs through the same table. Without this step those labels fall to `Other`, which is how an
older version of this repository ended up with a 26% residual and a map that read as
unclassified brown.

## Why a rule table and not a lookup

A hand-written mapping of 157 labels is more precise and rots faster: the register adds labels,
and a lookup silently sends anything new to the residual. A rule table fails loudly and visibly
— a new label lands in `Other`, which is reported — and it can be reviewed in one screen.

The original label is never discarded. `stg_ops.sector` keeps it, so every group can be
recomputed from a different table without re-ingesting, and any group membership can be
traced back to the exact labels that produced it.

## Audit query

```sql
SELECT sector, sector_group, COUNT(*) AS n_ops, SUM(total_amt) AS value
FROM stg_ops
GROUP BY sector, sector_group
ORDER BY value DESC;
```

This is the only query needed to argue with the mapping: it shows which raw label sits in
which group and how much value each carries.
