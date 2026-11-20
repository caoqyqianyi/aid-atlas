"""Stage 1 - ingest.

Pulls the upstream public sources and writes checksummed snapshots to
data/raw/. Nothing downstream touches the network, so every figure in
this repo is reproducible from the committed snapshot.

Sources
-------
World Bank projects API   : project-level portfolio records (22k+ operations)
World Bank country API    : ISO2/ISO3/region/income metadata
UN SDG indicator API      : official country series, used for the needs layer
ISO 3166 / UN M49 table   : one canonical key to reconcile all three

Usage
-----
    python pipeline/ingest.py            # normal refresh
    python pipeline/ingest.py --sample   # 300 projects, for quick iteration
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import http.client
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

WB_PROJECTS = "https://search.worldbank.org/api/v2/projects"
WB_COUNTRIES = "https://api.worldbank.org/v2/country"
SDG_SERIES = "https://unstats.un.org/SDGAPI/v1/sdg/Series/Data"
WB_POPULATION = "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL"
COUNTRY_CODES = "https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv"
NE_BOUNDARIES = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"

PROJECT_FIELDS = (
    "id", "project_name", "countrycode", "countryname", "regionname",
    "status", "projectstatusdisplay", "boardapprovaldate", "closingdate",
    "totalamt", "lendprojectcost", "grantamt", "ibrdcommamt", "idacommamt",
    "sector1", "impagency", "prodline", "fiscalyear",
)

# Indicator choice is deliberate: each series carries a stated 2030 target of
# either 0% or 100%, so the "gap" needs no arbitrary thresholds.
# See docs/methodology.md.
SDG_INDICATORS = {
    "SI_POV_DAY1": {"label": "Population below international poverty line", "target": 0.0, "direction": "lower_better"},
    "SN_ITK_DEFC": {"label": "Prevalence of undernourishment", "target": 0.0, "direction": "lower_better"},
    "SH_H2O_SAFE": {"label": "Safely managed drinking water services", "target": 100.0, "direction": "higher_better"},
    "EG_ACS_ELEC": {"label": "Access to electricity", "target": 100.0, "direction": "higher_better"},
}

# Country series carry urban/rural and sex breakdowns beside the national total.
# Only the national total is kept so every ratio stays comparable.
TOTAL_LOCATIONS = {"", "ALLAREA", "TOTAL"}
MIN_YEAR = 2005


def fetch_json(url: str, params: dict, retries: int = 4) -> dict:
    query = urllib.parse.urlencode(params, doseq=True)
    full = f"{url}?{query}"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "aid-atlas/0.1 (research)"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                json.JSONDecodeError, ConnectionError) as exc:
            # Public statistical APIs drop connections under load rather than
            # returning an error. Back off and try again; fail loudly at the end.
            if attempt == retries:
                raise SystemExit(f"failed after {retries} attempts: {full}\n{exc!r}")
            print(f"  retry {attempt}/{retries} - {exc!r}", file=sys.stderr)
            time.sleep(4 * attempt)
    raise AssertionError("unreachable")


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "aid-atlas/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8")


def write_snapshot(name: str, payload: dict, manifest: list, compress: bool = False) -> Path:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw_bytes = body.encode("utf-8")
    if compress:
        path = RAW / f"{name}.json.gz"
        path.write_bytes(gzip.compress(raw_bytes, compresslevel=9))
    else:
        path = RAW / f"{name}.json"
        path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    manifest.append(
        {
            "file": path.name,
            "sha256": digest,
            "compressed": compress,
            "bytes_uncompressed": len(raw_bytes),
            "bytes_on_disk": path.stat().st_size,
            "records": _count(payload),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    print(f"  {path.name:38s} {path.stat().st_size / 1024:9.1f} KB on disk  {digest[:12]}")
    return path


def _count(payload: dict) -> int:
    for key in ("projects", "data", "series", "rows"):
        if key in payload:
            val = payload[key]
            return len(val) if isinstance(val, (list, dict)) else int(val)
    return 0


def ingest_projects(sample: bool) -> dict:
    """Page through the portfolio API.

    The service paginates by request offset (`os`), not by page number - it
    silently returns the first page for any `page` value it is given. Rows
    come back keyed by project id, so duplicates collapse on update.
    """
    rows = 300 if sample else 1000
    fl = ",".join(PROJECT_FIELDS)
    collected: dict[str, dict] = {}
    first_page = fetch_json(WB_PROJECTS, {"format": "json", "rows": rows, "os": 0, "fl": fl})
    total = int(first_page.get("total", 0))
    collected.update(first_page.get("projects", {}))
    print(f"  portfolio: {total} projects, offset paging at {rows} rows/request")

    offset = rows
    while len(collected) < total:
        if sample and len(collected) >= 300:
            break
        payload = fetch_json(WB_PROJECTS, {"format": "json", "rows": rows, "os": offset, "fl": fl})
        batch = payload.get("projects", {})
        if not batch:
            break
        before = len(collected)
        collected.update(batch)
        if len(collected) == before:
            break
        offset += rows
        if offset % (rows * 5) == 0:
            print(f"    offset {offset}/{total} - {len(collected)} rows")

    # The API returns a default field set on top of the requested one, including
    # long project abstracts. Keep only the declared fields, which cuts the
    # snapshot from ~28 MB to a few.
    slim = {
        pid: {field: rec.get(field) for field in PROJECT_FIELDS}
        for pid, rec in collected.items()
    }
    return {"total": total, "rows": len(slim), "projects": slim}


def ingest_population() -> dict:
    """Most recent non-empty population per country, for per-capita financing.

    Absolute portfolio size ranks countries by the size of their economy. Per
    person financing is the size-neutral measure the allocation question
    actually needs.
    """
    payload = fetch_json(WB_POPULATION, {"format": "json", "per_page": 400, "mrnev": 1})
    rows = [
        {"iso3": rec["countryiso3code"], "year": int(rec["date"]), "population": rec["value"]}
        for rec in payload[1]
        if rec.get("countryiso3code") and rec.get("value")
    ]
    print(f"    population: {len(rows)} countries")
    return {"rows": rows}


def ingest_countries() -> dict:
    payload = fetch_json(WB_COUNTRIES, {"format": "json", "per_page": 400})
    # Response is [metadata, [country records]] - the second element is the list.
    return {"rows": payload[1]}


def ingest_country_codes() -> list[dict]:
    """ISO 3166 + M49 reference table, used to reconcile the three sources.

    The SDG API identifies countries by M49 numeric code, the World Bank by
    ISO2, Natural Earth by ISO3. One canonical table avoids name matching.
    """
    text = fetch_text(COUNTRY_CODES)
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        iso3 = (rec.get("ISO3166-1-Alpha-3") or "").strip()
        iso2 = (rec.get("ISO3166-1-Alpha-2") or "").strip()
        m49 = (rec.get("ISO3166-1-numeric") or "").strip()
        if not iso3 or not m49:
            continue
        rows.append(
            {
                "iso3": iso3,
                "iso2": iso2,
                "m49": m49.lstrip("0"),
                "name": (rec.get("UNTERM English Short") or rec.get("CLDR display name") or "").strip(),
            }
        )
    (RAW / "country_codes.csv").write_text(text, encoding="utf-8")
    return rows


def ingest_sdg(valid_m49: set[str]) -> dict:
    """Fetch the four series and keep only national totals.

    Sub-national and urban/rural rows, regional aggregates and pre-2005
    observations are dropped here rather than downstream, so the committed
    snapshot is already the analysable one.
    """
    series = {}
    for code in SDG_INDICATORS:
        rows = []
        page, total_pages = 1, 1
        while page <= total_pages:
            data = fetch_json(SDG_SERIES, {"seriesCode": code, "pageSize": 5000, "page": page})
            total_pages = int(data.get("totalPages", 1) or 1)
            for rec in data.get("data", []):
                dims = rec.get("dimensions") or {}
                if str(dims.get("Location") or "").strip() not in TOTAL_LOCATIONS:
                    continue
                area = str(rec.get("geoAreaCode") or "").lstrip("0")
                if area not in valid_m49:
                    continue
                year = rec.get("timePeriodStart")
                if year is None or float(year) < MIN_YEAR:
                    continue
                try:
                    value = float(rec.get("value"))
                except (TypeError, ValueError):
                    continue
                rows.append({"m49": area, "year": int(float(year)), "value": value})
            page += 1
        series[code] = rows
        print(f"    {code}: {len(rows)} national observations")
    return {"indicators": SDG_INDICATORS, "series": series}


def ingest_boundaries() -> dict:
    """Natural Earth 1:110m admin-0 boundaries, for the map layer only."""
    geo = json.loads(fetch_text(NE_BOUNDARIES))
    return {"features": len(geo["features"]), "geojson": geo}


def _exists(name: str) -> bool:
    return (RAW / f"{name}.json").exists() or (RAW / f"{name}.json.gz").exists()


def rebuild_manifest() -> dict:
    """Hash whatever is actually on disk.

    Recomputing from disk rather than bookkeeping each write means the manifest
    can never drift from the snapshots, including after a partial refresh.
    """
    entries = []
    for path in sorted(RAW.iterdir()):
        if path.name == "manifest.json" or path.suffix == ".md":
            continue
        payload = path.read_bytes()
        digest = hashlib.sha256(gzip.decompress(payload) if path.suffix == ".gz" else payload).hexdigest()
        entries.append(
            {
                "file": path.name,
                "sha256": digest,
                "bytes_on_disk": len(payload),
                "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                .isoformat(timespec="seconds"),
            }
        )
    manifest = {"snapshots": entries, "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  manifest: {len(entries)} snapshots hashed")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="pull a 300-project slice")
    parser.add_argument("--force", action="store_true", help="refresh snapshots that already exist")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    print("ingesting sources")

    refresh = lambda name: args.force or not _exists(name)

    if refresh("worldbank_projects"):
        write_snapshot("worldbank_projects", ingest_projects(args.sample), [], compress=True)
    else:
        print("  worldbank_projects.json.gz present - skipping")
    if refresh("worldbank_countries"):
        write_snapshot("worldbank_countries", ingest_countries(), [], compress=True)

    if refresh("country_codes"):
        codes = ingest_country_codes()
        write_snapshot("country_codes", {"rows": codes}, [])
    else:
        codes = json.loads((RAW / "country_codes.json").read_text(encoding="utf-8"))["rows"]
        print("  country_codes.json present - skipping")

    valid_m49 = {row["m49"] for row in codes if row["m49"]}
    if refresh("un_sdg_series"):
        write_snapshot("un_sdg_series", ingest_sdg(valid_m49), [], compress=True)
    else:
        print("  un_sdg_series.json.gz present - skipping")

    if refresh("worldbank_population"):
        write_snapshot("worldbank_population", ingest_population(), [], compress=True)

    if refresh("ne_110m_admin_0_countries"):
        write_snapshot("ne_110m_admin_0_countries", ingest_boundaries(), [], compress=True)

    rebuild_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
