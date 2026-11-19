# 0005 — One self-contained HTML file instead of a dashboard server

**Status:** accepted

## Context

The output has to be readable by someone who will not clone a repository, install a stack or
run a server. A hosted dashboard adds an operational dependency and a link that rots.

## Decision

`site.py` embeds the marts and the country geometry directly into the HTML as a single JSON
payload, uses plain JavaScript and native SVG, and loads only D3 from a CDN. No API call,
no build step, no local server: `file://` works.

## Consequences

- 285 KB for 217 countries and 177 polygons — acceptable, and it grows linearly.
- The page is not a multi-page app; a second analysis means a second file.
- D3 is the only external dependency, and the page degrades to a readable static skeleton
  if the CDN is unreachable.
