"""Stage 2 - build.

Turns the raw snapshots into a SQLite warehouse: staging tables parsed from
JSON, then SQL models in models/ that produce the marts the site reads.

    python pipeline/build.py

Design notes
------------
* Staging lives in SQLite as plain tables; analysis lives in models/*.sql so
  the business logic is reviewable without reading Python.
* A project can list several countries. Amounts are split evenly across them
  and a multi_country flag is kept, so country totals still sum to the global
  portfolio total. See docs/methodology.md.
* Dates arrive in two different formats from the same API. Both parsers live
  here, in one place, with a test each.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"
DB = ROOT / "data" / "warehouse" / "portfolio.db"
MARTS = ROOT / "data" / "marts"
MODELS = ROOT / "models"

# The register still uses World Bank internal codes for a handful of countries,
# and numeric pseudo-codes for regions. Without this table roughly 4,500
# operations - the whole DRC, Yemen and Gaza programmes among them - silently
# drop out of the country layer. Each entry is verified against the country
# name carried in the same record, not guessed from the code.
LEGACY_ISO2 = {
    "ZR": "COD",   # "Democratic Republic of the Congo" (Zaire)
    "RY": "YEM",   # "Republic of Yemen"
    "GZ": "PSE",   # "West Bank and Gaza"
    "XK": "XKX",   # "Republic of Kosovo" (user-assigned code)
    "TP": "TLS",   # "Democratic Republic of Timor-Leste"
    "YF": "SRB",   # "Republic of Serbia"
}
# "YU" (Socialist Federal Republic of Yugoslavia) has no successor state that
# can legitimately absorb its operations, so those rows are left unallocated.

AGGREGATE_CODE = re.compile(r"^\d")

# The register's sector field is a 158-value operational taxonomy ("Other
# Agriculture, Fishing and Forestry") with 27% blanks. These keyword rules
# collapse it to twelve comparable groups for the concentration measure. The
# official label is kept alongside, so nothing is lost. See
# docs/sector_taxonomy.md.
SECTOR_RULES = [
    ("Health", ("health", "nutrition", "disease", "hiv", "malaria")),
    ("Education", ("education", "school", "tertiary", "literacy", "training")),
    ("Water & sanitation", ("water", "sanitation", "sewerage", "flood")),
    ("Energy & extractives", ("energy", "power", "electricity", "oil", "gas", "mining", "renewable",
                              "thermal", "hydro", "transmission", "distribution")),
    ("Transport", ("transport", "road", "rail", "port", "aviation", "airport", "highway", "shipping")),
    ("Agriculture & food", ("agric", "irrigation", "fishing", "fisheries", "forestry", "livestock",
                            "food", "crops", "fertilizer")),
    ("Social protection & labour", ("social protection", "social safety", "pension", "labor", "labour", "welfare")),
    ("Public administration", ("public administration", "government", "judicial", "law", "tax",
                               "public financial", "civil service", "procurement", "statistics",
                               "economic management", "public sector")),
    ("Finance & private sector", ("finance", "banking", "insurance", "capital market", "payment",
                                  "competitiveness", "industry", "trade", "services", "tourism", "msme",
                                  "non-bank financial", "financial sector", "industrial adjustment",
                                  "capital markets")),
    ("Digital & ICT", ("information", "communication", "ict", "telecom", "digital", "broadband")),
    ("Urban & housing", ("urban", "housing", "cadastre", "land administration", "municipal")),
    ("Environment & climate", ("environment", "climate", "biodiversity", "pollution", "carbon",
                               "waste management", "wastewater")),
]


def sector_group(name: str) -> str:
    """Collapse the operational sector label into a comparable group.

    Labels from pre-2012 lending carry a "(Historic)" prefix; it encodes the
    vintage of the code list, not the sector, so it is stripped before matching.
    """
    text = (name or "").strip()
    if text.lower().startswith("(historic)"):
        text = text[len("(historic)"):].strip()
    text = text.lower()
    if not text or text == "unclassified":
        return "Unclassified"
    for group, keywords in SECTOR_RULES:
        if any(keyword in text for keyword in keywords):
            return group
    return "Other"


def parse_amount(value) -> float | None:
    """'200,000,000' -> 200000000.0; '' and None stay missing rather than 0."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.\-]", "", str(value))
    if not text or text in {"-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value) -> date | None:
    """The API mixes ISO timestamps and US-style localised dates."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:  # 2024-12-20T00:00:00Z
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def read_snapshot(name: str) -> dict:
    """Snapshots are stored gzipped when large; accept either form."""
    plain = RAW / f"{name}.json"
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    packed = RAW / f"{name}.json.gz"
    if packed.exists():
        return json.loads(gzip.decompress(packed.read_bytes()).decode("utf-8"))
    raise SystemExit(f"missing snapshot {name}.json(.gz) - run pipeline/ingest.py first")


def load_country_codes() -> dict[str, dict]:
    payload = read_snapshot("country_codes")
    return {row["iso2"]: row for row in payload["rows"] if row.get("iso2")}


def build_staging() -> dict[str, int]:
    STAGING.mkdir(parents=True, exist_ok=True)
    codes = load_country_codes()
    projects = read_snapshot("worldbank_projects")["projects"]

    ops_rows: list[list] = []
    country_rows: list[list] = []
    skipped_no_country = 0

    for pid, rec in projects.items():
        approval = parse_date(rec.get("boardapprovaldate"))
        closing = parse_date(rec.get("closingdate"))
        total = parse_amount(rec.get("totalamt"))
        commit = parse_amount(rec.get("lendprojectcost"))
        grant = parse_amount(rec.get("grantamt"))
        status = (rec.get("projectstatusdisplay") or rec.get("status") or "").strip()

        sector = rec.get("sector1")
        sector_name = sector.get("Name") if isinstance(sector, dict) else None
        sector_name = (sector_name or "").strip() or "Unclassified"
        group_name = sector_group(sector_name)

        impl_years = None
        if approval and closing:
            impl_years = round((closing - approval).days / 365.25, 2)

        iso2_list = as_list(rec.get("countrycode"))
        iso3_list = []
        for code in iso2_list:
            upper = code.upper()
            if AGGREGATE_CODE.match(upper):  # regional / global pseudo-code
                continue
            if upper in LEGACY_ISO2:
                iso3_list.append(LEGACY_ISO2[upper])
            elif upper in codes:
                iso3_list.append(codes[upper]["iso3"])
        iso3_list = sorted(set(iso3_list))
        if not iso3_list:
            skipped_no_country += 1
            continue

        ops_rows.append(
            [
                pid,
                (rec.get("project_name") or "").strip(),
                status,
                approval.isoformat() if approval else None,
                closing.isoformat() if closing else None,
                impl_years,
                total,
                commit,
                grant,
                (rec.get("regionname") or "").strip(),
                sector_name,
                group_name,
                (rec.get("impagency") or "").strip(),
                (rec.get("prodline") or "").strip(),
                int(float(rec.get("fiscalyear"))) if rec.get("fiscalyear") else None,
                1 if len(iso3_list) > 1 else 0,
            ]
        )

        share = (total or 0.0) / len(iso3_list)
        for iso3 in iso3_list:
            country_rows.append([pid, iso3, share])

    # A handful of territories have operations but no row in the World Bank
    # country list (Taiwan is reported separately from the sovereign register).
    # Keeping their links would break the reconciliation between the portfolio
    # total and the country split, so they are dropped here and written to an
    # explicit exclusions file instead of vanishing silently.
    known = {
        (rec.get("id") or "").strip()
        for rec in read_snapshot("worldbank_countries")["rows"]
        if (rec.get("id") or "").strip()
    }
    dropped: dict[str, float] = {}
    for row in country_rows[:]:
        if row[1] not in known:
            dropped[row[1]] = dropped.get(row[1], 0.0) + float(row[2] or 0)
            country_rows.remove(row)
    live = {row[0] for row in country_rows}
    ops_rows[:] = [row for row in ops_rows if row[0] in live]
    if dropped:
        (STAGING / "exclusions.json").write_text(
            json.dumps({"territories_without_country_row": dropped}, indent=2),
            encoding="utf-8",
        )

    write_csv(
        STAGING / "ops.csv",
        [
            "project_id", "project_name", "status", "approval_date", "closing_date",
            "impl_years", "total_amt", "commit_amt", "grant_amt", "region", "sector",
            "sector_group", "implementing_agency", "product_line", "fiscal_year",
            "multi_country",
        ],
        ops_rows,
    )
    write_csv(STAGING / "op_country.csv", ["project_id", "iso3", "amount_share"], country_rows)

    sdg_payload = read_snapshot("un_sdg_series")
    country_payload = read_snapshot("country_codes")["rows"]
    m49_to_iso3 = {row["m49"]: row["iso3"] for row in country_payload if row.get("m49")}
    sdg_rows = []
    for code, observations in sdg_payload["series"].items():
        for obs in observations:
            iso3 = m49_to_iso3.get(str(obs["m49"]))
            if iso3:
                sdg_rows.append([code, iso3, int(obs["year"]), float(obs["value"])])
    write_csv(STAGING / "sdg_observations.csv", ["indicator", "iso3", "year", "value"], sdg_rows)

    population = read_snapshot("worldbank_population")["rows"]
    write_csv(
        STAGING / "population.csv",
        ["iso3", "year", "population"],
        [[r["iso3"], r["year"], r["population"]] for r in population],
    )

    print(
        f"  staging: {len(ops_rows)} operations, {len(country_rows)} country links, "
        f"{len(sdg_rows)} SDG observations ({skipped_no_country} ops dropped without a country)"
    )
    return {"ops": len(ops_rows), "op_country": len(country_rows), "sdg": len(sdg_rows)}


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def load_warehouse(staging_counts: dict[str, int]) -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(
        """
        CREATE TABLE stg_ops (
            project_id TEXT PRIMARY KEY, project_name TEXT, status TEXT,
            approval_date TEXT, closing_date TEXT, impl_years REAL,
            total_amt REAL, commit_amt REAL, grant_amt REAL,
            region TEXT, sector TEXT, sector_group TEXT,
            implementing_agency TEXT, product_line TEXT, fiscal_year INTEGER,
            multi_country INTEGER
        );
        CREATE TABLE stg_op_country (project_id TEXT, iso3 TEXT, amount_share REAL);
        CREATE TABLE stg_sdg (indicator TEXT, iso3 TEXT, year INTEGER, value REAL);
        CREATE TABLE stg_pop (iso3 TEXT PRIMARY KEY, year INTEGER, population REAL);
        CREATE TABLE stg_country (
            iso3 TEXT PRIMARY KEY, iso2 TEXT, m49 TEXT, name TEXT,
            region TEXT, income_level TEXT
        );
        CREATE TABLE stg_indicator (
            indicator TEXT PRIMARY KEY, label TEXT, target REAL, direction TEXT
        );
        """
    )
    load_csv(conn, "stg_ops", STAGING / "ops.csv")
    load_csv(conn, "stg_op_country", STAGING / "op_country.csv")
    load_csv(conn, "stg_sdg", STAGING / "sdg_observations.csv")
    load_csv(conn, "stg_pop", STAGING / "population.csv")

    wb = read_snapshot("worldbank_countries")["rows"]
    codes = read_snapshot("country_codes")["rows"]
    by_iso3 = {row["iso3"]: row for row in codes if row.get("iso3")}

    country_records = []
    for rec in wb:
        iso3 = (rec.get("id") or "").strip()
        region = ((rec.get("region") or {}).get("value") or "").strip()
        income = (rec.get("incomeLevel") or {}).get("value", "")
        if not iso3 or region == "Aggregates" or iso3 in {"XKS", "ZIK"}:
            continue
        meta = by_iso3.get(iso3, {})
        country_records.append(
            [iso3, meta.get("iso2", ""), meta.get("m49", ""),
             (rec.get("name") or "").strip(), region, income]
        )
    conn.executemany("INSERT INTO stg_country VALUES (?,?,?,?,?,?)", country_records)

    sdg_meta = read_snapshot("un_sdg_series")["indicators"]
    conn.executemany(
        "INSERT INTO stg_indicator VALUES (?,?,?,?)",
        [[k, v["label"], v["target"], v["direction"]] for k, v in sdg_meta.items()],
    )
    conn.commit()
    conn.close()
    print(f"  warehouse: {DB.relative_to(ROOT)} "
          f"({staging_counts['ops']} ops, {len(country_records)} countries)")


def load_csv(conn: sqlite3.Connection, table: str, path: Path) -> None:
    with path.open(encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        placeholders = ",".join("?" * len(header))
        rows = [normalise_row(row) for row in reader]
        conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def normalise_row(row: list[str]) -> list:
    out: list = []
    for value in row:
        if value == "":
            out.append(None)
        elif re.fullmatch(r"-?\d+", value):
            out.append(int(value))
        elif re.fullmatch(r"-?\d*\.\d+", value):
            out.append(float(value))
        else:
            out.append(value)
    return out


def run_models() -> list[str]:
    conn = sqlite3.connect(DB)
    executed = []
    for path in sorted(MODELS.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
        executed.append(path.name)
        print(f"  model: {path.name}")
    conn.commit()
    conn.close()
    return executed


def export_marts() -> dict[str, int]:
    MARTS.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mart_%' ORDER BY name"
    )]
    counts = {}
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        with (MARTS / f"{table}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(rows[0].keys() if rows else [])
            for row in rows:
                writer.writerow(list(row))
        counts[table] = len(rows)
        print(f"  mart:  {table}.csv ({len(rows)} rows)")
    conn.close()
    return counts


def main() -> int:
    print("building warehouse")
    counts = build_staging()
    load_warehouse(counts)
    models = run_models()
    export_marts()
    print(f"done - {len(models)} models executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
