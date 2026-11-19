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
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARTS = ROOT / "data" / "marts"
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site"

# Sequential ramps blended into a 3x3 bivariate grid.
PORTFOLIO_RAMP = ["#e4efe9", "#8dc0ad", "#2f7f68"]
NEED_RAMP = ["#fbe3cf", "#efa273", "#bf5229"]


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
    return {
        f"{i + 1}{j + 1}": blend(PORTFOLIO_RAMP[i], NEED_RAMP[j])
        for i in range(3)
        for j in range(3)
    }


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


def build_payload() -> dict:
    countries = load_csv("mart_country")
    health = {row["metric"]: num(row["value"]) for row in load_csv("mart_portfolio_health")}
    sectors = load_csv("mart_sector")
    regions = load_csv("mart_region")
    priority = load_csv("mart_priority")

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
        "generated": date.today().isoformat(),
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
        "positive_gap": sum(1 for r in rows if (r["gap"] or 0) > 0),
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
<title>Portfolio Lens - development finance delivery against measured need</title>
<style>
  :root{--paper:#fbfaf7;--ink:#191a17;--muted:#6b6f66;--rule:#ddd8cd;--teal:#2f7f68;--panel:#fff}
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;background:var(--paper);color:var(--ink)}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       font-size:15px;line-height:1.62;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1120px;margin:0 auto;padding:0 28px 88px}
  h1,h2,h3{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-weight:600;letter-spacing:-.01em}
  h1{font-size:2.45rem;line-height:1.14;margin:0 0 .6rem}
  h2{font-size:1.32rem;margin:3.1rem 0 .35rem}
  h3{font-size:1rem;margin:1.9rem 0 .25rem;letter-spacing:0}
  p{margin:.55rem 0;max-width:76ch}
  .kicker{text-transform:uppercase;letter-spacing:.14em;font-size:.71rem;color:var(--muted);margin-bottom:1.3rem}
  header{padding:4.2rem 0 1.5rem;border-bottom:1px solid var(--rule)}
  .lede{font-size:1.06rem;color:#3c3f38;max-width:68ch}
  .note{font-size:.81rem;color:var(--muted);max-width:76ch}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--rule);
        border:1px solid var(--rule);margin:2.1rem 0 0}
  .kpi{background:var(--paper);padding:1rem 1.15rem}
  .kpi .v{font-family:"Iowan Old Style",Georgia,serif;font-size:1.55rem;line-height:1.2}
  .kpi .l{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-top:.3rem}
  .controls{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:1.3rem 0 .85rem}
  .controls .group{border:1px solid var(--rule);background:#fff;display:flex}
  .controls button{font:inherit;font-size:.81rem;padding:.38rem .78rem;border:0;background:transparent;
       color:var(--muted);cursor:pointer;border-right:1px solid var(--rule)}
  .controls button:last-child{border-right:0}
  .controls button.on{background:var(--ink);color:#fff}
  .legend{display:flex;gap:1.6rem;align-items:flex-start;margin:.35rem 0 .9rem;flex-wrap:wrap}
  .legend table{border-collapse:collapse;font-size:.72rem}
  .legend td{border:1px solid #fff}
  .sw{width:26px;height:21px}
  .axis{font-size:.67rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
  .mapwrap{position:relative;background:var(--panel);border:1px solid var(--rule)}
  svg{display:block;width:100%;height:auto}
  .country{stroke:#fff;stroke-width:.6px;cursor:pointer}
  #tip{position:absolute;pointer-events:none;background:#fff;border:1px solid var(--rule);
    box-shadow:0 6px 18px rgba(0,0,0,.09);padding:.55rem .7rem;font-size:.78rem;min-width:186px;
    opacity:0;transition:opacity .12s;line-height:1.45;z-index:20}
  #tip .n{font-weight:600;font-size:.9rem}
  #tip .r{color:var(--muted);font-size:.71rem;margin-bottom:.3rem}
  #tip dl{display:grid;grid-template-columns:auto auto;gap:.1rem .6rem;margin:0}
  #tip dt{color:var(--muted)} #tip dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
  .scatterwrap{background:var(--panel);border:1px solid var(--rule);margin-top:.5rem;position:relative}
  table.data{width:100%;border-collapse:collapse;font-size:.84rem;margin-top:.9rem}
  table.data th{text-align:left;font-weight:600;font-size:.71rem;text-transform:uppercase;
    letter-spacing:.08em;color:var(--muted);border-bottom:1px solid var(--rule);padding:.45rem .55rem}
  table.data td{padding:.4rem .55rem;border-bottom:1px solid #ece8dd;font-variant-numeric:tabular-nums}
  table.data tr:hover td{background:#f4f1e9}
  .bar{height:5px;background:#e6e1d5;position:relative}
  .bar span{position:absolute;left:0;top:0;bottom:0;background:var(--teal)}
  .two{display:grid;grid-template-columns:1.1fr .9fr;gap:2.3rem;align-items:start}
  .brief ol{padding-left:1.15rem} .brief li{margin:.45rem 0}
  footer{margin-top:3.6rem;padding-top:1.1rem;border-top:1px solid var(--rule);font-size:.77rem;color:var(--muted)}
  @media (max-width:820px){.kpis{grid-template-columns:repeat(2,1fr)} .two{grid-template-columns:1fr} h1{font-size:1.9rem}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="kicker">Portfolio Lens &middot; independent analysis on public data</div>
  <h1>Where development finance is delivered, and where it is needed</h1>
  <p class="lede">A reproducible pipeline that reads a sovereign development portfolio against four
  official SDG indicators. It asks a management question rather than a mapping question:
  <em>which country portfolios carry more measured need than delivery?</em></p>
  <div class="kpis">
    <div class="kpi"><div class="v">__TOTAL_VALUE__</div><div class="l">active portfolio, USD</div></div>
    <div class="kpi"><div class="v" id="k-ops">-</div><div class="l">operations</div></div>
    <div class="kpi"><div class="v" id="k-countries">-</div><div class="l">countries covered</div></div>
    <div class="kpi"><div class="v" id="k-blind">-</div><div class="l">need outruns financing</div></div>
  </div>
</header>

<h2>1 &middot; Need against delivery</h2>
<p>The default view shows the <strong>allocation gap</strong> - a country's percentile rank on
measured need minus its percentile rank on financing per person. Rust means it carries more need
than financing; blue means the reverse. Because both ranks are size-neutral, a small state and a
large one are compared on position, not on the size of their economy. Switch to
<em>need &times; portfolio</em> for the joint 3&times;3 distribution instead.</p>

<div class="controls">
  <span class="axis">colour by</span>
  <div class="group" id="modes">
    <button data-mode="gap" class="on">allocation gap</button>
    <button data-mode="bivariate">need &times; portfolio</button>
    <button data-mode="need">need only</button>
    <button data-mode="portfolio">portfolio only</button>
  </div>
  <div class="group" id="filters">
    <button data-filter="all" class="on">all countries</button>
    <button data-filter="complete">with 3+ indicators</button>
  </div>
</div>

<div class="legend" id="legend"></div>

<div class="mapwrap">
  <div id="tip"></div>
  <svg id="map" viewBox="0 0 1000 520" role="img" aria-label="World map of portfolio against need"></svg>
</div>
<p class="note">Grey areas have no polygon at the 1:110m simplification, or no measured need.
Small island states missing from the polygon set are still in the table and in
<code>data/marts/mart_country.csv</code>.</p>

<h2>2 &middot; The allocation question</h2>
<p>Financing per person is on a log scale because it spans five orders of magnitude, from zero
active operations to five figures per inhabitant. Vertical position is the measured SDG gap. The
shaded corner is where a portfolio review would ordinarily start: most need, least money per
person.</p>
<div class="scatterwrap"><svg id="scatter" viewBox="0 0 1000 460" role="img"
  aria-label="Scatterplot of need against portfolio value"></svg></div>

<h2>3 &middot; The short list</h2>
<p>Ranked by allocation gap. This is not a recommendation to move money; it is the population a
portfolio review would examine first, and the columns show why each country is on it.</p>
<table class="data" id="blindtable">
  <thead><tr><th>Country</th><th>Region</th><th style="text-align:right">SDG gap</th>
  <th style="text-align:right">Financing / person</th><th style="text-align:right">Allocation gap</th></tr></thead>
  <tbody></tbody>
</table>

<h2>4 &middot; The portfolio itself</h2>
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
      <thead><tr><th>Region</th><th style="text-align:right">Share</th><th style="text-align:right;white-space:nowrap">High need / thin</th></tr></thead>
      <tbody></tbody>
    </table>
    <h3>Portfolio health</h3>
    <table class="data" id="healthtable"><tbody></tbody></table>
  </div>
</div>

<h2>5 &middot; Method, and what this cannot tell you</h2>
<div class="brief">
  <h3>How the two layers are built</h3>
  <p><strong>Delivery.</strong> Every operation in the public project register is parsed into
  country links: commitments split evenly where an operation covers several countries, planned
  duration from board approval to closing date. Country aggregates give operation count, total and
  active commitment, and median duration.</p>
  <p><strong>Need.</strong> Four SDG series with a stated 2030 target - poverty (1.1.1),
  undernourishment (2.1.1), safely managed drinking water (6.1.1), electricity access (7.1.1).
  Each becomes percentage points of population not yet served and is averaged. Countries with fewer
  than three of the four are excluded from the terciles rather than assumed to be low-need.</p>
  <h3>Three things this does not do</h3>
  <ol>
    <li>It does not attribute outcomes. A thin portfolio and a large gap can both be symptoms of
    state capacity, access constraints or donor division of labour.</li>
    <li>Commitment is not disbursement. Value here is approved financing, not money that reached a
    country.</li>
    <li>Terciles are relative, not judged against a sufficiency standard. A country in the top
    tercile can still be under-financed for its population.</li>
  </ol>
  <h3>What a next iteration adds</h3>
  <p>Disbursement ratios from the same register, financing per capita, and a process view of
  approval-to-first-disbursement latency - the metric that turns a portfolio map into a business
  process review.</p>
</div>

<footer>
  Sources: World Bank projects API; UN Statistics Division SDG indicator database; Natural Earth
  (1:110m) boundaries; ISO 3166 / UN M49 reference table. Snapshot built <span id="gen"></span>.
  Independent work; figures are not reviewed or endorsed by any institution named in the source data.
</footer>
</div>

<script src="https://fastly.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script>
const DATA = __PAYLOAD__;
document.getElementById('gen').textContent = DATA.generated;

const HEALTH = DATA.health;
document.getElementById('k-ops').textContent = d3.format(',')(HEALTH.total_operations);
document.getElementById('k-countries').textContent = d3.format(',')(HEALTH.countries_with_portfolio);
document.getElementById('k-blind').textContent = DATA.positive_gap;

const byIso = new Map(DATA.countries.map(d => [d.iso3, d]));
const fmtUSD = v => v >= 1e9 ? '$' + (v/1e9).toFixed(1) + 'B'
                : v >= 1e6 ? '$' + Math.round(v/1e6) + 'M'
                : '$' + d3.format(',.0f')(v || 0);

const GAP_SCALE = d3.scaleLinear()
  .domain([-0.65, -0.3, -0.08, 0.08, 0.3, 0.65])
  .range(['#1f5a7a', '#7fabbe', '#e9e3d1', '#efe1cb', '#dd9f65', '#a8441e'])
  .clamp(true);
const PORT_RAMP = ['#e4efe9', '#8dc0ad', '#2f7f68'];
const NEED_RAMP = ['#fbe3cf', '#efa273', '#bf5229'];
let mode = 'gap';
let filter = 'all';

function fillFor(d){
  if (!d) return '#e9e6df';
  if (filter === 'complete' && !d.complete) return '#efebe2';
  if (mode === 'gap'){
    if (!d.complete || d.gap === null || d.gap === undefined) return '#e9e6df';
    return GAP_SCALE(d.gap);
  }
  if (mode === 'need'){
    if (!d.need) return '#e9e6df';
    return NEED_RAMP[Math.max(0, Math.min(2, (d.need_tercile || 1) - 1))];
  }
  if (mode === 'portfolio'){
    return PORT_RAMP[Math.max(0, Math.min(2, (d.portfolio_tercile || 1) - 1))];
  }
  if (!d.complete) return '#e9e6df';
  return DATA.palette['' + d.portfolio_tercile + d.need_tercile];
}

const width = 1000, height = 520;
const svg = d3.select('#map');
const projection = d3.geoNaturalEarth1().fitExtent([[8, 12], [width - 8, height - 14]], {type:'Sphere'});
const path = d3.geoPath(projection);

svg.append('path').datum({type:'Sphere'}).attr('d', path).attr('fill', '#f2efe7').attr('stroke', 'none');

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
      ['Operations', d3.format(',')(d.ops)],
      ['Median duration', d.median_years ? d.median_years.toFixed(1) + ' yrs' : '-'],
      ['Quadrant', d.quadrant || '-']
    ];
    tip.style('opacity', 1).html('<div class="n">' + name + '</div>' +
      '<div class="r">' + (d.region || '') + ' &middot; ' + (d.income || '') + '</div>' +
      '<dl>' + rows.map(r => '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>').join('') + '</dl>');
  }
  const box = document.querySelector('.mapwrap').getBoundingClientRect();
  let x = event.clientX - box.left + 14, y = event.clientY - box.top + 14;
  if (x > box.width - 220) x -= 232;
  tip.style('left', x + 'px').style('top', y + 'px');
}
function hideTip(){ tip.style('opacity', 0); }

function recolour(){
  countries.attr('fill', f => fillFor(byIso.get(f.properties.iso3)));
  renderLegend();
}

function renderLegend(){
  const el = document.getElementById('legend');
  if (mode === 'gap'){
    el.innerHTML = '<div style="max-width:420px"><div class="axis" style="margin-bottom:.35rem">' +
      'allocation gap</div>' +
      '<div style="height:12px;background:linear-gradient(90deg,' +
      ['#1f5a7a','#7fabbe','#e9e3d1','#efe1cb','#dd9f65','#a8441e'].join(',') + ')"></div>' +
      '<div style="display:flex;justify-content:space-between;font-size:.68rem;color:#6b6f66;' +
      'margin-top:.28rem;gap:1rem;white-space:nowrap">' +
      '<span>&minus;0.65 &nbsp;over-financed</span><span>balanced</span>' +
      '<span>under-financed &nbsp;+0.65</span></div></div>' +
      '<div class="note" style="max-width:30ch;margin:0">Rank-based, so every country is compared ' +
      'on position rather than on the size of its portfolio.</div>';
    return;
  }
  if (mode !== 'bivariate'){
    const ramp = mode === 'need' ? NEED_RAMP : PORT_RAMP;
    el.innerHTML = '<div><div class="axis" style="margin-bottom:.3rem">' +
      (mode === 'need' ? 'unmet SDG need' : 'portfolio size') + '</div>' +
      '<div style="display:flex">' + ramp.map(c => '<div class="sw" style="background:' + c + '"></div>').join('') +
      '</div><div style="display:flex;justify-content:space-between;font-size:.7rem;color:#6b6f66;width:78px">' +
      '<span>low</span><span>high</span></div></div>';
    return;
  }
  let rowsHtml = '';
  for (let need = 3; need >= 1; need--){
    rowsHtml += '<tr>';
    for (let port = 1; port <= 3; port++){
      rowsHtml += '<td class="sw" style="background:' + DATA.palette['' + port + need] + '"></td>';
    }
    rowsHtml += '</tr>';
  }
  el.innerHTML = '<div><div class="axis" style="margin-bottom:.3rem">need &uarr; &nbsp; portfolio &rarr;</div>' +
    '<table>' + rowsHtml + '</table>' +
    '<div style="display:flex;justify-content:space-between;font-size:.7rem;color:#6b6f66;width:78px">' +
    '<span>thin</span><span>large</span></div></div>' +
    '<div class="note" style="max-width:34ch;margin:0">Dark rust cells are the high-need, ' +
    'thin-portfolio corner. The fill blends two sequential ramps, so neither layer reads alone.</div>';
}

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
  const m = {t: 20, r: 26, b: 48, l: 58};
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
    .attr('fill', '#f7efe6').attr('opacity', .6);
  g.append('text').attr('x', 8).attr('y', 15).attr('font-size', 10.5)
    .attr('fill', '#8a5a3c').text('HIGH NEED / THIN PORTFOLIO');

  g.append('g').attr('transform', 'translate(0,' + H + ')')
    .call(d3.axisBottom(x).ticks(6, '.0s')).attr('font-size', 11);
  g.append('g').call(d3.axisLeft(y).ticks(6)).attr('font-size', 11);

  g.append('text').attr('x', W/2).attr('y', H + 40).attr('text-anchor', 'middle')
    .attr('font-size', 12).attr('fill', '#6b6f66').text('Financing per person, USD (log scale)');
  g.append('text').attr('transform', 'rotate(-90)').attr('x', -H/2).attr('y', -42)
    .attr('text-anchor', 'middle').attr('font-size', 12).attr('fill', '#6b6f66')
    .text('Unmet SDG need (index 0-100)');

  g.selectAll('circle').data(pts).join('circle')
    .attr('cx', d => x(Math.max(d.pc, floor)))
    .attr('cy', d => y(d.need))
    .attr('r', d => d.quadrant === 'high need / thin portfolio' ? 5 : 3.4)
    .attr('fill', d => DATA.palette['' + d.portfolio_tercile + d.need_tercile])
    .attr('stroke', d => d.quadrant === 'high need / thin portfolio' ? '#7d3418' : '#ffffff')
    .attr('stroke-width', d => d.quadrant === 'high need / thin portfolio' ? 1.1 : .7)
    .attr('opacity', .92);

  const labelled = pts.filter(d => d.quadrant === 'high need / thin portfolio')
    .sort((a, b) => b.need - a.need).slice(0, 9);
  g.selectAll('text.lbl').data(labelled).join('text')
    .attr('class', 'lbl')
    .attr('x', d => x(Math.max(d.pc, floor)) + 7).attr('y', d => y(d.need) + 3)
    .attr('font-size', 10).attr('fill', '#3c3f38').text(d => d.iso3);
})();

const tb = document.querySelector('#blindtable tbody');
DATA.priority.slice(0, 14).forEach(d => {
  const tr = document.createElement('tr');
  const pc = d.pc > 0 ? '$' + (d.pc < 10 ? d.pc.toFixed(2) : d.pc.toFixed(0)) : 'none active';
  tr.innerHTML = '<td>' + d.name + '</td><td>' + (d.region || '') + '</td>' +
    '<td style="text-align:right">' + d.need.toFixed(1) + '</td>' +
    '<td style="text-align:right">' + pc + '</td>' +
    '<td style="text-align:right">' + (d.gap > 0 ? '+' : '') + d.gap.toFixed(2) + '</td>';
  tb.appendChild(tr);
});

const st = document.querySelector('#sectortable tbody');
DATA.sectors.slice(0, 9).forEach(d => {
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>' + d.sector + '</td>' +
    '<td><div class="bar"><span style="width:' + Math.min(100, d.share * 100).toFixed(1) + '%"></span></div></td>' +
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

renderLegend();
</script>
</body>
</html>
"""


def main() -> int:
    write_site(build_payload())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
