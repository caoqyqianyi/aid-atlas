"""Stage 3 - render.

Reads the marts and the Natural Earth snapshot and writes one self-contained
site/index.html. No server, no build step, no external data files: the page
opens by double-click and works offline apart from the D3 bundle.

    python pipeline/site.py
"""

from __future__ import annotations

import csv
import gzip
import json
import math
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARTS = ROOT / "data" / "marts"
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site"

# Sequential ramps blended into a 3x3 bivariate grid.
PORTFOLIO_RAMP = ["#dbe8f1", "#6ea3c6", "#005f93"]
NEED_RAMP = ["#fdf0d6", "#f0bf5e", "#c9791f"]


def load_csv(name: str) -> list[dict]:
    with (MARTS / f"{name}.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def num(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def blend(a: str, b: str, weight: float = 0.5) -> str:
    a, b = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(f"{round(va * (1 - weight) + vb * weight):02x}")
    return "#" + "".join(out)


def bivariate_colours() -> dict[str, str]:
    """A 3x3 matrix keyed "portfolio_tercile + need_tercile".

    A straight RGB blend of two ramps produces nine colours that are hard to
    tell apart (the amber and the teal meet in the middle as olive). The cells
    are instead picked to keep one axis legible at a time: amber means need,
    blue means portfolio, pale means neither, and dark slate is the
    high-need/large-portfolio case a 3x3 grid is built to expose.
    """
    return {
        "13": "#c9791f", "23": "#35506b", "33": "#101d2c",
        "12": "#e9b96b", "22": "#7d97ab", "32": "#1c4a6e",
        "11": "#fdf0d6", "21": "#9fc0d6", "31": "#005f93",
    }


SOVEREIGN_UNITS = {"TWN": "CHN"}


def simplify_geometry(path: Path) -> dict:
    """Keep two properties and round coordinates to roughly 1 km.

    Natural Earth at 110m is 840 KB with ~90 metadata fields per feature.
    Rounding coordinates and dropping properties cuts the inline payload to
    about a third without visibly changing a 1000px map.
    """
    if path.suffix == ".gz":
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    geo = payload.get("geojson", payload)
    features = []
    for feature in geo["features"]:
        props = feature.get("properties", {})
        iso3 = str(props.get("ISO_A3") or "")
        if iso3 in ("-99", "", "None"):
            iso3 = str(props.get("ADM0_A3") or "")
        if not iso3:
            continue
        # Cartographic convention: one China. Taiwan is drawn at this scale as a
        # separate island polygon, so it is keyed to the China feature instead of
        # standing as its own unit; Hong Kong and Macau have no polygon at 1:110m.
        iso3 = SOVEREIGN_UNITS.get(iso3, iso3)
        features.append(
            {
                "type": "Feature",
                "properties": {"iso3": iso3, "name": props.get("NAME") or props.get("ADMIN") or ""},
                "geometry": round_coords(feature["geometry"]),
            }
        )
    return {"type": "FeatureCollection", "features": features}


def round_coords(geometry: dict) -> dict:
    def walk(node):
        if isinstance(node, list) and node and isinstance(node[0], (int, float)):
            return [round(node[0], 2), round(node[1], 2)]
        if isinstance(node, list):
            return [walk(child) for child in node]
        return node

    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"])}


def tercile_thresholds(values: list[float]) -> list[float]:
    values = sorted(v for v in values if v is not None)
    if not values:
        return [0.0, 0.0]
    n = len(values)
    return [round(values[n // 3], 4), round(values[2 * n // 3], 4)]


def snapshot_date() -> str:
    """Date the raw snapshots were captured, not the date of this render.

    Using today() would rewrite the page every day without any new data and
    make the committed site impossible to reproduce, which is exactly what the
    CI drift check exists to prevent.
    """
    path = RAW / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return date.today().isoformat()
    stamps = [s.get("retrieved_at", "") for s in manifest.get("snapshots", [])
              if s.get("retrieved_at")]
    return max(stamps)[:10] if stamps else date.today().isoformat()

def pearson(xs: list[float], ys: list[float]) -> float:
    """Correlation without pulling in numpy; the payload needs one number."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs) ** 0.5
    syy = sum((y - my) ** 2 for y in ys) ** 0.5
    return sxy / (sxx * syy) if sxx and syy else 0.0


def build_robustness(rows: list[dict]) -> dict:
    """Fold the long robustness mart into the matrix the page draws.

    Columns are the six readings; rows are the union of every country that
    reaches the top 25 under at least one of them, so a country that only
    enters under a single definition is still on the page to be seen entering.
    """
    variants = [
        ("equal", "Equal weights"),
        ("no_poverty", "No poverty"),
        ("no_hunger", "No hunger"),
        ("no_water", "No water"),
        ("no_energy", "No energy"),
        ("worst", "Worst dimension"),
    ]
    by_country: dict[str, dict] = {}
    for row in rows:
        iso = row["iso3"]
        entry = by_country.setdefault(iso, {"iso3": iso, "name": row["name"], "ranks": {}})
        entry["ranks"][row["variant"]] = int(num(row["rank"], 0))
        if row["variant"] == "equal":
            entry["need"] = num(row["need_index"])
            # The published rank, not this variant's rank: ties in the gap
            # would otherwise number two countries 9th and contradict the
            # table two sections above.
            entry["shortlist"] = int(num(row["shortlist_rank"], 0)) or None

    baseline = [c for c in by_country.values() if c.get("shortlist")]
    baseline.sort(key=lambda c: c["shortlist"])
    keep = {c["iso3"] for c in baseline}

    shown = [c for c in by_country.values() if min(c["ranks"].values()) <= 25]
    shown.sort(key=lambda c: (c.get("shortlist") is None, c.get("shortlist") or 999,
                              min(c["ranks"].values())))

    columns = []
    for key, label in variants:
        kept = sum(1 for c in baseline if c["ranks"].get(key, 999) <= 25)
        columns.append({"key": key, "label": label, "kept": kept})

    matrix = []
    for c in shown:
        held = sum(1 for col in columns if c["ranks"].get(col["key"], 999) <= 25)
        matrix.append(
            {
                "iso3": c["iso3"],
                "name": c["name"],
                "baseline": c.get("shortlist"),
                "need": c.get("need"),
                "held": held,
                "ranks": [c["ranks"].get(col["key"]) for col in columns],
            }
        )

    stable = sum(1 for c in matrix if c["held"] == len(columns))
    return {
        "columns": columns,
        "rows": matrix,
        "stable": stable,
        "baseline": len(baseline),
        "n_countries": len(by_country),
        "drifting": [c["iso3"] for c in matrix if c["held"] <= 2],
        "keep": sorted(keep),
    }


def build_convergence(rows: list[dict]) -> dict:
    """Starting need against the change since 2015.

    Absolute points, not percentages, because that is the scale the gap is
    measured on. A negative slope means the countries with the most need
    improved fastest - convergence - and the slope is what turns that into a
    rate rather than an impression.
    """
    points = []
    for r in rows:
        points.append(
            {
                "iso3": r["iso3"],
                "name": r["name"],
                "region": r["region"],
                "n15": num(r["need_2015"]),
                "n24": num(r["need_latest"]),
                "year": int(num(r["latest_year"], 0)),
                "delta": num(r["delta_pp"]),
                "pc": num(r["post2015_pc"], 0.0),
                "pop": round(num(r["population"], 0)),
                "rank": int(num(r["priority_rank"], 0)) or None,
            }
        )
    points.sort(key=lambda p: p["delta"] if p["delta"] is not None else 0)
    deltas = [p["delta"] for p in points if p["delta"] is not None]
    starts = [p["n15"] for p in points if p["n15"] is not None]
    money = [p for p in points if (p["pc"] or 0) > 0]

    mx, my = sum(starts) / len(starts), sum(deltas) / len(deltas)
    slope = (sum((x - mx) * (y - my) for x, y in zip(starts, deltas))
             / sum((x - mx) ** 2 for x in starts)) if starts else 0.0
    window = sorted(p["year"] - 2015 for p in points)[len(points) // 2]

    def bucket(lo: float, hi: float) -> float:
        vals = [p["delta"] for p in points if lo <= p["n15"] < hi]
        return round(sorted(vals)[len(vals) // 2], 1) if vals else 0.0

    # Half-life of the average gap if the fitted rate repeats: a statement about
    # the observed window, not a forecast.
    half_life = 0
    if slope < 0:
        half_life = int(round(math.log(0.5) / math.log(1 + slope) * window))

    return {
        "rows": points,
        "n": len(points),
        "window": window,
        "median": round(sorted(deltas)[len(deltas) // 2], 2) if deltas else 0.0,
        "improved": sum(1 for d in deltas if d <= -2),
        "worsened": sum(1 for d in deltas if d >= 2),
        "n_money": len(money),
        "r": round(pearson([p["delta"] for p in money],
                           [math.log1p(p["pc"]) for p in money]), 3),
        "slope": round(slope, 3),
        "intercept": round(my - slope * mx, 2),
        "high": bucket(40, 200),
        "low": bucket(0, 10),
        "half_life": half_life,
    }


def build_payload() -> dict:
    countries = load_csv("mart_country")
    health = {row["metric"]: num(row["value"]) for row in load_csv("mart_portfolio_health")}
    sectors = load_csv("mart_sector")
    regions = load_csv("mart_region")
    priority = load_csv("mart_priority")
    performance = load_csv("mart_portfolio_performance")
    scenario = load_csv("mart_reallocation")[0]
    dq = load_csv("mart_dq")
    robustness = load_csv("mart_robustness")
    convergence = load_csv("mart_convergence")

    rows = []
    for row in countries:
        rows.append(
            {
                "iso3": row["iso3"],
                "name": row["name"],
                "region": row["region"],
                "income": row["income_level"],
                "ops": int(num(row["n_ops"], 0)),
                "commit": round(num(row["total_commitment"], 0)),
                "active_commit": round(num(row["active_commitment"], 0)),
                "pc": num(row["financing_pc"], 0.0),
                "population": round(num(row["population"], 0)),
                "median_years": num(row["median_impl_years"]),
                "need": num(row["sdg_gap_index"]),
                "gap_poverty": num(row["gap_poverty"]),
                "gap_hunger": num(row["gap_hunger"]),
                "gap_water": num(row["gap_water"]),
                "gap_energy": num(row["gap_energy"]),
                "n_ind": int(num(row["n_indicators"], 0)),
                "portfolio_tercile": int(num(row["portfolio_tercile"], 0)),
                "need_tercile": int(num(row["need_tercile"], 0)) or None,
                "complete": int(num(row["need_complete"], 0)),
                "gap": num(row["allocation_gap"]),
                "quadrant": row["quadrant"],
            }
        )

    return {
        "generated": snapshot_date(),
        "countries": rows,
        "health": health,
        "sectors": [
            {
                "sector": s["sector"],
                "ops": int(num(s["n_ops"], 0)),
                "value": round(num(s["total_value"], 0)),
                "share": num(s["value_share"], 0),
            }
            for s in sectors
        ],
        "regions": [
            {
                "region": r["region"],
                "countries": int(num(r["n_countries"], 0)),
                "commit": round(num(r["total_commitment"], 0)),
                "share": num(r["value_share"], 0),
                "mean_need": num(r["mean_need_gap"]),
                "blindspots": int(num(r["n_blindspots"], 0)),
            }
            for r in regions
        ],
        "priority": [
            {
                "name": b["name"],
                "iso3": b["iso3"],
                "region": b["region"],
                "need": num(b["sdg_gap_index"]),
                "pc": num(b["financing_pc"], 0.0),
                "population": round(num(b["population"], 0)),
                "ops": int(num(b["n_ops"], 0)),
                "active_commit": round(num(b["active_commitment"], 0)),
                "gap": num(b["allocation_gap"], 0.0),
                "quadrant": b["quadrant"],
            }
            for b in priority
        ],
        "thresholds": {
            "need": tercile_thresholds([r["need"] for r in rows if r["complete"] == 1]),
            "pc": tercile_thresholds([r["pc"] for r in rows if r["complete"] == 1]),
        },
        "performance": {
            dim: [
                {
                    "bucket": r["bucket"],
                    "ops": int(num(r["n_ops"], 0)),
                    "value": round(num(r["value"], 0)),
                    "share_ops": num(r["share_ops"], 0.0),
                    "share_value": num(r["share_value"], 0.0),
                    "active_share": num(r["active_share"], None),
                }
                for r in performance if r["dimension"] == dim
            ]
            for dim in ("status", "cohort", "duration", "concentration")
        },
        "reallocation": {
            "share": num(scenario["share"], 0.05),
            "pool": round(num(scenario["pool_usd"], 0)),
            "n_donors": int(num(scenario["n_donors"], 0)),
            "n_recipients": int(num(scenario["n_recipients"], 0)),
            "recipient_population": round(num(scenario["recipient_population"], 0)),
            "donor_population": round(num(scenario["donor_population"], 0)),
            "gain_pc": num(scenario["gain_per_person"], 0.0),
            "donor_loss_pc": num(scenario["donor_loss_per_person"], 0.0),
            "total_active": round(num(health.get("active_value_usd"), 0)),
        },
        "dq": {
            "checks": [
                {
                    "check": r["check"],
                    "category": r["category"],
                    "detail": r["detail"],
                    "status": r["status"],
                }
                for r in dq
            ],
            "passed": sum(1 for r in dq if r["status"] == "PASS"),
            "total": len(dq),
        },
        "positive_gap": sum(1 for r in rows if (r["gap"] or 0) > 0),
        "robustness": build_robustness(robustness),
        "convergence": build_convergence(convergence),
        "palette": bivariate_colours(),
        "geometry": simplify_geometry(RAW / "ne_110m_admin_0_countries.json.gz"),
    }


def fmt_usd(value: float) -> str:
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"


def write_site(payload: dict) -> Path:
    SITE.mkdir(parents=True, exist_ok=True)
    total = fmt_usd(payload["health"].get("active_value_usd") or 0)
    html = TEMPLATE.replace("__TOTAL_VALUE__", total)
    html = html.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    path = SITE / "index.html"
    path.write_text(html, encoding="utf-8")
    print(f"  site: {path.relative_to(ROOT)} ({path.stat().st_size / 1024:.0f} KB)")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aid Atlas - development finance delivery against measured need</title>
<style>
  :root{
    --navy:#002244;--navy-2:#0b3a5e;--blue:#006eb6;--amber:#f2a900;
    --ink:#333333;--muted:#6f7377;--rule:#dfe1e3;--hair:#eceef0;
    --band:#f6f7f8;--paper:#ffffff;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  html,body{margin:0;padding:0;background:var(--paper);color:var(--ink)}
  body{font-family:"Open Sans","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
       font-size:15px;line-height:1.67;-webkit-font-smoothing:antialiased}
  a{color:var(--blue);text-decoration:none}
  a:hover{text-decoration:underline}
  .wrap{max-width:1180px;margin:0 auto;padding:0 24px}
  h1,h2,h3{color:var(--navy);font-weight:600;letter-spacing:-.005em}
  h1{font-size:2.55rem;line-height:1.18;margin:0 0 .85rem;max-width:22ch}
  h2{font-size:1.5rem;margin:0 0 .5rem;line-height:1.28}
  h3{font-size:.95rem;margin:1.7rem 0 .3rem;color:var(--navy)}
  p{margin:.6rem 0;max-width:100%}

  /* ---------- header ---------- */
  .topbar{position:sticky;top:0;z-index:30;background:#fff;border-bottom:1px solid var(--rule)}
  .bar{max-width:1180px;margin:0 auto;padding:0 24px;height:64px;display:flex;align-items:center;gap:1.6rem}
  .brand{display:flex;align-items:center;gap:.6rem;text-decoration:none!important}
  .mark{width:24px;height:24px;background:linear-gradient(135deg,var(--navy) 62%,var(--amber) 62%)}
  .brand .t{font-size:.83rem;font-weight:700;letter-spacing:.1em;color:var(--navy);text-transform:uppercase}
  .brand .s{font-size:.75rem;letter-spacing:.16em;color:var(--muted);text-transform:uppercase;
           border-left:1px solid var(--rule);padding-left:.7rem}
  .datalink{margin-left:-1.05rem;font-size:.75rem;letter-spacing:.16em;color:var(--muted);
            text-transform:uppercase;text-decoration:none!important;border-left:1px solid var(--rule);
            padding:2px 0 2px .7rem}
  .datalink:hover{color:var(--navy)}
  nav{display:flex;gap:1.35rem;margin-left:auto}
  nav a{font-size:.73rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
        padding:22px 0;border-bottom:3px solid transparent}
  nav a:hover{color:var(--navy);text-decoration:none;border-bottom-color:#e9ebed}
  nav a.on{color:var(--navy);border-bottom-color:var(--amber)}
  .search{position:relative;width:210px}
  .search input{width:100%;height:34px;border:1px solid var(--rule);background:#fff;
        padding:0 .6rem 0 1.9rem;font:inherit;font-size:.8rem;color:var(--ink)}
  .search input:focus{outline:none;border-color:var(--blue)}
  .search .ico{position:absolute;left:.65rem;top:9px;width:9px;height:9px;
        border:1.5px solid #9aa0a6;border-radius:50%}
  .search .ico::after{content:"";position:absolute;left:8px;top:8px;width:6px;height:1.5px;
        background:#9aa0a6;transform:rotate(45deg);transform-origin:left center}
  .results{position:absolute;left:auto;right:0;top:38px;min-width:252px;background:#fff;border:1px solid var(--rule);
        box-shadow:0 10px 26px rgba(0,34,68,.14);max-height:320px;overflow:auto;display:none;z-index:35}
  .results.on{display:block}
  .results .row{display:flex;align-items:baseline;gap:.45rem;padding:.42rem .62rem .44rem;
        border-bottom:1px solid var(--hair);cursor:pointer}
  .results .row:last-child{border-bottom:0}
  .results .row:hover,.results .row.sel{background:#f4f7f9}
  .results .nm{font-size:.78rem;color:var(--navy);font-weight:600}
  .results .tag{font-size:.58rem;letter-spacing:.08em;text-transform:uppercase;color:#a2701c;
        border:1px solid #e8cf9d;padding:0 .24rem}
  .results .mt{margin-left:auto;font-size:.7rem;color:var(--muted);font-variant-numeric:tabular-nums}
  .results .empty{padding:.55rem .62rem;font-size:.74rem;color:var(--muted)}
  .note.center{text-align:center;max-width:82ch;margin:1rem auto 0}

  /* ---------- hero ---------- */
  .hero{background:var(--navy);color:#fff}
  .hero .in{max-width:1180px;margin:0 auto;padding:3.6rem 24px 3.2rem}
  .kicker{display:flex;align-items:center;gap:.6rem;font-size:.71rem;letter-spacing:.16em;
          text-transform:uppercase;color:#c6d2de;margin-bottom:1.1rem}
  .kicker b{display:block;width:34px;height:3px;background:var(--amber)}
  .hero h1{color:#fff;max-width:min(34ch,100%);font-size:2.6rem;text-wrap:balance}
  .hero h1 .hl{color:var(--amber)}
  .hero .goal{color:#fff;font-size:1.2rem;line-height:1.5;max-width:min(80ch,100%);
              margin:0 0 1rem;padding-left:.85rem;border-left:3px solid var(--amber)}
  .hero .lede{color:#c9d6e2;font-size:1.03rem;max-width:min(82ch,100%);margin:0;
              text-wrap:pretty}
  .hero .lede em{color:#fff;font-style:normal;border-bottom:1px solid rgba(242,169,0,.55)}

  /* ---------- stat strip ---------- */
  .stats{border-bottom:1px solid var(--rule)}
  .stats .in{max-width:1180px;margin:0 auto;padding:0 24px;display:grid;
             grid-template-columns:repeat(4,1fr)}
  .tile{padding:1.5rem 1.4rem 1.45rem;border-right:1px solid var(--hair)}
  .tile:first-child{padding-left:0}
  .tile:last-child{border-right:0}
  .tile .lab{font-size:.68rem;letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}
  .tile .num{font-size:2.05rem;font-weight:600;color:var(--navy);line-height:1.15;margin-top:.32rem;
             font-variant-numeric:tabular-nums}
  .tile .unit{font-size:.74rem;color:var(--muted);margin-top:.18rem}

  /* ---------- sections ---------- */
  section.sec{padding:3.4rem 0 .4rem}
  section,#data{scroll-margin-top:76px}
  .sec-head{display:flex;align-items:flex-start;gap:.9rem;margin-bottom:1.2rem;border-bottom:1px solid var(--rule);
            padding-bottom:.75rem}
  .sec-no{font-size:.68rem;letter-spacing:.14em;color:var(--amber);font-weight:700;padding-top:.55rem}
  .sec-head h2{margin:0}
  .minor{font-size:.79rem;color:var(--muted);max-width:78ch}

  /* ---------- controls ---------- */
  .controls{display:flex;flex-wrap:wrap;gap:.7rem 1.4rem;align-items:center;margin:1.1rem 0 1rem}
  .controls .grp:last-of-type{margin-left:auto}
  .grp{display:flex;align-items:center;gap:.5rem}
  .grp .cap{font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .seg{display:flex;border:1px solid var(--rule);background:#fff}
  .seg button{font:inherit;font-size:.76rem;padding:.4rem .72rem;border:0;background:transparent;
        color:var(--muted);cursor:pointer;border-right:1px solid var(--hair)}
  .seg button:last-child{border-right:0}
  .seg button:hover{background:var(--band);color:var(--navy)}
  .seg button.on{background:var(--navy);color:#fff}

  /* ---------- legend ---------- */
  .legend{display:flex;flex-wrap:wrap;gap:1.6rem;align-items:flex-start;margin:.4rem 0 1rem}
  .legend .cap{font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:.42rem}
  .ramp{height:11px;width:330px}
  .ramp-labels{display:flex;justify-content:space-between;width:330px;margin-top:.3rem;
        font-size:.66rem;color:var(--muted);white-space:nowrap}
  .chips{display:flex;flex-wrap:wrap;gap:.55rem 1rem}
  .chip{display:flex;align-items:center;gap:.38rem;font-size:.72rem;color:var(--ink)}
  .chip i{width:13px;height:13px;display:block;border:1px solid rgba(0,0,0,.08)}

  /* ---------- cards ---------- */
  .card{background:#fff;border:1px solid var(--rule)}
  .mapwrap{position:relative}
  svg{display:block;width:100%;height:auto}
  .country{stroke:#fff;stroke-width:.6px;cursor:pointer}
  #tip,#ctip{background:#fff;border:1px solid var(--rule);
    box-shadow:0 8px 22px rgba(0,34,68,.13);padding:.6rem .75rem;font-size:.76rem;min-width:196px;
    opacity:0;transition:opacity .12s;line-height:1.45;z-index:20}
  #tip{position:absolute;pointer-events:none}
  #ctip{position:fixed;z-index:40;pointer-events:none;transition:none}
  #tip .n,#ctip .n{font-weight:600;font-size:.88rem;color:var(--navy)}
  #tip .r,#ctip .r{color:var(--muted);font-size:.7rem;margin-bottom:.35rem}
  #tip dl,#ctip dl{display:grid;grid-template-columns:auto auto;gap:.14rem .7rem;margin:0}
  #tip dt,#ctip dt{color:var(--muted)}
  #tip dd,#ctip dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
  table.data tbody tr.hit td{background:#fdf3dd}
  .scatterwrap{border:1px solid var(--rule);margin-top:.6rem}

  /* ---------- tables ---------- */
  table.data{width:100%;border-collapse:collapse;font-size:.82rem;margin-top:.2rem;
             border-top:2px solid var(--navy)}
  table.data thead th{text-align:left;font-weight:600;font-size:.66rem;text-transform:uppercase;
    letter-spacing:.09em;color:var(--navy);background:var(--band);
    padding:.55rem .6rem;border-bottom:1px solid var(--rule)}
  table.data td{padding:.48rem .6rem;border-bottom:1px solid var(--hair);font-variant-numeric:tabular-nums}
  table.data tbody tr:hover td{background:#fafbfc}
  table.data td:first-child{color:var(--navy)}
  .pbar{height:6px;background:#e8eaec;position:relative}
  .pbar span{position:absolute;left:0;top:0;bottom:0;background:var(--blue)}
  .two{display:grid;grid-template-columns:1.05fr .95fr;gap:2.6rem;align-items:start}
  .steps{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--rule);
         border:1px solid var(--rule);margin:1.1rem 0 1.9rem}
  .steps>div{background:#fff;padding:.8rem .75rem .9rem}
  .steps .n{font-size:.6rem;letter-spacing:.12em;color:var(--amber);font-weight:700}
  .steps b{display:block;font-size:.8rem;color:var(--navy);margin:.2rem 0 .22rem}
  .steps p{font-size:.73rem;color:var(--muted);margin:0;line-height:1.5}
  .three{display:grid;grid-template-columns:repeat(3,1fr);gap:2rem;align-items:start}

  /* ---------- operating profile and scenario ---------- */
  .scenario{display:grid;grid-template-columns:1.1fr .9fr;gap:2.2rem;padding:1.5rem 1.6rem 1.4rem;
            margin-top:2.2rem;border-top:3px solid var(--amber)}
  .scenario h3{margin:.12rem 0 .5rem}
  .slider{width:100%;margin:1.2rem 0 .35rem;accent-color:var(--navy)}
  .slider-labels{display:flex;justify-content:space-between;align-items:baseline;font-size:.7rem;color:var(--muted)}
  .slider-labels b{color:var(--navy);font-weight:600}
  .skpi{display:grid;grid-template-columns:1fr 1fr;gap:1.1rem 1.5rem;align-content:start}
  .skpi .lab{font-size:.64rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .skpi .num{font-size:1.32rem;font-weight:600;color:var(--navy);font-variant-numeric:tabular-nums;
             line-height:1.3}
  .skpi .unit{font-size:.7rem;color:var(--muted)}
  .pill{display:inline-block;font-size:.62rem;letter-spacing:.08em;text-transform:uppercase;
        padding:.1rem .38rem;border:1px solid #cfe0d5;background:#eef4f0;color:#2f5d3f}
  .pill.bad{border-color:#e6cfc7;background:#faf0ed;color:#8a3b22}

  /* ---------- robustness matrix ---------- */
  .matrixwrap{margin:1.15rem 0 0;padding:0;overflow-x:auto}
  .matrix{font-size:.74rem;border-top:3px solid var(--navy);min-width:680px}
  .matrix thead th{padding:.5rem .35rem .45rem;vertical-align:bottom}
  .matrix thead th .sub{display:block;font-weight:400;font-size:.59rem;color:var(--muted);
        letter-spacing:.03em;text-transform:none;margin-top:.12rem}
  .matrix th.n,.matrix td.n{text-align:right}
  .matrix td{padding:.3rem .35rem;border-bottom:1px solid var(--hair);text-align:center;
        font-variant-numeric:tabular-nums}
  .matrix td:first-child{text-align:left;padding-left:.8rem;font-size:.78rem;white-space:nowrap}
  .matrix td.n{text-align:right;padding-right:.8rem;font-weight:600;color:var(--navy)}
  .matrix td .out{color:#b9bec2;font-weight:400}
  .matrix tr.offs td:first-child{color:#6f7377}
  .matrix tr.band td{background:#fbfbfc;border-top:1px solid var(--rule);
        font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
        padding:.5rem .8rem;text-align:left}
  .qcount{color:#a85c10;font-weight:600}

  /* ---------- convergence ---------- */
  .convwrap{border:1px solid var(--rule);margin-top:.7rem;display:grid;
        grid-template-columns:1.22fr .78fr;gap:1.5rem;padding:1rem 1.2rem 1.2rem;align-items:start}
  .convplot svg{display:block;width:100%;height:auto}
  .convwrap .ax{font-size:9.5px;fill:var(--muted);letter-spacing:.03em}
  .convwrap .axl{font-size:10.5px;fill:var(--navy);letter-spacing:.04em}
  .convwrap .lbl{font-size:10px;fill:var(--navy);font-weight:600}
  .convmovers h4{font-size:.64rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);
        margin:.1rem 0 .5rem;font-weight:600}
  .convmovers table.data{font-size:.76rem;margin-top:0}
  .convmovers th,.convmovers td{padding:.34rem .45rem}
  .convmovers .sep td{border-top:1px solid var(--rule);padding-top:.5rem}
  .convmovers .note{text-align:left;margin:.55rem 0 0;font-size:.7rem;max-width:100%}
  .capnote{font-size:.74rem;color:var(--ink);line-height:1.6;margin:.9rem 0 0;
        max-width:100%;border-top:1px solid var(--hair);padding-top:.7rem}

  /* ---------- on-ramp, country file, weights, glossary ---------- */
  .start{background:var(--band,#f7f8f9);border-bottom:1px solid var(--rule)}
  .start .in{max-width:1180px;margin:0 auto;padding:.85rem 24px;display:grid;
        grid-template-columns:repeat(4,1fr);gap:1.4rem}
  .start a{display:flex;gap:.55rem;align-items:flex-start;color:var(--navy);
        border-bottom:1px solid transparent}
  .start a:hover{border-bottom-color:var(--amber);text-decoration:none}
  .start a .n{color:var(--amber);font-weight:700;font-size:.68rem;padding-top:.12rem}
  .start a .t{display:flex;flex-direction:column;gap:.06rem}
  .start a .t b{font-size:.78rem;font-weight:600}
  .start a .t span{color:var(--muted);font-size:.71rem;line-height:1.45}

  .cf{position:fixed;right:1.5rem;bottom:1.5rem;width:min(364px,calc(100vw - 2rem));
        max-height:min(80vh,660px);overflow:auto;background:#fff;border:1px solid var(--rule);
        border-top:3px solid var(--amber);box-shadow:0 16px 44px rgba(0,34,68,.22);z-index:60;
        padding:1.05rem 1.2rem 1.1rem}
  .cf[hidden]{display:none}
  .cf .cf-x{position:absolute;top:.45rem;right:.55rem;border:0;background:none;font-size:1.05rem;
        line-height:1;color:var(--muted);cursor:pointer}
  .cf h4{margin:0 0 .08rem;font-size:1.04rem;color:var(--navy)}
  .cf .meta{font-size:.7rem;color:var(--muted);margin-bottom:.7rem}
  .cf .verdict{font-size:.78rem;line-height:1.52;color:var(--ink);background:#fcfaf3;
        border-left:3px solid var(--amber);padding:.5rem .6rem;margin:0 0 .2rem}
  .cf .verdict.quiet{border-left-color:var(--rule);background:#fbfbfc;color:var(--muted)}
  .cf .lbl{font-size:.61rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);
        margin:.85rem 0 .32rem}
  .cf .barbox{display:grid;grid-template-columns:72px 1fr 42px;gap:.45rem;align-items:center;
        font-size:.72rem;margin:.16rem 0}
  .cf .track{height:7px;background:#eff1f2;position:relative}
  .cf .fill{position:absolute;left:0;top:0;bottom:0;background:#e2a23a}
  .cf .fill.none{background:#d7dbde}
  .cf .val{text-align:right;font-variant-numeric:tabular-nums;color:var(--navy)}
  .cf .kpis{display:grid;grid-template-columns:1fr 1fr;gap:.5rem .8rem;font-size:.75rem}
  .cf .kpis .u{display:block;font-size:.6rem;color:var(--muted);letter-spacing:.07em;
        text-transform:uppercase;margin-bottom:.08rem}
  .cf .kpis b{font-weight:600;color:var(--navy);font-variant-numeric:tabular-nums}
  .cf .chips{display:flex;flex-wrap:wrap;gap:.28rem}
  .cf .chipb{font-size:.63rem;padding:.12rem .38rem;border:1px solid var(--rule);color:var(--muted)}
  .cf .chipb.on{border-color:#e2a23a;background:#fdf6e7;color:#7a5310}
  .cf .drift{font-size:.76rem;line-height:1.55;margin:0}
  .cf .foot{margin-top:.85rem;border-top:1px solid var(--hair);padding-top:.65rem}
  .cf .go{border:1px solid var(--rule);background:#fff;color:var(--navy);font:inherit;
        font-size:.71rem;padding:.34rem .6rem;cursor:pointer}
  .cf .go:hover{border-color:var(--amber)}

  .robtool{display:flex;align-items:center;gap:1.2rem;flex-wrap:wrap;margin:.85rem 0 .1rem;
        font-size:.71rem;color:var(--muted)}
  .robtool label{display:flex;gap:.4rem;align-items:center;cursor:pointer}
  .robtool input{accent-color:var(--navy)}
  .robsort{color:#a85c10}
  .matrix th.scol{cursor:pointer}
  .matrix th.scol.on{color:#a85c10;box-shadow:inset 0 -2px 0 var(--amber)}
  .matrix tbody tr{cursor:pointer}

  .weights{margin-top:1rem;padding:1rem 1.1rem 1.1rem;border-top:3px solid var(--navy)}
  .weights .whead{display:flex;justify-content:space-between;align-items:baseline;gap:1rem;
        flex-wrap:wrap}
  .weights .whead h3{margin:0;font-size:.95rem;color:var(--navy)}
  .weights .reset{border:1px solid var(--rule);background:#fff;font:inherit;font-size:.67rem;
        color:var(--navy);padding:.24rem .5rem;cursor:pointer}
  .weights .reset:hover{border-color:var(--amber)}
  .wsliders{margin:.15rem 0 .9rem}
  .wrow{display:grid;grid-template-columns:78px 1fr 22px;gap:.55rem;align-items:center;
        font-size:.74rem;margin:.18rem 0}
  .wrow input{width:100%;accent-color:var(--navy)}
  .wrow .wv{text-align:right;color:var(--navy);font-variant-numeric:tabular-nums}
  .wout{display:grid;grid-template-columns:1.08fr .92fr;gap:1.6rem;margin-top:.5rem;
        align-items:start}
  .wtable{font-size:.76rem;margin-top:0}
  .wtable th,.wtable td{padding:.3rem .45rem}
  .wtable .mv{font-size:.61rem;letter-spacing:.05em;text-transform:uppercase}
  .wtable .mv.in{color:#a85c10}
  .wtable .mv.out{color:#8a3b22}
  .wtable .mv.same{color:var(--muted)}
  .wout .say{font-size:.76rem;line-height:1.62;text-align:left;max-width:100%;margin:0 0 .7rem}
  .wout .say b{color:var(--navy)}

  .glossary{margin-top:1.7rem;border-top:1px solid var(--rule);padding-top:.85rem}
  .glossary summary{cursor:pointer;font-size:.7rem;letter-spacing:.11em;text-transform:uppercase;
        color:var(--navy);font-weight:600}
  .glossary summary:hover{color:#a85c10}
  .glossary dl{display:grid;grid-template-columns:186px 1fr;gap:.4rem 1.3rem;margin:.85rem 0 0;
        font-size:.78rem}
  .glossary dt{color:var(--navy);font-weight:600}
  .glossary dd{margin:0;line-height:1.55;color:var(--ink)}

  /* ---------- method ---------- */
  .method{display:grid;grid-template-columns:1fr 1fr;gap:2.6rem}
  .note{font-size:.78rem;color:var(--muted);max-width:76ch;text-align:center;margin:.55rem auto 0}
  #qcount{white-space:nowrap;color:#a85c10;font-weight:600}
  .brief li{margin:.5rem 0;max-width:72ch}

  /* ---------- footer ---------- */
  footer{margin-top:4rem;background:var(--navy);color:#b9c6d3}
  footer .in{max-width:1180px;margin:0 auto;padding:2.4rem 24px 2.6rem;display:grid;
             grid-template-columns:1.4fr 1fr 1fr;gap:2.2rem}
  footer h4{color:#fff;font-size:.68rem;letter-spacing:.13em;text-transform:uppercase;
            margin:0 0 .55rem;font-weight:600}
  footer p{font-size:.76rem;margin:.25rem 0;color:#aebccb}
  footer .rule{grid-column:1/-1;border-top:1px solid rgba(255,255,255,.16);padding-top:1rem;
               font-size:.7rem;color:#8fa1b2}
  @media (max-width:900px){
    .stats .in{grid-template-columns:repeat(2,1fr)}
    .tile:nth-child(2){border-right:0}
    .two,.three,.method,.scenario,.steps,.convwrap,footer .in{grid-template-columns:1fr}
    nav{display:none} h1{font-size:1.85rem}
    .start .in{grid-template-columns:1fr 1fr;gap:1rem}
    .cf{right:.6rem;bottom:.6rem;max-height:78vh;overflow:auto}
    .wout{grid-template-columns:1fr;gap:1rem}
  }
</style>
</head>
<body>

<div class="topbar" id="top">
  <div class="bar">
    <a class="brand" href="#top" title="Aid Atlas, top of page"><span class="mark"></span>
      <span class="t">Aid Atlas</span></a>
    <a class="datalink" href="#data" title="Data quality: the checks this page runs">Data</a>
    <nav>
      <a href="#overview" class="on">Overview</a>
      <a href="#countries">Countries</a>
      <a href="#portfolio">Portfolio</a>
      <a href="#method">Method</a>
    </nav>
    <div class="search"><span class="ico"></span>
      <input id="q" type="text" placeholder="Search 217 countries" autocomplete="off"
        aria-label="Search a country" aria-expanded="false">
      <div class="results" id="results" role="listbox"></div>
    </div>
  </div>
</div>

<section class="hero" id="overview">
  <div class="in">
    <div class="kicker"><b></b>Independent analysis &middot; public data only</div>
    <h1>Where development finance is <span class="hl">delivered</span>, and where it is
    <span class="hl">needed</span></h1>
    <p class="goal">It ranks 167 countries by the gap between financing per person and
    measured SDG need.</p>
    <p class="lede">A reproducible pipeline that reads a sovereign development portfolio against four
    official SDG indicators. It asks a management question rather than a mapping question:
    <em>which country portfolios carry more measured need than delivery?</em></p>
  </div>
</section>

<div class="stats">
  <div class="in">
    <div class="tile"><div class="lab">Active portfolio</div>
      <div class="num">__TOTAL_VALUE__</div><div class="unit" id="u-active">-</div></div>
    <div class="tile"><div class="lab">Operations</div>
      <div class="num" id="k-ops">-</div><div class="unit" id="u-ops">-</div></div>
    <div class="tile"><div class="lab">Countries covered</div>
      <div class="num" id="k-countries">-</div><div class="unit" id="u-countries">-</div></div>
    <div class="tile"><div class="lab">Need outruns financing</div>
      <div class="num" id="k-blind">-</div><div class="unit" id="u-need">-</div></div>
  </div>
</div>

<aside class="cf" id="cf" hidden aria-live="polite" aria-label="Country file">
  <button class="cf-x" id="cf-close" aria-label="Close the country file">&times;</button>
  <div id="cf-body"></div>
</aside>

<div class="start">
  <div class="in">
    <a href="#countries"><span class="n">1</span><span class="t"><b>The map</b>
      <span>where need outruns delivery</span></span></a>
    <a href="#robustness"><span class="n">2</span><span class="t"><b>The short list</b>
      <span>25 countries, and whether they hold</span></span></a>
    <a href="#trend"><span class="n">3</span><span class="t"><b>The direction</b>
      <span>is the gap closing?</span></span></a>
    <a href="#method"><span class="n">4</span><span class="t"><b>The method</b>
      <span>seven terms in plain words</span></span></a>
  </div>
</div>

<div class="wrap">
<div id="ctip"></div>

<section class="sec" id="countries">
  <div class="sec-head"><div class="sec-no">01</div>
    <div><h2>Need against delivery</h2></div></div>
  <p>The default view shows the <strong>allocation gap</strong> - a country's percentile rank on
  measured need minus its percentile rank on financing per person. Blue means it is better financed
  than its need rank; amber means it carries more need than financing. Because both ranks are
  size-neutral, a small state and a large one are compared on position, not on the size of their
  economy.</p>

  <div class="controls">
    <div class="grp"><span class="cap">Colour by</span>
      <div class="seg" id="modes">
        <button data-mode="gap" class="on">Allocation gap</button>
        <button data-mode="bivariate">Need &times; portfolio</button>
        <button data-mode="need">Need only</button>
        <button data-mode="portfolio">Portfolio only</button>
      </div>
    </div>
    <div class="grp"><span class="cap">Show</span>
      <div class="seg" id="filters">
        <button data-filter="all" class="on">All countries</button>
        <button data-filter="complete">With 3+ indicators</button>
      </div>
    </div>
  </div>

  <div class="legend" id="legend"></div>

  <div class="card mapwrap">
    <div id="tip"></div>
    <svg id="map" viewBox="0 0 1000 520" role="img" aria-label="World map of portfolio against need"></svg>
  </div>
  <p class="note center">Click a country to open its file: the four gaps, its position, and how it
  ranks under each reading. Grey areas have no polygon at the 1:110m simplification, or no measured
  need; small island states missing from the polygon set are still in the table and in
  <code>data/marts/mart_country.csv</code>.</p>
</section>

<section class="sec">
  <div class="sec-head"><div class="sec-no">02</div>
    <div><h2>The allocation question</h2></div></div>
  <p>Financing per person is on a log scale because it spans five orders of magnitude, from zero
  active operations to five figures per inhabitant. Vertical position is the measured SDG gap. The
  shaded corner is where a portfolio review would ordinarily start: most need, least money per
  person.</p>
  <div class="card scatterwrap"><svg id="scatter" viewBox="0 0 1000 460" role="img"
    aria-label="Scatterplot of need against financing per person"></svg></div>
  <p class="note" id="scattercap">Hover a point for its figures; click one to find it in the short
  list. Points sit at the smallest positive financing value when a country has no active
  operations.</p>
</section>

<section class="sec">
  <div class="sec-head"><div class="sec-no">03</div>
    <div><h2>The short list</h2></div></div>
  <p>Ranked by allocation gap. This is not a recommendation to move money; it is the population a
  portfolio review would examine first, and the columns show why each country is on it.
  <span class="note" id="qcount"></span></p>
  <table class="data" id="blindtable">
    <thead><tr><th>Country</th><th>Region</th><th style="text-align:right">SDG gap</th>
    <th style="text-align:right">Financing / person</th><th style="text-align:right">Allocation gap</th></tr></thead>
    <tbody></tbody>
  </table>
</section>

<section class="sec" id="robustness">
  <div class="sec-head"><div class="sec-no">04</div>
    <div><h2>Does the short list survive a different reading?</h2></div></div>
  <p>The ranking averages four gaps with equal weight, which is one choice among several. This
  runs the same comparison five other ways - drop each indicator in turn, and take the single worst
  gap instead of the mean - over exactly the same countries. A move between columns is therefore a
  move in definition, not in data. <span class="qcount" id="rob-summary"></span></p>
  <div class="robtool">
    <label><input type="checkbox" id="robshow25"> Only the 25 on the published list</label>
    <span class="robsort" id="robsort"></span>
  </div>
  <div class="card matrixwrap">
    <table class="data matrix" id="robusttable">
      <thead><tr><th>Country</th><th class="n">Rank</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <p class="note">Darker cells sit closer to the top of the list. A grey number is a country that
  is still ranked under that reading, just outside the top 25 - it is entering or leaving, not
  missing. Click a column header to re-sort by that reading, and click any row for the country
  file.</p>
  <div class="card weights">
    <div class="whead"><h3>You set the weights</h3>
      <button class="reset" id="wreset">Reset to equal weights</button></div>
    <div class="wout">
      <div>
        <div class="wsliders" id="wsliders"></div>
        <table class="data wtable" id="wtable">
          <thead><tr><th>#</th><th>Country</th><th style="text-align:right">Need</th>
          <th style="text-align:right">$/person</th><th style="text-align:right">Gap</th>
          <th>vs published</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div>
        <p class="say">The published ranking is one reading of four equally weighted gaps. Move
        the sliders and the same arithmetic runs in your browser: the weighted mean of the gaps
        each country reports, percentile ranks on need and financing per person, then the
        difference. Setting one weight to zero reproduces the matching column above.</p>
        <p class="say" id="wnote2"></p>
        <p class="say" id="wdrop"></p>
        <p class="say" style="color:#6f7377">The published column is the equal-weight case and does
        not move; this panel only changes the reading above it, never the files. Click a row for
        the country file.</p>
      </div>
    </div>
  </div>
</section>

<section class="sec" id="trend">
  <div class="sec-head"><div class="sec-no">05</div>
    <div><h2>Is the picture moving?</h2></div></div>
  <p>Every figure above is the latest reading, as if need stood still. Read from 2015, when the
  2030 framework was adopted, the four series show whether the countries carrying the most need
  are catching up. The horizontal axis is the 2015 reading; the vertical axis is what changed
  since, in the same points - downward is improvement. The dashed line is a least-squares fit
  through all 117 countries with a reading in both years.</p>
  <div class="legend" id="convlegend"></div>
  <div class="card convwrap">
    <div class="convplot"><svg id="conv" viewBox="0 0 560 560" role="img"
      aria-label="Starting need against the change since 2015"></svg></div>
    <div class="convmovers">
      <h4>Largest moves, 2015 to latest</h4>
      <table class="data" id="movertable">
        <thead><tr><th>Country</th><th style="text-align:right">Change</th>
        <th style="text-align:right">$ / person</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="note">Need is the change in points of population unserved; money is approved
      from 2015 onward, per person.</div>
      <p class="capnote" id="convcaption"></p>
    </div>
  </div>
</section>

<section class="sec" id="portfolio">
  <div class="sec-head"><div class="sec-no">06</div>
    <div><h2>The portfolio itself</h2></div></div>
  <div class="two">
    <div>
      <h3>Sector concentration</h3>
      <table class="data" id="sectortable">
        <thead><tr><th>Sector</th><th style="width:32%">Share of value</th><th style="text-align:right">%</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="note">Shares are of classified value. About a fifth of the book carries no sector
      code in the source and is excluded from the denominator rather than pooled into an "other" bar.</div>
    </div>
    <div>
      <h3>Regional balance</h3>
      <table class="data" id="regiontable">
        <thead><tr><th>Region</th><th style="text-align:right">Share</th><th style="text-align:right">High need /<br>thin</th></tr></thead>
        <tbody></tbody>
      </table>
      <h3>Portfolio health</h3>
      <table class="data" id="healthtable"><tbody></tbody></table>
    </div>
  </div>
</section>

<section class="sec" id="operating">
  <div class="sec-head"><div class="sec-no">07</div>
    <div><h2>How the book behaves</h2></div></div>
  <p class="minor">The same snapshot read as an operating profile rather than a map: what is still live,
  when the live work was approved, how long operations are planned to run, and how much of the value
  sits in a handful of operations.</p>
  <div class="three">
    <div>
      <h4>Status mix</h4>
      <table class="data" id="statustable">
        <thead><tr><th>Status</th><th style="width:30%">Share of value</th>
        <th style="text-align:right">%</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="note">Pipeline and dropped entries are counted rather than hidden: they are the
      queue a portfolio review inherits.</div>
    </div>
    <div>
      <h4>Planned duration</h4>
      <table class="data" id="durationtable">
        <thead><tr><th>Band</th><th style="width:30%">Share of value</th>
        <th style="text-align:right">%</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="note">Board approval to scheduled closing date. Operations without both dates stay
      in their own bucket instead of being imputed.</div>
    </div>
    <div>
      <h4>Approval cohorts</h4>
      <table class="data" id="cohorttable">
        <thead><tr><th>Cohort</th><th style="text-align:right">Share of value</th>
        <th style="text-align:right">Still live</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="note">Share of each cohort's value that is still active at the snapshot date.</div>
    </div>
  </div>

  <div class="card scenario">
    <div>
      <div class="grp"><span class="cap">Scenario</span></div>
      <h3>What a reallocation would buy</h3>
      <p class="minor">Move a share of live value from the countries already better financed than their
      measured need to the 25 on the short list. The pool is raised pro rata from the donors and paid
      pro rata to population, so the gain per person is identical in every recipient.</p>
      <input class="slider" id="share" type="range" min="0" max="10" step="0.5" value="5"
             aria-label="Share of active value reallocated">
      <div class="slider-labels"><span>0%</span>
        <span><b id="share-out">5% of live value</b></span><span>10%</span></div>
      <p class="note" id="scen-note"></p>
    </div>
    <div class="skpi" id="scen-stats"></div>
  </div>
</section>

<section class="sec" id="method">
  <div class="sec-head"><div class="sec-no">08</div>
    <div><h2>Method, and what this cannot tell you</h2></div></div>
  <h3>How it works</h3>
  <div class="steps">
    <div><span class="n">01</span><b>Source</b>
      <p>Public data only: the project register, four SDG series, and the population and
      income fields that make both readable per person.</p></div>
    <div><span class="n">02</span><b>Snapshot</b>
      <p>Each download is checksummed into <code>data/raw</code> with a manifest, so every
      downstream number can be reproduced without touching the network again.</p></div>
    <div><span class="n">03</span><b>Build</b>
      <p>The register flattened into staging CSVs: one row per operation, one per country
      link, commitments split evenly. Generated on every build, never versioned.</p></div>
    <div><span class="n">04</span><b>Model</b>
      <p>Plain SQL files in filename order, <code>int_*</code> then <code>mart_*</code>. Fifteen
      models produce nine published tables; no mart reads a CSV directly.</p></div>
    <div><span class="n">05</span><b>Publish</b>
      <p>Fourteen assertions over warehouse and marts; a failure exits non-zero and stops the
      render. The site then embeds marts and geometry into one file, only D3 from a CDN.</p></div>
  </div>
  <div class="method">
    <div>
      <h3>How the two layers are built</h3>
      <p><strong>Delivery.</strong> Every operation in the public project register is parsed into
      country links: commitments split evenly where an operation covers several countries, planned
      duration from board approval to closing date. Country aggregates give operation count, total and
      active commitment, and median duration.</p>
      <p><strong>Need.</strong> Four SDG series with a stated 2030 target - poverty (1.1.1),
      undernourishment (2.1.1), safely managed drinking water (6.1.1), electricity access (7.1.1).
      Each becomes percentage points of population not yet served and is averaged. Countries with fewer
      than three of the four are excluded from the ranking rather than assumed to be low-need.</p>
      <h3>What a next iteration adds</h3>
      <p>Disbursement ratios from the same register and a process view of approval-to-first-disbursement
      latency - the metric that turns a portfolio map into a business process review.</p>
    </div>
    <div class="brief">
      <h3>Three things this does not do</h3>
      <ol>
        <li>It does not attribute outcomes. A thin portfolio and a large gap can both be symptoms of
        state capacity, access constraints or donor division of labour.</li>
        <li>Commitment is not disbursement. Value here is approved financing, not money that reached a
        country.</li>
        <li>Ranks are relative, not judged against a sufficiency standard. A country in the top
        tercile can still be under-financed for its population.</li>
      </ol>
    </div>
  </div>

  <h3 id="data" style="margin-top:2.4rem">Data quality</h3>
  <p class="minor">Every check below runs in <code>pipeline/dq.py</code> between the build and the
  render, and the build stops if one of them fails. <span id="dq-summary"></span></p>
  <table class="data" id="dqtable">
    <thead><tr><th>Check</th><th>What the number says</th><th style="text-align:right">Status</th></tr></thead>
    <tbody></tbody>
  </table>

  <details class="glossary">
    <summary>Seven terms, in plain words</summary>
    <dl>
      <dt>Need index</dt>
      <dd>The share of a country's population without minimum services, averaged over four UN
      indicators: poverty, hunger, safe drinking water and electricity. 0 means everyone covered;
      100 means nobody.</dd>
      <dt>Financing per person</dt>
      <dd>Everything ever committed to the country, divided by its population. It is approval, not
      money that has reached anyone.</dd>
      <dt>Percentile rank</dt>
      <dd>The country's position among the 167 ranked countries, from 0 (lowest) to 1 (highest).
      It compares position, not size, so a small state is not penalised for being small.</dd>
      <dt>Allocation gap</dt>
      <dd>Need rank minus financing rank. Positive means more measured need than money; negative
      means the opposite. It is a triage signal, not proof of misallocation.</dd>
      <dt>Short list</dt>
      <dd>The 25 countries with the largest positive gap: the population a portfolio review would
      look at first, not a recommendation to move money.</dd>
      <dt>Reading</dt>
      <dd>One way of weighting the four indicators. Six readings are published, including one that
      drops each indicator and one that scores a country on its single worst gap.</dd>
      <dt>Stakeholder view</dt>
      <dd>The country file: click any country on the map, in a table, in the matrix or on the drift
      panel, and the same six numbers, four bars, six ranks and its change since 2015 open together.</dd>
    </dl>
  </details>
</section>

</div>

<footer>
  <div class="in">
    <div>
      <h4>Sources</h4>
      <p>World Bank projects API &middot; UN Statistics Division SDG indicator database</p>
      <p>Natural Earth 1:110m boundaries &middot; ISO 3166 / UN M49 reference table</p>
    </div>
    <div>
      <h4>Method</h4>
      <p>Rank on financing per person, not absolute value. Percentile ranks rather than terciles,
      so tie groups are not split across bins.</p>
    </div>
    <div>
      <h4>Status</h4>
      <p>Snapshot built <span id="gen"></span>. Independent work; figures are not reviewed or
      endorsed by any institution named in the source data.</p>
    </div>
    <div class="rule">Aid Atlas &middot; reproducible analysis of public development data &middot; MIT licence</div>
  </div>
</footer>

<script src="https://fastly.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script>
const DATA = __PAYLOAD__;
document.getElementById('gen').textContent = DATA.generated;

const HEALTH = DATA.health;
const fmt = d3.format(',');
document.getElementById('k-ops').textContent = fmt(HEALTH.total_operations);
document.getElementById('k-countries').textContent = fmt(HEALTH.countries_with_portfolio);
document.getElementById('k-blind').textContent = DATA.positive_gap;
document.getElementById('u-active').textContent =
  'of $' + (HEALTH.total_value_usd / 1e12).toFixed(2) + 'tn committed';
document.getElementById('u-ops').textContent =
  (HEALTH.share_operations_active * 100).toFixed(1) + '% still active';
document.getElementById('u-countries').textContent =
  HEALTH.countries_with_need_data + ' with need data';
document.getElementById('u-need').textContent =
  'of ' + HEALTH.countries_with_need_data + ' ranked countries';

const byIso = new Map(DATA.countries.map(d => [d.iso3, d]));
const fmtUSD = v => v >= 1e9 ? '$' + (v/1e9).toFixed(1) + 'B'
                : v >= 1e6 ? '$' + Math.round(v/1e6) + 'M'
                : '$' + d3.format(',.0f')(v || 0);

const GAP_SCALE = d3.scaleLinear()
  .domain([-0.65, -0.3, -0.08, 0.08, 0.3, 0.65])
  .range(['#0b4a75', '#5f96bd', '#dfe6ea', '#fbfbfc', '#efb64a', '#a85c10'])
  .clamp(true);
const PORT_RAMP = ['#dbe8f1', '#6ea3c6', '#005f93'];
const NEED_RAMP = ['#fdf0d6', '#f0bf5e', '#c9791f'];
const NO_DATA = '#e9ecee';
let mode = 'gap';
let filter = 'all';

function fillFor(d){
  if (!d) return NO_DATA;
  if (filter === 'complete' && !d.complete) return '#f1f3f4';
  if (mode === 'gap'){
    if (!d.complete || d.gap === null || d.gap === undefined) return NO_DATA;
    return GAP_SCALE(d.gap);
  }
  if (mode === 'need'){
    if (!d.need) return NO_DATA;
    return NEED_RAMP[Math.max(0, Math.min(2, (d.need_tercile || 1) - 1))];
  }
  if (mode === 'portfolio'){
    return PORT_RAMP[Math.max(0, Math.min(2, (d.portfolio_tercile || 1) - 1))];
  }
  if (!d.complete) return NO_DATA;
  return DATA.palette['' + d.portfolio_tercile + d.need_tercile];
}

const width = 1000, height = 520;
const svg = d3.select('#map');
const projection = d3.geoNaturalEarth1().fitExtent([[8, 12], [width - 8, height - 14]], {type:'Sphere'});
const path = d3.geoPath(projection);

svg.append('path').datum({type:'Sphere'}).attr('d', path).attr('fill', '#f7f8f9').attr('stroke', 'none');

const countries = svg.selectAll('path.country')
  .data(DATA.geometry.features)
  .join('path')
  .attr('class', 'country')
  .attr('d', path)
  .attr('fill', f => fillFor(byIso.get(f.properties.iso3)))
  .on('mousemove', (event, f) => showTip(event, f))
  .on('mouseleave', hideTip);

const tip = d3.select('#tip');
function showTip(event, feature){
  const d = byIso.get(feature.properties.iso3);
  const name = (d && d.name) || feature.properties.name;
  if (!d){
    tip.style('opacity', 1).html('<div class="n">' + name + '</div>' +
      '<div class="r">not in this portfolio snapshot</div>');
  } else {
    const rows = [
      ['SDG gap', d.need ? d.need.toFixed(1) + ' pts' : 'no data'],
      ['Financing / person', d.pc ? '$' + d.pc.toFixed(1) : 'no active ops'],
      ['Active commitment', d.active_commit ? fmtUSD(d.active_commit) : '-'],
      ['Operations', fmt(d.ops)],
      ['Median duration', d.median_years ? d.median_years.toFixed(1) + ' yrs' : '-'],
      ['Quadrant', d.quadrant || '-']
    ];
    tip.style('opacity', 1).html('<div class="n">' + name + '</div>' +
      '<div class="r">' + (d.region || '') + ' &middot; ' + (d.income || '') + '</div>' +
      '<dl>' + rows.map(r => '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>').join('') + '</dl>');
  }
  const box = document.querySelector('.mapwrap').getBoundingClientRect();
  let x = event.clientX - box.left + 14, y = event.clientY - box.top + 14;
  if (x > box.width - 230) x -= 242;
  tip.style('left', x + 'px').style('top', y + 'px');
}
function hideTip(){ tip.style('opacity', 0); }

function recolour(){
  countries.attr('fill', f => fillFor(byIso.get(f.properties.iso3)));
  renderLegend();
}

function renderLegend(){
  const el = document.getElementById('legend');
  const cap = t => '<div class="cap">' + t + '</div>';
  if (mode === 'gap'){
    el.innerHTML =
      '<div>' + cap('Allocation gap &nbsp;&minus;0.65 to +0.65') +
      '<div class="ramp" style="background:linear-gradient(90deg,' +
      ['#0b4a75','#5f96bd','#dfe6ea','#fbfbfc','#efb64a','#a85c10'].join(',') + ')"></div>' +
      '<div class="ramp-labels"><span>better financed than need</span>' +
      '<span>need outruns financing</span></div></div>' +
      '<div class="chips" style="align-items:flex-end">' +
      '<div class="note" style="max-width:32ch;margin:0;text-align:left">Rank-based, so every country is compared ' +
      'on position rather than on the size of its portfolio. Grey = no measured need.</div></div>';
    return;
  }
  if (mode !== 'bivariate'){
    const ramp = mode === 'need' ? NEED_RAMP : PORT_RAMP;
    el.innerHTML = '<div>' + cap(mode === 'need' ? 'Unmet SDG need' : 'Portfolio size') +
      '<div style="display:flex">' + ramp.map(c =>
        '<div style="width:83px;height:14px;background:' + c + '"></div>').join('') + '</div>' +
      '<div class="ramp-labels" style="width:249px"><span>low</span><span>high</span>' +
      '</div></div>';
    return;
  }
  let rowsHtml = '';
  for (let need = 3; need >= 1; need--){
    rowsHtml += '<tr>';
    for (let port = 1; port <= 3; port++){
      rowsHtml += '<td style="padding:0;border:1px solid #fff;width:26px;height:20px;background:' +
        DATA.palette['' + port + need] + '"></td>';
    }
    rowsHtml += '</tr>';
  }
  el.innerHTML = '<div>' + cap('Need &uarr; &nbsp; portfolio &rarr;') +
    '<table style="border-collapse:collapse"><tbody>' + rowsHtml + '</tbody></table>' +
    '<div class="ramp-labels" style="width:78px"><span>thin</span><span>large</span></div></div>' +
    '<div class="note" style="max-width:34ch;margin:0;text-align:left">Amber cells are the high-need, ' +
    'thin-portfolio corner; dark slate is high need with a large book, the case a quadrant view ' +
    'hides.</div>';
}

const navLinks = [...document.querySelectorAll('nav a')];
const navSections = navLinks
  .map(a => document.getElementById(a.getAttribute('href').slice(1)))
  .filter(Boolean);

function highlightNav(id){
  navLinks.forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + id));
}
navLinks.forEach(a => a.addEventListener('click', () => {
  highlightNav(a.getAttribute('href').slice(1));
}));
function syncNav(){
  let current = navSections[0].id;
  for (const sec of navSections){
    if (sec.getBoundingClientRect().top <= 140) current = sec.id;
  }
  highlightNav(current);
}
window.addEventListener('scroll', syncNav, {passive: true});
window.addEventListener('resize', syncNav);
syncNav();

document.querySelectorAll('#modes button').forEach(btn => {
  btn.addEventListener('click', () => {
    mode = btn.dataset.mode;
    document.querySelectorAll('#modes button').forEach(b => b.classList.toggle('on', b === btn));
    recolour();
  });
});
document.querySelectorAll('#filters button').forEach(btn => {
  btn.addEventListener('click', () => {
    filter = btn.dataset.filter;
    document.querySelectorAll('#filters button').forEach(b => b.classList.toggle('on', b === btn));
    recolour();
  });
});

(function scatter(){
  const el = d3.select('#scatter');
  const m = {t: 26, r: 30, b: 52, l: 62};
  const W = 1000 - m.l - m.r, H = 460 - m.t - m.b;
  const pts = DATA.countries.filter(d => d.complete && d.need);
  const positive = pts.map(d => d.pc).filter(v => v > 0);
  const floor = d3.min(positive) || 1;
  const ceil = d3.max(pts, d => d.pc) || 1;
  const x = d3.scaleLog().domain([floor, Math.max(ceil, floor * 10)]).range([0, W]).nice();
  const y = d3.scaleLinear().domain([0, d3.max(pts, d => d.need)]).range([H, 0]).nice();
  const g = el.append('g').attr('transform', 'translate(' + m.l + ',' + m.t + ')');

  const nx = Math.max(floor, DATA.thresholds.pc[0]);
  g.append('rect').attr('x', 0).attr('y', 0)
    .attr('width', Math.max(1, Math.min(W, x(nx))))
    .attr('height', Math.max(0, y(DATA.thresholds.need[1])))
    .attr('fill', '#fdf3dd').attr('opacity', .85);
  g.append('text').attr('x', 9).attr('y', 17).attr('font-size', 9.5)
    .attr('letter-spacing', '.08em').attr('fill', '#a2701c')
    .text('HIGH NEED / THIN PORTFOLIO');

  g.append('g').attr('transform', 'translate(0,' + H + ')')
    .call(d3.axisBottom(x).ticks(6, '.0s')).attr('font-size', 11)
    .attr('color', '#6f7377');
  g.append('g').call(d3.axisLeft(y).ticks(6)).attr('font-size', 11).attr('color', '#6f7377');
  g.append('g').append('line').attr('x1', 0).attr('x2', W).attr('y1', H).attr('y2', H)
    .attr('stroke', '#dfe1e3');

  g.append('text').attr('x', W/2).attr('y', H + 42).attr('text-anchor', 'middle')
    .attr('font-size', 11.5).attr('fill', '#6f7377').text('Financing per person, USD (log scale)');
  g.append('text').attr('transform', 'rotate(-90)').attr('x', -H/2).attr('y', -44)
    .attr('text-anchor', 'middle').attr('font-size', 11.5).attr('fill', '#6f7377')
    .text('Unmet SDG need (index 0-100)');

  const rad = d => d.quadrant === 'high need / thin portfolio' ? 5 : 3.2;
  const ctip = document.getElementById('ctip');
  const cardHtml = d => {
    const rows = [
      ['Need index', d.need ? d.need.toFixed(1) + ' / 100' : 'no data'],
      ['Financing / person', d.pc ? '$' + d.pc.toFixed(1) : 'no active operations'],
      ['Allocation gap', d.gap == null ? 'not ranked' :
        (d.gap > 0 ? '+' : '') + d.gap.toFixed(2)],
      ['Operations', fmt(d.ops)]
    ];
    return '<div class="n">' + d.name + '</div>' +
      '<div class="r">' + (d.region || '') + (d.income ? ' &middot; ' + d.income : '') + '</div>' +
      '<dl>' + rows.map(r => '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>').join('') + '</dl>';
  };
  const placeCard = event => {
    const pad = 16, w = ctip.offsetWidth, h = ctip.offsetHeight;
    let cx = event.clientX + pad, cy = event.clientY + pad;
    if (cx + w > window.innerWidth - 8) cx = event.clientX - w - pad;
    if (cy + h > window.innerHeight - 8) cy = event.clientY - h - pad;
    ctip.style.left = cx + 'px';
    ctip.style.top = cy + 'px';
  };
  g.selectAll('circle').data(pts).join('circle')
    .attr('cx', d => x(Math.max(d.pc, floor)))
    .attr('cy', d => y(d.need))
    .attr('r', rad)
    .attr('fill', d => d.quadrant === 'high need / thin portfolio' ? '#c9791f' : '#004a78')
    .attr('stroke', '#ffffff')
    .attr('stroke-width', .8)
    .attr('opacity', .9)
    .style('cursor', 'pointer')
    .on('mouseenter', (event, d) => {
      d3.select(event.currentTarget).attr('r', rad(d) + 2.2).attr('opacity', 1);
      ctip.innerHTML = cardHtml(d);
      ctip.style.opacity = '1';
      placeCard(event);
    })
    .on('mousemove', (event) => placeCard(event))
    .on('mouseleave', (event, d) => {
      d3.select(event.currentTarget).attr('r', rad(d)).attr('opacity', .9);
      ctip.style.opacity = '0';
    })
    .on('click', (event, d) => {
      ctip.style.opacity = '0';
      document.getElementById('scattercap').innerHTML = SHORT.has(d.name)
        ? '<strong>' + d.name + '</strong> is on the short list; its row is highlighted in section 03.'
        : '<strong>' + d.name + '</strong> is not on the 25-country short list &mdash; need ' +
          d.need.toFixed(1) + ', ' +
          (d.pc ? '$' + d.pc.toFixed(0) + ' per person' : 'no active operations') +
          (d.gap == null ? '.' : ', gap ' + (d.gap > 0 ? '+' : '') + d.gap.toFixed(2) + '.');
      playSearch(d.name);
    });

  const labelled = pts.filter(d => d.quadrant === 'high need / thin portfolio')
    .sort((a, b) => b.need - a.need).slice(0, 9);
  const centres = pts.map(d => [x(Math.max(d.pc, floor)), y(d.need)]);
  const boxes = [];
  g.selectAll('text.lbl').data(labelled).join('text')
    .attr('class', 'lbl')
    .attr('font-size', 9.5).attr('fill', '#002244')
    .text(d => d.iso3)
    .each(function(d){
      const px = x(Math.max(d.pc, floor)), py = y(d.need);
      const w = d.iso3.length * 6.9 + 2, h = 10;
      const others = centres.filter(([cx, cy]) => Math.abs(cx - px) > 1 || Math.abs(cy - py) > 1);
      const fits = (bx, by) => {
        const top = by - h;
        if (bx < 3 || bx + w > W - 3 || top < 0 || by > H) return false;
        for (const b of boxes){
          if (bx < b[0] + b[2] && b[0] < bx + w && top < b[1] + b[3] && b[1] < top + h) return false;
        }
        return !others.some(([cx, cy]) =>
          cx > bx - 3 && cx < bx + w + 3 && cy > top - 3 && cy < top + h + 3);
      };
      let placed = false;
      for (const dy of [0, -12, 12, -24, 24, -36, 36, -48, 48]){
        for (const dx of [7, -w - 7]){
          const bx = px + dx, by = py + dy;
          if (fits(bx, by)){
            d3.select(this).attr('x', bx).attr('y', by);
            boxes.push([bx, by - h, w, h]);
            placed = true;
            break;
          }
        }
        if (placed) break;
      }
      if (!placed) d3.select(this).attr('x', px + 7).attr('y', Math.min(H - 2, py - 6));
    });
})();

const tb = document.querySelector('#blindtable tbody');
DATA.priority.forEach((d, i) => {
  const tr = document.createElement('tr');
  tr.dataset.name = d.name;
  tr.dataset.iso = d.iso3;
  tr.style.cursor = 'pointer';
  const pc = d.pc > 0 ? '$' + (d.pc < 10 ? d.pc.toFixed(2) : d.pc.toFixed(0)) : 'none active';
  tr.innerHTML = '<td>' + d.name + '</td><td>' + (d.region || '') + '</td>' +
    '<td style="text-align:right">' + d.need.toFixed(1) + '</td>' +
    '<td style="text-align:right">' + pc + '</td>' +
    '<td style="text-align:right;color:' + (d.gap > 0 ? '#a2701c' : '#005f93') + '">' +
    (d.gap > 0 ? '+' : '') + d.gap.toFixed(2) + '</td>';
  tb.appendChild(tr);
});

const q = document.getElementById('q');
const qcount = document.getElementById('qcount');
const results = document.getElementById('results');
const ALL = DATA.countries.slice().sort((a, b) => a.name.localeCompare(b.name));
const SHORT = new Map(DATA.priority.map(d => [d.name, d]));

function filterRows(term){
  let hits = 0;
  [...tb.querySelectorAll('tr')].forEach(tr => {
    const hit = !term || tr.dataset.name.toLowerCase().includes(term);
    tr.style.display = hit ? '' : 'none';
    if (hit) hits++;
  });
  return hits;
}

function focusRow(name){
  const row = [...tb.querySelectorAll('tr')].find(tr => tr.dataset.name === name);
  if (!row) return false;
  row.scrollIntoView({block: 'center', behavior: 'smooth'});
  row.classList.add('hit');
  setTimeout(() => row.classList.remove('hit'), 2600);
  return true;
}

function showMatches(term){
  if (!term){ closeMatches(); return; }
  const hits = ALL.filter(d => d.name.toLowerCase().includes(term)).slice(0, 8);
  results.innerHTML = hits.length ? hits.map(d =>
    '<div class="row" data-name="' + d.name + '">' +
    '<span class="nm">' + d.name + '</span>' +
    (SHORT.has(d.name) ? '<span class="tag">short list</span>' : '') +
    '<span class="mt">' + (d.gap == null ? 'not ranked' :
      (d.gap > 0 ? '+' : '') + d.gap.toFixed(2)) + '</span></div>').join('')
    : '<div class="empty">No country matches that name</div>';
  results.classList.add('on');
  q.setAttribute('aria-expanded', 'true');
}

function closeMatches(){
  results.classList.remove('on');
  q.setAttribute('aria-expanded', 'false');
}

function playSearch(name){
  q.value = name;
  const hits = filterRows(name.toLowerCase());
  closeMatches();
  if (focusRow(name)){
    qcount.textContent = hits + (hits === 1 ? ' match' : ' matches');
  } else {
    qcount.textContent = name + ' is not on the 25-country short list';
  }
}

q.addEventListener('input', () => {
  const term = q.value.trim().toLowerCase();
  const hits = filterRows(term);
  qcount.textContent = term ? hits + (hits === 1 ? ' match' : ' matches') : '';
  showMatches(term);
});
results.addEventListener('mousedown', e => {
  const row = e.target.closest('.row');
  if (!row) return;
  e.preventDefault();
  playSearch(row.dataset.name);
});
q.addEventListener('keydown', e => {
  if (e.key === 'Enter'){
    e.preventDefault();
    const first = results.querySelector('.row');
    if (first) playSearch(first.dataset.name);
  } else if (e.key === 'Escape'){
    q.value = '';
    filterRows('');
    qcount.textContent = '';
    closeMatches();
  }
});
q.addEventListener('blur', () => setTimeout(closeMatches, 150));
document.addEventListener('click', e => {
  if (!e.target.closest('.search')) closeMatches();
});

const st = document.querySelector('#sectortable tbody');
DATA.sectors.slice(0, 9).forEach(d => {
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>' + d.sector + '</td>' +
    '<td><div class="pbar"><span style="width:' + Math.min(100, d.share * 100).toFixed(1) + '%"></span></div></td>' +
    '<td style="text-align:right">' + (d.share * 100).toFixed(1) + '%</td>';
  st.appendChild(tr);
});

const rt = document.querySelector('#regiontable tbody');
DATA.regions.forEach(d => {
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>' + d.region + '</td>' +
    '<td style="text-align:right">' + (d.share * 100).toFixed(1) + '%</td>' +
    '<td style="text-align:right">' + d.blindspots + '</td>';
  rt.appendChild(tr);
});

const ht = document.querySelector('#healthtable tbody');
[['share_operations_active','Operations active'],
 ['share_value_active','Value active'],
 ['mean_implementation_years','Mean duration (yrs)'],
 ['share_operations_over_10y','Share over 10 yrs'],
 ['sector_hhi','Sector concentration (HHI)'],
 ['share_value_top10_operations','Value in top 10 ops']
].forEach(([k, label]) => {
  const v = HEALTH[k];
  if (v === undefined || v === null) return;
  const isRatio = k.startsWith('share');
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>' + label + '</td><td style="text-align:right">' +
    (isRatio ? (v * 100).toFixed(0) + '%' : v.toFixed(2)) + '</td>';
  ht.appendChild(tr);
});

/* ---------- operating profile ---------- */
(function operatingProfile(){
  const dims = DATA.performance;
  const bar = d => '<td><div class="pbar"><span style="width:' +
    Math.min(100, (d.share_value || 0) * 100).toFixed(1) + '%"></span></div></td>';
  const pct = d => (d.share_value * 100).toFixed(1) + '%';
  function fill(sel, dim, row){
    const el = document.querySelector(sel);
    (dims[dim] || []).forEach(d => {
      const tr = document.createElement('tr');
      tr.innerHTML = row(d);
      el.appendChild(tr);
    });
  }
  fill('#statustable tbody', 'status', d =>
    '<td>' + d.bucket + '</td>' + bar(d) +
    '<td style="text-align:right">' + pct(d) + '</td>');
  fill('#durationtable tbody', 'duration', d =>
    '<td>' + d.bucket + '</td>' + bar(d) +
    '<td style="text-align:right">' + pct(d) + '</td>');
  fill('#cohorttable tbody', 'cohort', d =>
    '<td>' + d.bucket + '</td>' +
    '<td style="text-align:right">' + pct(d) + '</td>' +
    '<td style="text-align:right">' +
    (d.active_share === null ? '-' : (d.active_share * 100).toFixed(0) + '%') + '</td>');
})();

/* ---------- reallocation scenario ---------- */
(function reallocation(){
  const s = DATA.reallocation;
  const slider = document.getElementById('share');
  const out = document.getElementById('share-out');
  const stats = document.getElementById('scen-stats');
  const note = document.getElementById('scen-note');
  function draw(share){
    const pool = share / 100 * s.total_active;
    const gain = pool / s.recipient_population;
    const loss = pool / s.donor_population;
    out.textContent = share + '% of live value';
    stats.innerHTML =
      '<div><div class="lab">Value moved</div><div class="num">' + fmtUSD(pool) + '</div>' +
      '<div class="unit">of ' + fmtUSD(s.total_active) + ' still live</div></div>' +
      '<div><div class="lab">Gain per person</div><div class="num">$' + gain.toFixed(2) + '</div>' +
      '<div class="unit">in the ' + s.n_recipients + ' short-listed countries</div></div>' +
      '<div><div class="lab">Cost per person</div><div class="num">$' + loss.toFixed(2) + '</div>' +
      '<div class="unit">across the ' + s.n_donors + ' donor countries</div></div>' +
      '<div><div class="lab">People covered</div><div class="num">' +
      (s.recipient_population / 1e6).toFixed(0) + 'm</div>' +
      '<div class="unit">recipient population</div></div>';
    note.textContent = 'The memo and the README quote the 5% case: ' + fmtUSD(s.pool) +
      ' moved, $' + s.gain_pc.toFixed(2) + ' per person. Arithmetic on this snapshot, not a proposal.';
  }
  slider.addEventListener('input', () => draw(parseFloat(slider.value)));
  draw(parseFloat(slider.value));
})();

/* ---------- data quality ---------- */
(function dataQuality(){
  const d = DATA.dq;
  const tb = document.querySelector('#dqtable tbody');
  d.checks.forEach(c => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + c.check + '</td><td>' + c.detail + '</td>' +
      '<td style="text-align:right"><span class="pill' +
      (c.status === 'PASS' ? '' : ' bad') + '">' + c.status + '</span></td>';
    tb.appendChild(tr);
  });
  document.getElementById('dq-summary').textContent =
    d.passed + ' of ' + d.total + ' checks pass on the committed snapshot.';
})();

/* ---------- robustness matrix ---------- */
(function robustness(){
  const r = DATA.robustness;
  const head = document.querySelector('#robusttable thead tr');
  r.columns.forEach(function(col, i){
    const th = document.createElement('th');
    th.className = 'scol';
    th.dataset.col = i;
    th.title = 'Sort the matrix by this reading';
    th.innerHTML = col.label + '<span class="sub">' + col.kept + ' of 25 kept</span>';
    head.appendChild(th);
  });

  // Two stops rather than one smooth ramp: almost all of the signal sits in
  // ranks 1-12, and a linear ramp spends most of its range on ranks nobody
  // reads twice.
  const heat = d3.scaleLinear().domain([1, 11, 25]).range(['#c07c00', '#e7b354', '#fdf8ec']);
  const dark = hex => {
    const c = d3.rgb(hex);
    return (0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b) / 255 < 0.6;
  };
  const tb = document.querySelector('#robusttable tbody');
  const hint = document.getElementById('robsort');
  let sortCol = null;
  let only25 = false;

  function draw(){
    tb.innerHTML = '';
    let rows = r.rows.slice();
    if (only25) rows = rows.filter(x => x.baseline !== null);
    if (sortCol !== null){
      rows.sort((a, b) => (a.ranks[sortCol] === null ? 999 : a.ranks[sortCol]) -
                          (b.ranks[sortCol] === null ? 999 : b.ranks[sortCol]));
    }
    let banded = false;
    rows.forEach(function(row){
      // The band only makes sense in the published order; under a sort the
      // table is a ranking of its own and the boundary is misleading.
      if (sortCol === null && row.baseline === null && !banded){
        banded = true;
        const band = document.createElement('tr');
        band.className = 'band';
        band.innerHTML = '<td colspan="8">Outside the short list - entering under another reading</td>';
        tb.appendChild(band);
      }
      const tr = document.createElement('tr');
      if (row.baseline === null) tr.className = 'offs';
      const name = document.createElement('td');
      name.textContent = row.name;
      tr.appendChild(name);
      const base = document.createElement('td');
      base.className = 'n';
      base.textContent = row.baseline === null ? '' : row.baseline;
      tr.appendChild(base);
      row.ranks.forEach(function(rank, i){
        const col = r.columns[i];
        const td = document.createElement('td');
        if (rank !== null && rank <= 25){
          const bg = heat(rank);
          td.style.background = bg;
          td.style.color = dark(bg) ? '#ffffff' : '#4a3505';
          td.textContent = rank;
        } else {
          td.innerHTML = '<span class="out">' + (rank === null ? '-' : rank) + '</span>';
        }
        let tip = col.label + ': ' + (rank === null ? 'not ranked' : 'rank ' + rank) + '.';
        if (row.baseline !== null && rank !== null){
          const shift = row.baseline - rank;
          tip += ' Published rank ' + row.baseline +
            (shift === 0 ? ', unchanged.' : ', ' + Math.abs(shift) +
             (shift > 0 ? ' places higher' : ' places lower') + '.');
        } else if (row.baseline === null && rank !== null && rank <= 25){
          tip += ' Not on the published list; it enters under this reading.';
        }
        td.title = tip;
        tr.appendChild(td);
      });
      tr.addEventListener('click', () => openCountry(row.iso3));
      tb.appendChild(tr);
    });
  }

  head.querySelectorAll('th.scol').forEach(function(th){
    th.addEventListener('click', function(){
      const i = Number(th.dataset.col);
      sortCol = (sortCol === i) ? null : i;
      head.querySelectorAll('th.scol').forEach(o => o.classList.toggle('on', o === th && sortCol !== null));
      hint.textContent = sortCol === null ? ''
        : 'Sorted by ' + r.columns[sortCol].label + ' - click the header again to restore the published order.';
      draw();
    });
  });

  const box = document.getElementById('robshow25');
  box.addEventListener('change', function(){ only25 = box.checked; draw(); });

  draw();

  const phrase = {equal: 'the baseline', no_poverty: 'dropping poverty', no_hunger: 'dropping hunger',
    no_water: 'dropping water', no_energy: 'dropping electricity', worst: 'using the worst dimension'};
  const weakest = r.columns.slice(1).reduce((a, b) => (b.kept < a.kept ? b : a));
  const heldOne = r.rows.filter(x => x.held === 1).length;
  document.getElementById('rob-summary').textContent =
    r.stable + ' of the ' + r.baseline + ' hold their place under all six readings' +
    (heldOne ? '; ' + heldOne + ' countries from outside the list enter under exactly one' : '') +
    '. The largest swing comes from ' + phrase[weakest.key] + ': ' +
    (r.baseline - weakest.kept) + ' of the 25 leave the list.';
})();

/* ---------- convergence ---------- */
(function convergence(){
  const c = DATA.convergence;
  const rows = c.rows;
  const W = 560, H = 560, m = {t: 20, r: 22, b: 58, l: 58};
  const svg = d3.select('#conv');
  const x = d3.scaleLinear().domain([0, 76]).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([7, -19]).range([m.t, H - m.b]);

  [0, 25, 50, 75].forEach(v => {
    svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', y(7)).attr('y2', y(-19))
       .attr('stroke', '#f4f5f6');
    svg.append('text').attr('x', x(v)).attr('y', y(-19) + 15).attr('text-anchor', 'middle')
       .attr('class', 'ax').text(v);
  });
  [5, 0, -5, -10, -15].forEach(v => {
    svg.append('line').attr('x1', x(0)).attr('x2', x(76)).attr('y1', y(v)).attr('y2', y(v))
       .attr('stroke', v === 0 ? '#dfe1e3' : '#f4f5f6');
    svg.append('text').attr('x', m.l - 8).attr('y', y(v) + 3).attr('text-anchor', 'end')
       .attr('class', 'ax').text(v > 0 ? '+' + v : v);
  });

  // The fitted line is the finding: its slope says whether need is converging
  // and how fast, so it is drawn rather than only described.
  svg.append('line').attr('x1', x(0)).attr('y1', y(c.intercept))
     .attr('x2', x(76)).attr('y2', y(c.intercept + c.slope * 76))
     .attr('stroke', '#dc9600').attr('stroke-width', 1.4).attr('stroke-dasharray', '7 4');

  const money = rows.filter(p => (p.pc || 0) > 0).map(p => p.pc).sort((a, b) => a - b);
  const cut = money.length ? money[Math.floor(money.length / 2)] : 0;
  const fill = p => !(p.pc > 0) ? '#f2a900' : (p.pc >= cut ? '#002244' : '#7fa6c2');

  svg.append('g').selectAll('circle').data(rows).join('circle')
    .attr('cx', p => x(p.n15)).attr('cy', p => y(p.delta))
    .attr('r', p => p.rank ? 5.2 : 4.1)
    .attr('fill', fill).attr('fill-opacity', .88)
    .attr('stroke', p => p.rank ? '#ffffff' : 'none')
    .attr('stroke-width', p => p.rank ? 1.5 : 0)
    .style('cursor', 'pointer')
    .on('click', (event, p) => openCountry(p.iso3))
    .append('title')
    .text(p => p.name + ' - ' + p.n15.toFixed(1) + ' in 2015, ' + p.n24.toFixed(1) + ' in ' +
      p.year + ' (' + (p.delta > 0 ? '+' : '') + p.delta.toFixed(1) + ' points); $' +
      p.pc.toFixed(0) + ' per person approved since 2015');

  // Five names, chosen so the eye finds the shape: the deepest falls, the fall
  // that came with almost no money, and the largest rises.
  const picks = rows.filter(p => ['UGA', 'KHM', 'ZWE', 'TUN', 'UKR'].includes(p.iso3));
  const boxes = [];
  picks.forEach(p => {
    const label = p.name.length > 18 ? p.name.slice(0, 17) + '\u2026' : p.name;
    const w = label.length * 5.1, h = 10, px = x(p.n15), py = y(p.delta);
    const spots = [[px + 8, py - 4, 'start'], [px - 8 - w, py - 4, 'start'],
                   [px + 8, py + 12, 'start'], [px - 8 - w, py + 12, 'start']];
    for (const [lx, ly, anchor] of spots) {
      const box = {x0: lx, x1: lx + w, y0: ly - h + 3, y1: ly + 2, h};
      const clash = boxes.some(b => lx < b.x1 + 3 && lx + w > b.x0 - 3 &&
                                      ly < b.y1 + 3 && ly - h > b.y0 - 3);
      if (lx < m.l + 2 || lx + w > W - m.r || clash) continue;
      boxes.push(box);
      svg.append('text').attr('x', lx).attr('y', ly).attr('text-anchor', anchor)
         .attr('class', 'lbl').text(label);
      break;
    }
  });

  svg.append('text').attr('x', (x(0) + x(76)) / 2).attr('y', H - 12)
     .attr('text-anchor', 'middle').attr('class', 'axl')
     .text('Measured need, 2015  (points of population unserved)');
  const midY = (y(7) + y(-19)) / 2;
  svg.append('text').attr('x', 14).attr('y', midY).attr('text-anchor', 'middle')
     .attr('class', 'axl').attr('transform', 'rotate(-90, 14, ' + midY + ')')
     .text('Change since 2015 (points; down is better)');

  document.getElementById('convlegend').innerHTML =
    '<div><div class="cap">Approved since 2015, per person</div><div class="chips">' +
    '<span class="chip"><i style="background:#002244"></i>above the median</span>' +
    '<span class="chip"><i style="background:#7fa6c2"></i>below the median</span>' +
    '<span class="chip"><i style="background:#f2a900"></i>nothing approved</span>' +
    '</div></div>' +
    '<div><div class="cap">Dashed line</div><div class="chips">' +
    '<span class="chip"><i style="background:#dc9600;height:2px;margin:5px 0"></i>' +
    'fit, \u2212' + Math.abs(c.slope).toFixed(2) + ' points per point of 2015 need</span>' +
    '</div></div>' +
    '<div><div class="cap">White ring</div><div class="chips">' +
    '<span class="chip"><i style="background:#002244;border-radius:50%;' +
    'box-shadow:0 0 0 1.5px #fff"></i>on the short list</span></div></div>';

  document.getElementById('convcaption').textContent =
    'Need is converging, slowly. Countries that started above 40 points fell a median of ' +
    Math.abs(c.high).toFixed(1) + '; those that started under 10 fell ' +
    Math.abs(c.low).toFixed(1) + '. A slope of \u2212' + Math.abs(c.slope).toFixed(2) +
    ' points per point of 2015 need would halve the median gap in about ' +
    c.half_life + ' years if the ' + c.window +
    '-year average held - a rate, not a forecast. Money does not sort the cloud: across ' +
    c.n_money + ' countries that received anything since 2015, the correlation between the ' +
    'change in need and log dollars per person is ' + (c.r >= 0 ? '+' : '') + c.r.toFixed(2) +
    '; ' + c.improved + ' of ' + c.n + ' countries improved by two points or more.';

  const movers = document.getElementById('movertable').querySelector('tbody');
  const top = rows.slice(0, 5), rising = rows.slice(-3);
  const row = (p, cls) => '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + p.name +
    '</td><td style="text-align:right;color:' + (p.delta <= 0 ? '#2f5d3f' : '#8a3b22') + '">' +
    (p.delta > 0 ? '+' : '') + p.delta.toFixed(1) + '</td><td style="text-align:right">' +
    (p.pc > 0 ? '$' + fmt(p.pc) : 'none') + '</td></tr>';
  movers.innerHTML = top.map(p => row(p)).join('') +
    '<tr class="sep"><td colspan="3" style="color:#6f7377;font-size:.63rem;text-transform:uppercase;' +
    'letter-spacing:.09em">Rising</td></tr>' + rising.map(p => row(p)).join('');
})();

renderLegend();

/* ---------- country file ---------- */
const CF = document.getElementById('cf');
const CFB = document.getElementById('cf-body');
const CFLAB = ['Equal', '\u2212 poverty', '\u2212 hunger', '\u2212 water', '\u2212 electricity', 'Worst'];

function money(v){
  return '$' + (v >= 10 ? Math.round(v).toLocaleString('en-US') : v.toFixed(2));
}

function openCountry(iso){
  const d = byIso.get(iso);
  if (!d) return;
  const rob = DATA.robustness.rows.find(x => x.iso3 === iso);
  const conv = DATA.convergence.rows.find(x => x.iso3 === iso);
  const four = [['Poverty', d.gap_poverty], ['Hunger', d.gap_hunger],
                ['Water', d.gap_water], ['Electricity', d.gap_energy]];

  let verdict, quiet = false;
  if (!d.complete){
    verdict = 'Not ranked: ' + (d.n_ind || 0) + ' of the four indicators carry a value in this snapshot.';
    quiet = true;
  } else if (d.gap >= 0.45){
    verdict = 'Need clearly outruns financing. A review candidate: the portfolio is thin against the measured need.';
  } else if (d.gap >= 0.15){
    verdict = 'Need ahead of financing. A portfolio conversation, not necessarily new money.';
  } else if (d.gap > -0.15){
    verdict = 'Need and financing are roughly in step, near the middle of both distributions.';
  } else {
    verdict = 'Financing ahead of measured need: the portfolio is heavier than the need ranks imply.';
    quiet = true;
  }

  const bars = four.map(function(pair){
    const label = pair[0], v = pair[1];
    const has = v !== null && v !== undefined && !isNaN(v);
    const w = has ? Math.max(0, Math.min(100, v)) : 100;
    return '<div class="barbox"><span>' + label + '</span><span class="track">' +
      '<span class="fill' + (has ? '' : ' none') + '" style="width:' + w + '%"></span></span>' +
      '<span class="val">' + (has ? v.toFixed(1) : 'n/a') + '</span></div>';
  }).join('');

  const kpi = (u, v) => '<div><span class="u">' + u + '</span><b>' + v + '</b></div>';
  const chips = rob ? rob.ranks.map(function(rank, i){
    const on = rank !== null && rank <= 25;
    return '<span class="chipb' + (on ? ' on' : '') + '">' + CFLAB[i] + ' ' +
      (rank === null ? '-' : rank) + '</span>';
  }).join('') : '';

  let drift = 'No comparable reading in both 2015 and a later year.';
  if (conv){
    drift = 'Need ' + (conv.delta > 0 ? 'rose ' : 'fell ') + Math.abs(conv.delta).toFixed(1) +
      ' points between 2015 and ' + conv.year + '. ' +
      (conv.pc > 0 ? money(conv.pc) + ' per person approved since 2015.'
                   : 'Nothing approved since 2015.');
  }

  CFB.innerHTML =
    '<h4>' + d.name + '</h4>' +
    '<div class="meta">' + (d.region || '') + ' &middot; ' + (d.income || '') + '</div>' +
    '<p class="verdict' + (quiet ? ' quiet' : '') + '">' + verdict + '</p>' +
    '<div class="lbl">The four gaps &middot; points of population unserved</div>' + bars +
    '<div class="lbl">Position</div><div class="kpis">' +
      kpi('Need index', d.complete ? d.need.toFixed(1) + ' of 100' : 'not ranked') +
      kpi('Financing / person', d.pc > 0 ? money(d.pc) : '$0') +
      kpi('Allocation gap', d.complete ? (d.gap > 0 ? '+' : '') + d.gap.toFixed(2) : '-') +
      kpi('Operations', fmt(d.ops)) +
      kpi('Short list', rob && rob.baseline ? '#' + rob.baseline + ' of 25'
          : (d.complete ? 'outside the 25' : '-')) +
      kpi('Population', d.population ? fmt(d.population) : '-') +
    '</div>' +
    '<div class="lbl">Rank under each reading</div><div class="chips">' +
      (chips || '<span class="chipb">not ranked</span>') + '</div>' +
    '<div class="lbl">Since 2015</div><p class="drift">' + drift + '</p>' +
    '<div class="foot"><button class="go" id="cf-go">Show in the short-list table</button></div>';
  document.getElementById('cf-go').addEventListener('click', function(){ playSearch(d.name); });
  CF.hidden = false;
}

document.getElementById('cf-close').addEventListener('click', function(){ CF.hidden = true; });
window.addEventListener('keydown', function(e){ if (e.key === 'Escape') CF.hidden = true; });
countries.on('click', function(event, f){ openCountry(f.properties.iso3); });
[...document.querySelectorAll('#blindtable tbody tr')].forEach(function(tr){
  tr.addEventListener('click', function(){ openCountry(tr.dataset.iso); });
});

/* ---------- weights the reader can move ---------- */
(function weighting(){
  const KEYS = ['gap_poverty', 'gap_hunger', 'gap_water', 'gap_energy'];
  const LAB = {gap_poverty: 'Poverty', gap_hunger: 'Hunger', gap_water: 'Water',
               gap_energy: 'Electricity'};
  const pop = DATA.countries.filter(d => d.complete);
  const published = new Map(DATA.priority.map((d, i) => [d.iso3, i + 1]));
  const state = {gap_poverty: 5, gap_hunger: 5, gap_water: 5, gap_energy: 5};

  // (count of values below) / (n - 1): SQLite's PERCENT_RANK, which is what
  // mart_priority uses, so equal weights reproduce the published list.
  function percentile(pairs){
    const sorted = pairs.map(p => p[1]).sort((a, b) => a - b);
    const n = sorted.length;
    const out = new Map();
    pairs.forEach(function(pair){
      let lo = 0, hi = n;
      while (lo < hi){
        const mid = (lo + hi) >> 1;
        if (sorted[mid] < pair[1]) lo = mid + 1; else hi = mid;
      }
      out.set(pair[0], n > 1 ? lo / (n - 1) : 0);
    });
    return out;
  }
  const finPct = percentile(pop.map(d => [d.iso3, d.pc || 0]));

  function liveNeed(){
    const rows = [];
    pop.forEach(function(d){
      let num = 0, den = 0;
      KEYS.forEach(function(k){
        const w = state[k];
        if (w <= 0) return;
        const g = d[k];
        // A country is read on the gaps it reports, renormalised over the
        // weighted ones - the same rule as the SQL, so equal weights must
        // reproduce the published list exactly.
        if (g === null || g === undefined) return;
        num += w * g; den += w;
      });
      if (!den) return;
      rows.push([d.iso3, num / den]);
    });
    return rows;
  }

  function draw(){
    const need = liveNeed();
    const tb = document.querySelector('#wtable tbody');
    if (!need.length){
      tb.innerHTML = '<tr><td colspan="6">Every weight is at zero - raise one to rank.</td></tr>';
      document.getElementById('wnote2').textContent = '';
      document.getElementById('wdrop').textContent = '';
      return;
    }
    const needPct = percentile(need);
    const ranked = need.map(function(pair){
      return {iso3: pair[0], need: pair[1], gap: needPct.get(pair[0]) - finPct.get(pair[0])};
    }).sort((a, b) => b.gap - a.gap);
    const live25 = ranked.slice(0, 25);
    const kept = live25.filter(r => published.has(r.iso3));
    const out = [...published.keys()].filter(iso => !live25.some(r => r.iso3 === iso));

    tb.innerHTML = ranked.slice(0, 10).map(function(r, i){
      const d = byIso.get(r.iso3), was = published.get(r.iso3);
      let mv = '<span class="mv in">new</span>';
      if (was){
        // Countries that tie on the gap keep the published order; a one-place
        // swap between equal scores is not a finding.
        const tied = d.gap !== null && Math.abs(r.gap - d.gap) < 0.005;
        const diff = was - (i + 1);
        mv = tied ? '<span class="mv same">same</span>'
           : '<span class="mv ' + ((diff > 0 || !diff) ? 'in' : 'out') + '">' +
             (diff === 0 ? 'same' : (diff > 0 ? '+' : '') + diff) + '</span>';
      }
      return '<tr data-iso="' + r.iso3 + '"><td>' + (i + 1) + '</td><td>' + d.name + '</td>' +
        '<td style="text-align:right">' + r.need.toFixed(1) + '</td>' +
        '<td style="text-align:right">' + (d.pc > 0 ? money(d.pc) : 'none') + '</td>' +
        '<td style="text-align:right;color:' + (r.gap > 0 ? '#a2701c' : '#005f93') + '">' +
        (r.gap > 0 ? '+' : '') + r.gap.toFixed(2) + '</td><td>' + mv + '</td></tr>';
    }).join('');

    [...tb.querySelectorAll('tr')].forEach(function(tr){
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function(){ openCountry(tr.dataset.iso); });
    });

    document.getElementById('wnote2').innerHTML = '<b>' + kept.length +
      ' of the published 25</b> survive this weighting, out of ' + ranked.length +
      ' countries ranked on the gaps they report.';
    document.getElementById('wdrop').innerHTML = out.length
      ? '<b>Leaving the list:</b> ' + out.slice(0, 8).map(iso => byIso.get(iso).name).join(', ') +
        (out.length > 8 ? ' and ' + (out.length - 8) + ' more.' : '.')
      : '<b>No one leaves:</b> the same 25 countries, in a different order.';
  }

  const wrap = document.getElementById('wsliders');
  KEYS.forEach(function(k){
    const row = document.createElement('div');
    row.className = 'wrow';
    row.innerHTML = '<span>' + LAB[k] + '</span>' +
      '<input type="range" min="0" max="10" step="1" value="5" data-key="' + k +
      '" aria-label="Weight for ' + LAB[k] + '"><span class="wv">5</span>';
    wrap.appendChild(row);
  });
  wrap.addEventListener('input', function(e){
    const k = e.target.dataset.key;
    if (!k) return;
    state[k] = Number(e.target.value);
    e.target.parentNode.querySelector('.wv').textContent = e.target.value;
    draw();
  });
  document.getElementById('wreset').addEventListener('click', function(){
    KEYS.forEach(function(k){ state[k] = 5; });
    [...wrap.querySelectorAll('input')].forEach(function(el){
      el.value = 5;
      el.parentNode.querySelector('.wv').textContent = '5';
    });
    draw();
  });
  draw();
})();
</script>
</body>
</html>
"""


def main() -> int:
    write_site(build_payload())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
