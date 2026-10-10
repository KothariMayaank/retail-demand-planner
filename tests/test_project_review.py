"""Regression cases found during the full project review."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from demand_planner.analysis import run_model_analysis
from demand_planner.artifacts import save_analysis
from demand_planner.domain import PlanningSettings
from demand_planner.evaluation.backtesting import rolling_backtest
from demand_planner.evaluation.selection import compare_models
from demand_planner.evaluation.metrics import forecast_metrics
from demand_planner.evaluation.reporting import audit_scorecard
from demand_planner.forecasting.regression import forecast_regression
from demand_planner.inventory.planning import plan_inventory
from demand_planner.ui.cache import data_digest
from scripts.prepare_deployment import FIXED, release_files
from scripts.reproduce_run import reproduce
from tests.test_baseline import sales_fixture
from tests.test_inventory import fixture
from tests.test_regression import long_dataset


class ProjectReviewTests(unittest.TestCase):
    def test_rmse_and_signed_bias_expose_different_errors(self):
        metrics = forecast_metrics([0, 2, 4], [1, 4, 3])
        self.assertAlmostEqual(metrics["rmse"], 2 ** .5)
        self.assertAlmostEqual(metrics["bias_units"], 2 / 3)
        self.assertIsNone(forecast_metrics([], [])["rmse"])

    def test_scorecard_pools_errors_and_uses_frozen_selection(self):
        rows = pd.DataFrame({"product_id": ["A", "B"], "horizon_days": [7, 7],
                             "partition": ["audit", "audit"], "date": ["2025-01-01"] * 2,
                             "actual_units": [100., 10.], "predicted_units": [80., 20.],
                             "predicted_units_ml": [90., 10.], "score_eligible": [True, True],
                             "score_eligible_ml": [True, True]})
        choices = pd.DataFrame({"product_id": ["A", "B"], "horizon_days": [7, 7],
                                "selected_model": ["ml", "baseline"]})
        result = audit_scorecard(rows, choices).iloc[0]
        self.assertAlmostEqual(result.baseline_wape_percent, 100 * 30 / 110)
        self.assertAlmostEqual(result.selected_wape_percent, 100 * 20 / 110)
        self.assertEqual(result.selected_bias_units, 0)
        self.assertEqual((result.products_improved, result.products_worse, result.products_tied), (1, 0, 1))
        # An unselected unavailable challenger must not suppress baseline policy scores.
        rows.loc[1, "score_eligible_ml"] = False
        self.assertEqual(audit_scorecard(rows, choices).scored_days.iloc[0], 2)

    def test_scorecard_zero_and_unavailable_denominators(self):
        sales = sales_fixture(90)
        sales["units_sold"] = 0
        baseline, _, _ = rolling_backtest(sales, "001", 7)
        ml, _, _ = rolling_backtest(sales, "001", 7, forecaster=forecast_regression)
        joined, decision = compare_models(baseline, ml, "001", 7)
        row = audit_scorecard(joined, pd.DataFrame([decision])).iloc[0]
        self.assertEqual(row.selected_mae, 0)
        self.assertTrue(pd.isna(row.selected_wape_percent))
        self.assertTrue(pd.isna(row.mae_improvement_percent))
        joined["score_eligible"] = False
        row = audit_scorecard(joined, pd.DataFrame([decision])).iloc[0]
        self.assertEqual(row.scored_days, 0)
        self.assertTrue(pd.isna(row.selected_mae))

    def test_cache_includes_source_provenance(self):
        dataset, _ = fixture()
        self.assertNotEqual(data_digest(dataset), data_digest(replace(dataset, source="Synthetic sample")))

    def test_replay_preserves_na_like_identifiers_and_unknown_stock_flags(self):
        dataset = long_dataset()
        for frame in dataset.tables.values():
            frame["product_id"] = "NA"
        dataset.tables["sales"].loc[0, "stockout_flag"] = pd.NA
        result = run_model_analysis(dataset, PlanningSettings())
        with tempfile.TemporaryDirectory() as directory:
            run = save_analysis(dataset, result, directory)
            self.assertEqual(reproduce(run, retrain=True), 14)

    def test_baseline_audit_exists_when_ml_is_unavailable(self):
        sales = sales_fixture(90)
        baseline, _, _ = rolling_backtest(sales, "001", 7)
        ml, _, _ = rolling_backtest(sales, "001", 7, forecaster=forecast_regression)
        _, decision = compare_models(baseline, ml, "001", 7)
        self.assertEqual(decision["selected_model"], "baseline")
        self.assertEqual(decision["audit_ml_scored_days"], 0)
        self.assertEqual(decision["audit_selected_scored_days"], 21)
        self.assertEqual(decision["audit_selected_mae"], 0)

    def test_lost_sales_before_delivery_are_not_backordered(self):
        dataset, forecasts = fixture(stock=0, demand=10, lead=3, review=4)
        dataset.tables["products"][["pack_size", "minimum_order_qty"]] = [1, 0]
        _, summary = plan_inventory(dataset, forecasts, PlanningSettings(safety_stock_policy="none"))
        self.assertEqual(summary.raw_order_units.iloc[0], 40)
        self.assertEqual(summary.suggested_order_units.iloc[0], 40)
        self.assertEqual(summary.pre_arrival_lost_units.iloc[0], 30)

    def test_late_receipt_cannot_cancel_order_needed_to_bridge_gap(self):
        dataset, forecasts = fixture(stock=0, demand=10, lead=3, review=4, receipts=[(6, 100)])
        dataset.tables["products"][["pack_size", "minimum_order_qty"]] = [1, 0]
        _, summary = plan_inventory(dataset, forecasts, PlanningSettings(safety_stock_policy="none"))
        self.assertEqual(summary.suggested_order_units.iloc[0], 20)

    def test_orders_match_independent_exhaustive_delivery_simulation(self):
        for stock, receipts in ((0, ()), (3, ((5, 100),)), (30, ()),
                                (5, ((7, 5), (7, 6), (8, 50))), (2, ((2, 5), (6, 9)))):
            with self.subTest(stock=stock, receipts=receipts):
                dataset, forecasts = fixture(stock=stock, receipts=receipts)
                _, summary = plan_inventory(dataset, forecasts, PlanningSettings())
                # Enumerate legal supplier orders, then run an independent stock ledger.
                feasible = []
                for quantity in [0] + list(range(12, 301, 6)):
                    balance, after_arrival_loss = float(stock), 0.
                    for day in range(1, 8):
                        balance += sum(amount for arrival, amount in receipts if arrival == day)
                        if day == 4:
                            balance += quantity
                        if day >= 4:
                            after_arrival_loss += max(0., 2.5 - balance)
                        balance = max(0., balance - 2.5)
                    if after_arrival_loss <= 1e-9 and balance >= 5 - 1e-9:
                        feasible.append(quantity)
                self.assertEqual(summary.suggested_order_units.iloc[0], min(feasible))

    def test_release_rejects_false_synthetic_declaration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in FIXED:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            sample = root / "data/sample"
            sample.mkdir(parents=True)
            (sample / "manifest.json").write_text(json.dumps({"is_synthetic": False}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "synthetic"):
                release_files(root)
