"""Integration checks for cache isolation, exports and calculation/display agreement."""
from dataclasses import replace
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import pandas as pd
from streamlit.testing.v1 import AppTest
from demand_planner.domain import PlanningSettings, AnalysisResults
from demand_planner.ui.cache import cached_analysis, _analysis_cached, data_digest
from demand_planner.data.exporting import results_zip
from tests.test_inventory import fixture, render_inventory
from demand_planner.inventory.planning import plan_inventory


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        _analysis_cached.clear()

    def tearDown(self):
        _analysis_cached.clear()

    def test_cache_reuses_result_and_returns_isolated_copies(self):
        dataset, _ = fixture()
        settings = PlanningSettings()
        result = AnalysisResults(dataset.fingerprint, settings, daily_forecasts=pd.DataFrame({"predicted_units": [2.5]}))
        with patch("demand_planner.ui.cache.run_model_analysis", return_value=result) as calculate:
            first = cached_analysis(dataset, settings)
            first.daily_forecasts.loc[0, "predicted_units"] = 999
            second = cached_analysis(dataset, settings)
            self.assertEqual(calculate.call_count, 1)
            self.assertEqual(second.daily_forecasts.predicted_units.iloc[0], 2.5)
            self.assertIsNone(second.artifact_directory)

    def test_cache_invalidates_for_values_settings_and_code(self):
        dataset, _ = fixture()
        settings = PlanningSettings()
        with patch("demand_planner.ui.cache.run_model_analysis", return_value=AnalysisResults(dataset.fingerprint, settings)) as calculate:
            cached_analysis(dataset, settings)
            # Same declared fingerprint, different actual inventory must still miss the cache.
            dataset.tables["inventory"].loc[0, "on_hand_units"] += 1
            cached_analysis(dataset, settings)
            cached_analysis(dataset, replace(settings, safety_stock_days=3.0))
            cached_analysis(dataset, replace(settings, review_period_days=5))
            with patch("demand_planner.ui.cache.engine_digest", return_value="changed-code"):
                cached_analysis(dataset, settings)
            self.assertEqual(calculate.call_count, 5)

    def test_all_rows_are_hashed_even_large_inputs(self):
        dataset, _ = fixture()
        dataset.tables["sales"] = pd.concat([dataset.tables["sales"]] * 15000, ignore_index=True)
        previous = data_digest(dataset)
        dataset.tables["sales"].loc[14999, "units_sold"] = 555
        self.assertNotEqual(previous, data_digest(dataset))

    def test_analysis_failure_clears_results_and_explains_problem(self):
        from tests.test_baseline import render_completed_screen
        dataset, _ = fixture()
        app = AppTest.from_function(render_completed_screen, args=(dataset, None, "data_setup")).run()
        with patch("demand_planner.ui.screens.cached_analysis", side_effect=ValueError("Correct the inventory snapshot date.")):
            next(button for button in app.button if button.label == "Run analysis").click().run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state["results"])
        self.assertTrue(any("Correct the inventory snapshot" in item.value for item in app.error))

    def test_zip_values_settings_and_formula_safety(self):
        dataset, forecasts = fixture()
        projections, orders = plan_inventory(dataset, forecasts, PlanningSettings())
        orders.loc[0, "product_name"] = "=malicious formula"
        result = AnalysisResults(dataset.fingerprint, PlanningSettings(), daily_forecasts=forecasts,
                                 inventory_projection=projections, reorder_suggestions=orders)
        with ZipFile(BytesIO(results_zip(result))) as archive:
            saved = pd.read_csv(archive.open("reorder_suggestions.csv"), dtype={"product_id": str})
            self.assertEqual(saved.suggested_order_units.iloc[0], orders.suggested_order_units.iloc[0])
            self.assertEqual(saved.product_name.iloc[0], "'=malicious formula")
            raw = pd.read_csv(archive.open("daily_forecasts.csv"))
            self.assertEqual(raw.predicted_units.tolist(), forecasts.predicted_units.tolist())
            self.assertEqual(json.loads(archive.read("settings.json"))["safety_stock_days"], 2.0)
            self.assertIn(b"not guarantees", archive.read("README.txt"))

    def test_overview_and_inventory_agree_on_order_and_shortage_counts(self):
        from tests.test_baseline import render_completed_screen
        dataset, forecasts = fixture()
        projections, orders = plan_inventory(dataset, forecasts, PlanningSettings())
        result = AnalysisResults(dataset.fingerprint, PlanningSettings(), daily_forecasts=forecasts,
                                 inventory_projection=projections, reorder_suggestions=orders)
        overview = AppTest.from_function(render_completed_screen, args=(dataset, result, "overview")).run()
        inventory = AppTest.from_function(render_inventory, args=(dataset, result)).run()
        self.assertFalse(overview.exception)
        self.assertFalse(inventory.exception)
        self.assertEqual(overview.metric[1].value, inventory.metric[0].value)
        self.assertEqual(overview.metric[2].value, inventory.metric[1].value)
        self.assertEqual(inventory.metric[2].value, str(int(orders.suggested_order_units.sum())))
        self.assertEqual(inventory.metric[5].value, f"{orders.target_stock_units.iloc[0]:,.2f}")
