# 0003 — Percentile ranks instead of NTILE bins

**Status:** accepted

## Context

Tercles were built with `NTILE(3)`. Dozens of countries tie at exactly zero active financing,
and `NTILE` splits a tie group arbitrarily across bins. The effect was concrete: part of the
zero-financing block was labelled "middle" and the corresponding countries disappeared from
the short list.

## Decision

Use `PERCENT_RANK()` and cut at 0.3333 / 0.6667. Ties share a rank, so zero financing falls
entirely into the bottom third. The same cut points reproduce terciles where no ties exist,
so the 3×3 map and the continuous ranking stay consistent with each other.

## Consequences

- Bin sizes are no longer exactly one third; heavy tie groups make the bottom bin larger.
  This is the correct behaviour for a skewed distribution and is stated in the methodology.
- Cut points are exported by construction, so the site and a reader's own query use identical
  boundaries.
