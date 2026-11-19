# 0004 — Rank on a continuous gap, not a hard quadrant

**Status:** accepted

## Context

A 3×3 grid of need tercile against portfolio tercile is easy to defend in a slide, but its
cells are sparse: only four countries land in "high need / thin portfolio". Two of the most
informative cases — the Democratic Republic of Congo and Chad — fall into "aligned" because
their portfolios are large in absolute terms, even though their per-capita financing is
near the bottom of the distribution.

## Decision

Keep the grid for mapping (it is the view a non-analyst reads fastest) and rank the short list
on `allocation_gap = need_percentile − financing_percentile`, a continuous measure in (−1, 1).

## Consequences

- The short list contains countries from more than one quadrant, each explained by its own
  columns rather than by its cell.
- The map and the table can disagree; the site says so explicitly, and the disagreement is
  the finding rather than a bug.
