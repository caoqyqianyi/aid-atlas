# 0002 — Rank on financing per person, not absolute commitment

**Status:** accepted

## Context

The first version ranked countries on absolute active commitment. The result was
uninformative: the largest borrowers occupy the top third almost mechanically, because
commitment scales with the size of the economy. The "thin portfolio" list collapsed to
one or two entries, and those entries were small states whose absence of operations had
nothing to do with need.

## Decision

Divide active commitment by the latest non-empty total population
(`SP.POP.TOTL`, `mrnev=1`), and rank on `ln(1 + financing_pc)` because the measure spans
five orders of magnitude — from zero to five figures per inhabitant.

## Consequences

- The gap becomes interpretable: need rank against delivery rank, both size-neutral.
- Population becomes a denominator and therefore a modelling assumption; a bad population
  estimate moves a country's rank.
- Countries with no active operation rank at the bottom by construction. This is a
  statement about the portfolio, not evidence that those countries receive nothing from
  other sources.
- Absolute-commitment views remain available in `mart_country` for anyone who wants them.
