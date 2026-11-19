# SOP — use the output in a portfolio review

The site produces a review population, not a decision. This is how it is meant to be read.

## 1. Start from the short list, not the map

`mart_priority` ranks by allocation gap. The map is for orientation; ranks are for work.

```bash
head -26 data/marts/mart_priority.csv
```

## 2. Triage each entry into one of three shapes

| Shape | Signal | Next question |
|---|---|---|
| High need, no active operation | `financing_pc = 0`, `n_ops` small but non-zero | Is the country absent by policy, by capacity, or by data lag? |
| High need, active but thin per person | high `n_ops`, low `financing_pc` | Is the portfolio small projects, or large ones closing? |
| High need, thin, large absolute book | high `n_ops`, high `total_commitment` | Is delivery the constraint rather than allocation? |

The third shape is the one a quadrant view hides: DRC and Chad both sit in "aligned" by
tercile and near the top by gap.

## 3. Check the evidence behind each row

- `n_indicators` — fewer than four means the index rests on partial coverage.
- `population_year` — a stale denominator distorts `financing_pc`.
- `median_impl_years` — a long planned duration means committed money is slow, not absent.

## 4. Write the finding in one sentence per country

Format: *"X ranks Nth on allocation gap: need index 87.7, US$61 per person, 180 operations,
median duration 6.2 years."* Numbers first, interpretation second. A finding that cannot be
written in this form is not yet a finding.

## 5. State what the review cannot conclude

Commitment is not disbursement; a gap is not a misallocation; ranks are relative. Any
recommendation that ignores these three is outside what this analysis supports.
