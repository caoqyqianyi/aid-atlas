# SOP — add an SDG indicator to the need index

The index is deliberately small: four series, each with a stated 2030 target of 0% or 100%.
Adding a fifth changes every rank, so it is a methodology change, not a data change.

## 1. Qualify the indicator

It must have (a) a numeric 2030 target of 0 or 100, (b) national totals in the SDG API,
(c) coverage for most of the 167 countries already ranked. An indicator with a target of
"halve by 2030" does not qualify without inventing a baseline year.

## 2. Confirm the series code

```bash
python pipeline/ingest.py --probe <SERIES_CODE>
```

Prints row count, dimension values and the latest year. Confirm the series exists — several
plausible-looking codes return zero rows (`EG_ELC_ACCS` is empty; `EG_ACS_ELEC` is the live
one).

## 3. Register it

Add to `SDG_SERIES` in `pipeline/ingest.py`:

```python
"SH_STA_...": {"label": "...", "target": 100, "direction": "higher_better"}
```

and to `SDG_SERIES` in `pipeline/build.py` so the gap is computed (`direction` decides whether
the gap is `target − value` or `value − target`).

## 4. Re-ingest and rebuild

```bash
python pipeline/ingest.py --force && python pipeline/build.py && python pipeline/site.py
python -m unittest discover -s tests
```

The coverage rule (`need_complete` requires three of four) becomes "three of five". Update it
in `models/20_mart_country.sql` and in `docs/methodology.md` in the same commit.

## 5. Record the change

Write an ADR in `docs/decisions/` with the before/after rank movement for the top ten
countries. If the short list changes materially, say so in the commit message rather than
letting a reader discover it from a diff.
