# 0001 — Use a public sovereign portfolio as a proxy

**Status:** accepted

## Context

The question is institutional: which country portfolios carry more need than delivery. The
natural data source would be a single agency's programme register. In practice the machine-readable
routes to those registers are closed or unstable: the IATI datastore requires an API key (401),
the legacy datastore endpoint is retired (404), and the publisher pages return either 403 or a
JavaScript shell with no data behind it.

## Decision

Build on the World Bank project register, which is open, complete and documented, and treat it
as a proxy for a sovereign development portfolio. Keep the ingest layer adapter-shaped — one
function per source, a declared field list, a snapshot contract — so an institutional register
can be added without touching the models.

## Consequences

- The analysis is legitimate at the level of the development finance system, and explicitly
  not a claim about any one agency's portfolio.
- Per-country figures include operations that an agency-level review would exclude.
- Every number is reproducible from a public snapshot, which is worth more for a demonstrator
  than the extra fidelity of a closed source.
