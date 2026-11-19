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


if __name__ == "__main__":
    unittest.main()
