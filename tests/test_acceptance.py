import unittest
from datetime import date
from streamlit.testing.v1 import AppTest
from scripts.verify_end_to_end import uploaded_files
from demand_planner.data.loading import load_csv_bundle
from demand_planner.data.validation import validate_dataset
from demand_planner.analysis import run_model_analysis
from demand_planner.domain import PlanningSettings
from tests.test_uncertainty import render_forecast
from tests.test_inventory import render_inventory


class UploadedAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = validate_dataset(load_csv_bundle(uploaded_files(), "Acceptance upload"), as_of=date(2026,10,10))
        cls.result = run_model_analysis(cls.report.dataset, PlanningSettings())

    def test_zero_limited_gapped_and_absent_sales_are_distinct(self):
        self.assertFalse(self.report.has_errors)
        future = self.result.future_forecasts
        self.assertTrue(future.loc[future.product_id == "002"].predicted_units.eq(0).all())
        for product in ("003", "005", "010"):
            self.assertTrue(future.loc[future.product_id == product].predicted_units.isna().all())
        self.assertTrue(future.loc[future.product_id == "004"].predicted_units.eq(3).all())
        self.assertTrue(future.loc[future.product_id == "004"].method.eq("recent_mean_28d_fallback").all())

    def test_forecast_ui_short_history_is_unavailable_not_zero(self):
        app = AppTest.from_function(render_forecast, args=(self.report.dataset, self.result)).run()
        app.selectbox(key=f"forecast_product_{self.report.dataset.fingerprint}").select("003").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "Unavailable")
        self.assertTrue(any("Forecast unavailable" in item.value for item in app.warning))

    def test_inventory_ui_reports_unavailable_products(self):
        app = AppTest.from_function(render_inventory, args=(self.report.dataset, self.result)).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("3 products" in item.value for item in app.warning))

    def test_review_callback_refreshes_data_quality(self):
        from tests.test_validation import render_upload_flow
        files = uploaded_files()
        app = AppTest.from_function(render_upload_flow, args=(files,)).run()
        # Exercise the actual sidebar callback separately with initialized state.
        from tests.test_foundation import PROJECT_ROOT
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run()
        app.session_state["validation_report"] = self.report
        app.session_state["dataset"] = self.report.dataset
        app.number_input(key="review_period_days").set_value(27).run()
        refreshed = app.session_state["validation_report"]
        self.assertEqual(refreshed.default_review_period_days, 27)
        self.assertFalse(refreshed.summary.inventory_ready.any())
        self.assertIsNone(app.session_state["results"])
