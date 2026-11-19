# 0006 — Collapse sector labels with a keyword rule table

**Status:** accepted

## Context

157 distinct sector labels, no hierarchy, 20% of value null. A hand-written lookup of 157
entries is precise today and silently wrong tomorrow, because new labels fall through it
without notice.

## Decision

A 12-group keyword rule table evaluated in a fixed order, with the `(Historic)` prefix stripped
first, and the raw label retained in staging.

## Consequences

- New labels land in a reported `Other` residual (currently 0.7% of value) instead of
  disappearing.
- Order is load-bearing and documented; changing a keyword can move value between groups, so
  the audit query in `docs/sector_taxonomy.md` is part of the review.
- Sector shares use classified value as the denominator, which is stated wherever they appear.
