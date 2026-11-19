# SOP — refresh the data

Quarterly, or before any presentation. Roughly ten minutes, of which eight are download.

## 1. Check the last run

```bash
cat data/raw/manifest.json
```

Note `retrieved_at` and confirm the snapshot set is complete (seven files).

## 2. Refetch

```bash
python pipeline/ingest.py --force
```

Expect ~23 pages from the project register and several pages per SDG series. The fetcher retries
on `RemoteDisconnected` and `HTTPException`, not only on `URLError`; an interrupted run is safe
to repeat, because each snapshot is written atomically after its own fetch completes.

## 3. Rebuild and test

```bash
python pipeline/build.py && python pipeline/site.py && python -m unittest discover -s tests
```

All 19 tests must pass. A reconciliation failure means the country split no longer sums to the
portfolio total — stop and inspect `data/staging/exclusions.json` before publishing anything.

## 4. Sanity-check the movement

```bash
git diff --stat data/marts/
```

Read `mart_portfolio_health.csv` against the previous run. Active value moving by more than a
few percent, or `countries_with_portfolio` changing, is usually a register revision rather than
a code change; note it in the commit message.

## 5. Publish

Rebuild the screenshot in `docs/img/dashboard.png`, then commit `data/`, `site/index.html` and
the image together, so the repository's picture always matches its numbers.

## Failure modes seen in practice

| Symptom | Cause | Fix |
|---|---|---|
| Only ~18,000 operations | paging on `page` instead of `os` | the API ignores `page`; offsets must advance by 1,000 |
| Four thousand operations missing, DRC and Yemen have none | legacy ISO-2 codes unresolved | extend `LEGACY_ISO2` |
| Snapshot 20 MB+ | undeclared API fields written | keep the declared field list in `ingest.py` |
| Need index double-counted | urban/rural or sex rows kept | filter on `dimensions.Location` |
