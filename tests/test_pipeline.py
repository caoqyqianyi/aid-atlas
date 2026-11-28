"""Data and logic tests.

Run with either `python -m unittest discover -s tests` or `pytest tests`.

The reconciliation tests are the important ones: they fail if the country
split, the date parsing or the amount parsing ever stops adding up.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_module("build", ROOT / "pipeline" / "build.py")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise unittest.SkipTest(f"{path.name} not built yet - run pipeline/build.py")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class TestParsers(unittest.TestCase):
    def test_amount_with_thousands_separator(self):
        self.assertEqual(build.parse_amount("200,000,000"), 200_000_000.0)

    def test_amount_missing_values_are_none_not_zero(self):
        for value in (None, "", "   ", "n/a"):
            self.assertIsNone(build.parse_amount(value))

    def test_amount_keeps_zero(self):
        self.assertEqual(build.parse_amount("0"), 0.0)

    def test_date_iso_timestamp(self):
        self.assertEqual(str(build.parse_date("2024-12-20T00:00:00Z")), "2024-12-20")

    def test_date_us_style_from_the_same_api(self):
        self.assertEqual(str(build.parse_date("12/20/2025 12:00:00 AM")), "2025-12-20")

    def test_date_garbage_returns_none(self):
        self.assertIsNone(build.parse_date("not a date"))

    def test_country_list_handles_single_and_multi(self):
        self.assertEqual(build.as_list(["RW"]), ["RW"])
        self.assertEqual(build.as_list("RW"), ["RW"])
        self.assertEqual(build.as_list(None), [])


class TestMarts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ops = read_csv(ROOT / "data" / "staging" / "ops.csv")
        cls.links = read_csv(ROOT / "data" / "staging" / "op_country.csv")
        cls.countries = read_csv(ROOT / "data" / "marts" / "mart_country.csv")
        cls.priority = read_csv(ROOT / "data" / "marts" / "mart_priority.csv")
        cls.health = read_csv(ROOT / "data" / "marts" / "mart_portfolio_health.csv")

    def test_country_split_reconciles_to_portfolio_total(self):
        portfolio_total = sum(float(o["total_amt"]) for o in self.ops if o["total_amt"])
        split_total = sum(float(l["amount_share"]) for l in self.links)
        self.assertAlmostEqual(portfolio_total, split_total, places=2)

    def test_mart_country_reconciles_to_split(self):
        mart_total = sum(float(c["total_commitment"]) for c in self.countries)
        split_total = sum(float(l["amount_share"]) for l in self.links)
        self.assertAlmostEqual(mart_total, split_total, places=2)

    def test_one_row_per_country(self):
        iso3 = [c["iso3"] for c in self.countries]
        self.assertEqual(len(iso3), len(set(iso3)))

    def test_no_negative_commitment(self):
        self.assertTrue(all(float(c["total_commitment"]) >= 0 for c in self.countries))

    def test_need_index_within_bounds(self):
        for row in self.countries:
            if row["sdg_gap_index"]:
                self.assertGreaterEqual(float(row["sdg_gap_index"]), 0)
                self.assertLessEqual(float(row["sdg_gap_index"]), 100)

    def test_incomplete_countries_are_not_assigned_a_tercile(self):
        for row in self.countries:
            if row["need_complete"] == "0":
                self.assertIn(row["need_tercile"], ("", "None"))

    def test_only_three_quadrant_labels_plus_insufficient(self):
        allowed = {"high need / thin portfolio", "low need / heavy portfolio",
                   "aligned", "insufficient need data"}
        self.assertTrue({c["quadrant"] for c in self.countries} <= allowed)

    def test_priority_list_is_ordered_by_allocation_gap(self):
        gaps = [float(row["allocation_gap"]) for row in self.priority]
        self.assertEqual(gaps, sorted(gaps, reverse=True))
        self.assertEqual([int(r["priority_rank"]) for r in self.priority],
                         list(range(1, len(self.priority) + 1)))

    def test_priority_list_only_contains_measured_need(self):
        for row in self.priority:
            self.assertNotIn(row["sdg_gap_index"], ("", "None"))
            self.assertLessEqual(float(row["allocation_gap"]), 1.0)
            self.assertGreaterEqual(float(row["allocation_gap"]), -1.0)

    def test_financing_per_capita_is_consistent(self):
        for row in self.countries:
            if not row["population"] or not row["financing_pc"]:
                continue
            expected = float(row["active_commitment"]) / float(row["population"])
            self.assertAlmostEqual(float(row["financing_pc"]), expected, delta=1e-6)

    def test_allocation_gap_is_a_percentile_difference(self):
        for row in self.countries:
            if row["allocation_gap"] in ("", "None"):
                continue
            gap = float(row["allocation_gap"])
            self.assertAlmostEqual(gap, round(gap, 4), places=6)

    def test_health_metrics_are_all_populated(self):
        metrics = {row["metric"]: row["value"] for row in self.health}
        for key in ("total_operations", "total_value_usd", "countries_with_portfolio",
                    "share_operations_active", "sector_hhi"):
            self.assertIn(key, metrics)
            self.assertNotIn(metrics[key], ("", "None"))


class TestOperatingProfile(unittest.TestCase):
    """The operating profile must describe the same book as the health mart."""

    @classmethod
    def setUpClass(cls):
        cls.perf = read_csv(ROOT / "data" / "marts" / "mart_portfolio_performance.csv")
        cls.health = {row["metric"]: float(row["value"])
                      for row in read_csv(ROOT / "data" / "marts" / "mart_portfolio_health.csv")}

    def dim(self, name):
        return [row for row in self.perf if row["dimension"] == name]

    def test_status_buckets_sum_to_the_portfolio_total(self):
        total = sum(float(row["value"]) for row in self.dim("status"))
        self.assertAlmostEqual(total, self.health["total_value_usd"], delta=1.0)

    def test_every_dimension_covers_every_operation(self):
        for name in ("status", "cohort", "duration"):
            count = sum(int(row["n_ops"]) for row in self.dim(name))
            self.assertEqual(count, int(self.health["total_operations"]),
                             f"{name} buckets do not cover the book")

    def test_shares_add_up_to_one(self):
        for name in ("status", "cohort", "duration"):
            share = sum(float(row["share_value"]) for row in self.dim(name))
            self.assertAlmostEqual(share, 1.0, delta=0.01)

    def test_concentration_is_monotonic(self):
        values = [float(row["value"]) for row in self.dim("concentration")]
        self.assertEqual(values, sorted(values))
        self.assertLessEqual(values[-1], self.health["total_value_usd"] + 1)

    def test_active_share_within_bounds(self):
        for row in self.perf:
            if row["active_share"] in ("", "None"):
                continue
            self.assertGreaterEqual(float(row["active_share"]), 0)
            self.assertLessEqual(float(row["active_share"]), 1)


class TestReallocation(unittest.TestCase):
    """The scenario row and the arithmetic the page runs must agree."""

    @classmethod
    def setUpClass(cls):
        rows = read_csv(ROOT / "data" / "marts" / "mart_reallocation.csv")
        if not rows:
            raise unittest.SkipTest("empty scenario table")
        cls.scn = rows[0]
        cls.countries = read_csv(ROOT / "data" / "marts" / "mart_country.csv")
        cls.priority = read_csv(ROOT / "data" / "marts" / "mart_priority.csv")
        cls.total_active = sum(float(c["active_commitment"] or 0) for c in cls.countries)
        cls.donors = [c for c in cls.countries
                      if float(c["active_commitment"] or 0) > 0
                      and float(c["allocation_gap"] or 0) < 0]
        cls.donor_pop = sum(float(c["population"] or 0) for c in cls.donors)
        cls.recipient_pop = sum(float(c["population"] or 0) for c in cls.priority)

    def test_pool_is_the_stated_share_of_live_value(self):
        share = float(self.scn["share"])
        self.assertAlmostEqual(float(self.scn["pool_usd"]), share * self.total_active, delta=1.0)

    def test_donor_and_recipient_sets_are_as_declared(self):
        self.assertEqual(int(self.scn["n_donors"]), len(self.donors))
        self.assertEqual(int(self.scn["n_recipients"]), len(self.priority))
        self.assertAlmostEqual(float(self.scn["donor_population"]), self.donor_pop, delta=1.0)
        self.assertAlmostEqual(float(self.scn["recipient_population"]), self.recipient_pop, delta=1.0)

    def test_gain_and_cost_per_person_follow_the_page_formula(self):
        pool = float(self.scn["pool_usd"])
        self.assertAlmostEqual(float(self.scn["gain_per_person"]) / (pool / self.recipient_pop),
                               1.0, places=6)
        self.assertAlmostEqual(float(self.scn["donor_loss_per_person"]) / (pool / self.donor_pop),
                               1.0, places=6)

    def test_scenario_pool_is_smaller_than_live_value(self):
        self.assertLess(float(self.scn["pool_usd"]), self.total_active)


class TestDataQuality(unittest.TestCase):
    """A failed check must not be silently absorbed by the render step."""

    @classmethod
    def setUpClass(cls):
        cls.checks = read_csv(ROOT / "data" / "marts" / "mart_dq.csv")

    def test_every_check_passes_on_the_committed_snapshot(self):
        failing = [c["check_id"] for c in self.checks if c["status"] != "PASS"]
        self.assertEqual(failing, [], f"failing checks: {failing}")

    def test_check_ids_are_unique(self):
        ids = [c["check_id"] for c in self.checks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_check_suite_is_not_silently_shrinking(self):
        self.assertGreaterEqual(len(self.checks), 12)


class TestRobustness(unittest.TestCase):
    """The six readings must agree with the published ranking where they should."""

    @classmethod
    def setUpClass(cls):
        cls.rows = read_csv(ROOT / "data" / "marts" / "mart_robustness.csv")
        cls.country = {r["iso3"]: r for r in read_csv(ROOT / "data" / "marts" / "mart_country.csv")}

    def _variant(self, key):
        return [r for r in self.rows if r["variant"] == key]

    def test_all_six_readings_are_present(self):
        keys = {r["variant"] for r in self.rows}
        self.assertEqual(keys, {"equal", "no_poverty", "no_hunger", "no_water",
                                "no_energy", "worst"})

    def test_each_reading_ranks_the_same_population(self):
        sizes = {len(self._variant(k)) for k in
                 ("equal", "no_poverty", "no_hunger", "no_water", "no_energy", "worst")}
        self.assertEqual(len(sizes), 1)
        self.assertGreater(sizes.pop(), 150)

    def test_baseline_rerun_reproduces_the_published_gap(self):
        # The equal-weight column is a re-implementation of model 25. If the two
        # ever disagree, the matrix is drawing a different ranking from the
        # table above it.
        worst = 0.0
        for r in self._variant("equal"):
            published = float(self.country[r["iso3"]]["allocation_gap"])
            worst = max(worst, abs(float(r["allocation_gap"]) - published))
        self.assertLess(worst, 0.0002)

    def test_every_reading_produces_a_top_25(self):
        for key in ("equal", "no_poverty", "no_hunger", "no_water", "no_energy", "worst"):
            in_list = [r for r in self._variant(key) if r["in_top25"] == "1"]
            self.assertEqual(len(in_list), 25, key)

    def test_ranks_are_unique_within_a_reading(self):
        for key in ("equal", "no_poverty", "no_hunger", "no_water", "no_energy", "worst"):
            ranks = [int(r["rank"]) for r in self._variant(key)]
            self.assertEqual(len(ranks), len(set(ranks)), key)
            self.assertEqual(sorted(ranks)[0], 1, key)

    def test_shortlist_rank_marks_exactly_the_25(self):
        marked = {r["iso3"] for r in self.rows if r["shortlist_rank"]}
        self.assertEqual(len(marked), 25)


class TestConvergence(unittest.TestCase):
    """The drift layer is an arithmetic claim, so it gets arithmetic tests."""

    @classmethod
    def setUpClass(cls):
        cls.rows = read_csv(ROOT / "data" / "marts" / "mart_convergence.csv")
        cls.country = {r["iso3"]: r for r in read_csv(ROOT / "data" / "marts" / "mart_country.csv")}

    def test_one_row_per_country(self):
        iso = [r["iso3"] for r in self.rows]
        self.assertEqual(len(iso), len(set(iso)))

    def test_delta_is_the_difference_of_the_two_readings(self):
        for r in self.rows:
            drift = float(r["delta_pp"]) - (float(r["need_latest"]) - float(r["need_2015"]))
            self.assertLess(abs(drift), 0.02, r["iso3"])

    def test_readings_sit_inside_the_index_bounds(self):
        for r in self.rows:
            for column in ("need_2015", "need_latest"):
                value = float(r[column])
                self.assertGreaterEqual(value, 0.0, r["iso3"])
                self.assertLessEqual(value, 100.0, r["iso3"])

    def test_latest_reading_is_recent(self):
        years = [int(r["latest_year"]) for r in self.rows]
        self.assertGreaterEqual(min(years), 2021)
        self.assertLessEqual(max(years), 2024)

    def test_post_2015_money_is_per_person(self):
        for r in self.rows:
            population = float(r["population"])
            self.assertGreater(population, 0, r["iso3"])
            implied = float(r["post2015_value"]) / population
            self.assertLess(abs(float(r["post2015_pc"]) - implied), 0.1, r["iso3"])

    def test_enough_countries_report_both_years(self):
        self.assertGreaterEqual(len(self.rows), 100)


class TestRenderedPage(unittest.TestCase):
    """The page is the deliverable, so its structure is asserted, not assumed."""

    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")

    def test_sections_render_in_order(self):
        ids = ["overview", "field", "countries", "robustness", "trend", "portfolio",
               "operating", "method"]
        positions = [self.html.index('id="%s"' % i) for i in ids]
        self.assertEqual(positions, sorted(positions))

    def test_search_has_a_result_list(self):
        self.assertIn('id="results"', self.html)
        self.assertIn("playSearch", self.html)

    def test_payload_is_embedded_once(self):
        self.assertEqual(self.html.count("const DATA = "), 1)

    def test_the_two_new_panels_have_somewhere_to_draw(self):
        for marker in ('id="robusttable"', 'id="rob-summary"', 'id="conv"', 'id="movertable"'):
            self.assertIn(marker, self.html)

    def test_identity_and_data_links_go_to_different_places(self):
        # "Aid Atlas" returns to the top of the page; "Data" leaves for the CSV marts.
        self.assertIn('<a class="brand" href="#top"', self.html)
        self.assertIn('<div class="topbar" id="top">', self.html)
        self.assertIn('class="datalink"', self.html)
        head = self.html.split('class="datalink"', 1)[1][:200]
        self.assertIn('href="#data"', head)
        self.assertIn('id="data"', self.html)

    def test_the_field_plate_draws_one_square_per_country(self):
        # The plate is drawn at runtime from the payload; assert the scaffolding and the rule.
        for marker in ('<section class="field" id="field">', 'id="fgrid"', 'id="ffield"',
                       'class="fcap"', "band.className = 'fband'", "t.className = 'ftile'"):
            self.assertIn(marker, self.html)
        self.assertIn("DATA.countries.filter(d => d.complete && d.gap !== null)", self.html)

    def test_four_stops_link_to_the_four_sections(self):
        # The on-ramp is the only navigation for a reader who arrives cold.
        stops = ['href="#countries"', 'href="#robustness"',
                 'href="#trend"', 'href="#method"']
        block = self.html.split('class="start"', 1)[1].split("</div>", 1)[0]
        for stop in stops:
            self.assertIn(stop, block)

    def test_country_file_exists_and_is_clickable(self):
        for marker in ('id="cf"', 'id="cf-body"', 'id="cf-close"', 'id="cf-go"',
                       'function openCountry('):
            self.assertIn(marker, self.html)
        # every row of the short list carries the key the drawer opens on
        self.assertIn("tr.dataset.iso = ", self.html)
        self.assertIn("tr.addEventListener('click'", self.html)

    def test_weights_panel_has_four_sliders_and_a_table(self):
        # The sliders are built at runtime from KEYS, so assert on that source.
        for marker in ('id="wsliders"', 'id="wtable"', 'id="wnote2"', 'id="wreset"'):
            self.assertIn(marker, self.html)
        self.assertIn('type="range"', self.html)
        keys = self.html.split("const KEYS = [", 1)[1].split("]", 1)[0]
        self.assertEqual(keys.count("'"), 8)  # four keys, opening and closing quote
        self.assertIn("gap_poverty", keys)
        self.assertIn("gap_energy", keys)

    def test_matrix_is_sortable_and_filterable(self):
        self.assertIn('id="robshow25"', self.html)
        self.assertIn('id="robsort"', self.html)
        self.assertIn("th.className = 'scol'", self.html)
        self.assertIn("th.dataset.col = i", self.html)
        self.assertIn("head.querySelectorAll('th.scol')", self.html)

    def test_plain_words_glossary_covers_the_terms_the_page_uses(self):
        self.assertIn('class="glossary"', self.html)
        blocks = self.html.split('class="glossary"', 1)[1]
        self.assertGreaterEqual(blocks.count("<dt>"), 7)


if __name__ == "__main__":
    unittest.main()
