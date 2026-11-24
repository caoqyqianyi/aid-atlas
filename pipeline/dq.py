"""Data-quality gate.

Runs a fixed set of checks over the warehouse and the marts, writes
data/marts/mart_dq.csv for the site, and exits non-zero if any check fails so
CI stops before rendering a page that quotes numbers nobody verified.

    python pipeline/dq.py

Design notes
------------
* Every check is deterministic given the committed snapshots: no wall-clock
  dates, no random sampling, so a rebuild on any day produces the same file.
* Checks are statements about the data, not about the code: duplicates,
  referential integrity, totals that must reconcile across layers, coverage
  floors and bounds. Anything tighter belongs in the unit tests.
"""

from __future__ import annotations

import csv
import gzip
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse" / "portfolio.db"
MARTS = ROOT / "data" / "marts"
RAW = ROOT / "data" / "raw"
OUT = MARTS / "mart_dq.csv"


def load_csv(name: str) -> list[dict]:
    with (MARTS / f"{name}.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def check(conn: sqlite3.Connection) -> list[dict]:
    """Return one row per check: id, category, statement, value, threshold, status."""
    health = {row["metric"]: num(row["value"]) for row in load_csv("mart_portfolio_health")}
    countries = load_csv("mart_country")
    priority = load_csv("mart_priority")
    scenario = load_csv("mart_reallocation")[0]
    perf = load_csv("mart_portfolio_performance")

    ops = conn.execute("SELECT COUNT(*) FROM stg_ops").fetchone()[0]
    raw_projects = json.loads(gzip.decompress((RAW / "worldbank_projects.json.gz").read_bytes()))
    raw_records = len(raw_projects["projects"])
    dup_ids = conn.execute(
        "SELECT COUNT(*) FROM (SELECT project_id FROM stg_ops GROUP BY 1 HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    orphan_links = conn.execute(
        "SELECT COUNT(*) FROM stg_op_country c WHERE NOT EXISTS"
        " (SELECT 1 FROM stg_country s WHERE s.iso3 = c.iso3)"
    ).fetchone()[0]
    link_sum = conn.execute("SELECT SUM(amount_share) FROM stg_op_country").fetchone()[0] or 0
    op_sum = conn.execute("SELECT SUM(total_amt) FROM stg_ops").fetchone()[0] or 0
    missing_dates = conn.execute(
        "SELECT COUNT(*) FROM stg_ops WHERE approval_date IS NULL"
    ).fetchone()[0]
    classified = conn.execute(
        "SELECT SUM(total_amt) FROM stg_ops WHERE sector_group <> 'Unclassified'"
    ).fetchone()[0] or 0
    # The SDG extract ships "nan" as a string for years it has not filled yet.
    # Stored as text, a NaN passes every numeric bound and then reads as the
    # largest gap in the country's index - so it gets its own check.
    sdg_bad = conn.execute(
        "SELECT COUNT(*) FROM stg_sdg WHERE typeof(value) <> 'real'"
        " OR value < 0 OR value > 100"
    ).fetchone()[0]

    country_total = sum(num(r["total_commitment"]) for r in countries)
    country_active = sum(num(r["active_commitment"]) for r in countries)
    with_need = sum(1 for r in countries if r["need_complete"] == "1")
    gaps = [num(r["allocation_gap"]) for r in countries if r["need_complete"] == "1"]
    ranks = sorted(int(num(r["priority_rank"])) for r in priority)
    pool = num(scenario["pool_usd"])
    share = num(scenario["share"])
    expected_pool = share * health.get("active_value_usd", 0)

    def ratio(a: float, b: float) -> float:
        return a / b if b else 0.0

    rows: list[dict] = []

    def add(cid, category, statement, value, threshold, ok, detail=""):
        rows.append(
            {
                "check_id": cid,
                "category": category,
                "check": statement,
                "value": round(value, 6),
                "threshold": threshold,
                "status": "PASS" if ok else "FAIL",
                "detail": detail,
            }
        )

    add("dq_01", "Integrity", "One row per project in staging", dup_ids, "= 0", dup_ids == 0,
        f"{ops:,} operations")
    add("dq_02", "Integrity", "Country links resolve to a known country", orphan_links, "= 0",
        orphan_links == 0, "every link has an ISO-3 in the reference table")
    add("dq_03", "Reconciliation", "Split amounts equal the register total",
        abs(link_sum - op_sum), "< 0.01 USD", abs(link_sum - op_sum) < 0.01,
        "commitments split across recipients sum back to the whole")
    add("dq_04", "Reconciliation", "Country layer equals the portfolio total",
        ratio(abs(country_total - health.get("total_value_usd", 0)), health.get("total_value_usd", 1)),
        "< 0.5%", ratio(abs(country_total - health.get("total_value_usd", 0)),
                        health.get("total_value_usd", 1)) < 0.005,
        "sum of country commitments vs mart_portfolio_health")
    add("dq_05", "Reconciliation", "Active value agrees across layers",
        ratio(abs(country_active - health.get("active_value_usd", 0)), health.get("active_value_usd", 1)),
        "< 0.5%", ratio(abs(country_active - health.get("active_value_usd", 0)),
                        health.get("active_value_usd", 1)) < 0.005,
        "mart_country vs mart_portfolio_health")
    add("dq_06", "Coverage", "Register records retained in staging",
        ratio(ops, raw_records), ">= 0.75", ratio(ops, raw_records) >= 0.75,
        f"{ops:,} of {raw_records:,} records; the remainder carry no resolvable "
        f"country code, are regional entries or repeat across pages")
    add("dq_07", "Completeness", "Operations with an approval date", ratio(ops - missing_dates, ops),
        ">= 0.75", ratio(ops - missing_dates, ops) >= 0.75,
        f"{missing_dates:,} of {ops:,} operations carry no approval date")
    add("dq_08", "Completeness", "Value with a sector classification", ratio(classified, op_sum),
        ">= 0.75", ratio(classified, op_sum) >= 0.75,
        f"{ratio(op_sum - classified, op_sum):.1%} of value is unclassified")
    add("dq_09", "Coverage", "Countries with a measured need index", with_need, ">= 150",
        with_need >= 150, f"{with_need} of {len(countries)} countries carry the index")
    add("dq_10", "Bounds", "Allocation gap inside [-1, 1]",
        max((abs(g) for g in gaps), default=0), "<= 1.0", all(abs(g) <= 1.0 for g in gaps),
        f"largest absolute gap {max((abs(g) for g in gaps), default=0):.2f}")
    add("dq_11", "Uniqueness", "Short-list ranks are 1..25 without gaps",
        ranks[-1] if ranks else 0, "= 25, all distinct",
        ranks == list(range(1, len(priority) + 1)),
        f"{len(priority)} rows, ranks {ranks[0]} to {ranks[-1]}")
    add("dq_12", "Scenario", "Scenario pool equals its stated share of active value",
        ratio(abs(pool - expected_pool), expected_pool), "< 1%",
        ratio(abs(pool - expected_pool), expected_pool) < 0.01,
        "mart_reallocation vs mart_portfolio_health")
    add("dq_13", "Reconciliation", "Operating profile buckets sum to the portfolio",
        abs(sum(num(r["value"]) for r in perf if r["dimension"] == "status")
            - health.get("total_value_usd", 0)), "< 0.01 USD",
        abs(sum(num(r["value"]) for r in perf if r["dimension"] == "status")
            - health.get("total_value_usd", 0)) < 0.01,
        "status buckets are exhaustive by construction")
    add("dq_14", "Bounds", "SDG observations are finite percentages",
        sdg_bad, "= 0", sdg_bad == 0,
        "no NaN placeholders and no reading outside 0-100")
    return rows


def main() -> int:
    if not DB.exists():
        print("no warehouse at data/warehouse/portfolio.db - run pipeline/build.py first")
        return 2
    conn = sqlite3.connect(DB)
    rows = check(conn)
    conn.close()

    MARTS.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    failed = [r for r in rows if r["status"] == "FAIL"]
    width = max(len(r["check"]) for r in rows)
    for r in rows:
        print(f"  [{r['status']}] {r['check']:<{width}}  {r['detail']}")
    print(f"{len(rows) - len(failed)} of {len(rows)} checks pass "
          f"-> {OUT.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
