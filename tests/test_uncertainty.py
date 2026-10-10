import tempfile
import unittest
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from demand_planner.forecasting.uncertainty import estimate_ranges, add_ranges
from demand_planner.analysis import run_model_analysis
from demand_planner.artifacts import save_analysis
from demand_planner.domain import PlanningSettings
from demand_planner.data.exporting import csv_bytes
from demand_planner.ui.forecasting import forecast_chart
from test_regression import long_dataset


def candidates_fixture():
    origins = pd.date_range("2025-01-01", periods=6, freq="7D")
    rows = []
    for fold, origin in enumerate(origins, start=1):
        for lead in range(1, 8):
            error = (fold - 1) * 7 + lead - 1 if fold <= 3 else [2, 18, 17][(lead - 1) % 3]
            rows.append({"product_id": "001", "horizon_days": 7, "forecast_origin": origin,
                         "date": origin + pd.Timedelta(days=lead), "fold": fold,
                         "partition": "development" if fold <= 3 else "audit", "actual_units": 100 + error,
                         "predicted_units": 100., "predicted_units_ml": 95.,
                         "score_eligible": True, "score_eligible_ml": True})
    return pd.DataFrame(rows)


def render_forecast(dataset=None, results=None):
    import streamlit as st
    from demand_planner.ui.state import initialize_state
    from demand_planner.ui.forecasting import forecasting_screen
    initialize_state()
    st.session_state.dataset = dataset
    st.session_state.results = results
    forecasting_screen()


class PredictionRangeTests(unittest.TestCase):
    def test_quantile_rank_and_independent_observed_coverage(self):
        record, audit = estimate_ranges(candidates_fixture(), "001", 7, "baseline")
        self.assertEqual(record["calibration_days"], 21)
        self.assertEqual(record["error_radius_units"], 17)
        self.assertEqual(record["audit_scored_days"], 21)
        self.assertEqual(record["audit_covered_days"], 15)
        self.assertAlmostEqual(record["audit_coverage_percent"], 100 * 15 / 21)
        self.assertTrue(audit.range_covered.eq(audit.actual_units.le(117)).all())

    def test_future_audit_errors_cannot_change_radius(self):
        rows = candidates_fixture()
        before, _ = estimate_ranges(rows, "001", 7, "baseline")
        rows.loc[rows.partition.eq("audit"), "actual_units"] = 10000
        after, _ = estimate_ranges(rows, "001", 7, "baseline")
        self.assertEqual(before["error_radius_units"], after["error_radius_units"])
        self.assertEqual(after["audit_coverage_percent"], 0)

    def test_selected_model_errors_are_used_and_stockouts_excluded(self):
        rows = candidates_fixture()
        baseline, _ = estimate_ranges(rows, "001", 7, "baseline")
        ml, _ = estimate_ranges(rows, "001", 7, "ml")
        self.assertEqual(ml["error_radius_units"], baseline["error_radius_units"] + 5)
        rows.loc[0, "actual_units"] = 100000
        rows.loc[0, ["score_eligible", "score_eligible_ml"]] = False
        rows.loc[21, ["score_eligible", "score_eligible_ml"]] = False
        record, _ = estimate_ranges(rows, "001", 7, "baseline")
        self.assertEqual(record["calibration_days"], 20)
        self.assertEqual(record["audit_scored_days"], 20)
        self.assertLess(record["error_radius_units"], 30)

    def test_clipping_preserves_order_point_and_unavailable_rows(self):
        record, _ = estimate_ranges(candidates_fixture(), "001", 7, "baseline")
        forecast = pd.DataFrame({"predicted_units": [2., 0., -2., np.nan]})
        result = add_ranges(forecast, record)
        self.assertEqual(result.estimated_lower_units.iloc[:3].tolist(), [0., 0., 0.])
        self.assertEqual(result.estimated_upper_units.iloc[:3].tolist(), [19., 17., 17.])
        self.assertTrue((result.estimated_lower_units.iloc[:3] <= result.predicted_units.iloc[:3]).all())
        self.assertTrue((result.predicted_units.iloc[:3] <= result.estimated_upper_units.iloc[:3]).all())
        self.assertTrue(result.estimated_upper_units.iloc[3:].isna().all())
        self.assertEqual(result.interval_status.iloc[3], "unavailable")

    def test_insufficient_calibration_and_no_audit_are_explicit(self):
        rows = candidates_fixture()
        rows.loc[:2, "score_eligible"] = False
        record, _ = estimate_ranges(rows, "001", 7, "baseline")
        self.assertEqual(record["interval_status"], "unavailable")
        self.assertIsNone(record["error_radius_units"])
        self.assertIsNone(record["audit_coverage_percent"])
        rows = candidates_fixture().iloc[:21]
        record, _ = estimate_ranges(rows, "001", 7, "baseline")
        self.assertEqual(record["interval_status"], "estimated")
        self.assertIsNone(record["audit_coverage_percent"])

    def test_zero_demand_and_zero_width_are_not_percentage_confidence(self):
        rows = candidates_fixture()
        rows[["actual_units", "predicted_units", "predicted_units_ml"]] = 0.
        record, _ = estimate_ranges(rows, "001", 7, "baseline")
        self.assertEqual(record["error_radius_units"], 0.)
        self.assertEqual(record["audit_coverage_percent"], 100.)
        self.assertIsNone(record["audit_wape_percent"])
        self.assertEqual(record["audit_mae"], 0.)

    def test_calibration_cannot_overlap_audit_forecast_period(self):
        rows = candidates_fixture()
        rows.loc[0, "date"] = rows.date.max()
        with self.assertRaisesRegex(ValueError, "Calibration targets"):
            estimate_ranges(rows, "001", 7, "baseline")


class ForecastScreenTests(unittest.TestCase):
    def test_empty_and_not_yet_run_states(self):
        for dataset in (None, long_dataset()):
            app = AppTest.from_function(render_forecast, args=(dataset, None)).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.info)

    def test_all_horizons_metrics_plot_values_and_csv_precision(self):
        dataset = long_dataset()
        dataset.tables["sales"].loc[340, "units_sold"] = 17
        result = run_model_analysis(dataset, PlanningSettings())
        app = AppTest.from_function(render_forecast, args=(dataset, result)).run()
        for horizon in (7, 14, 28):
            app.selectbox(key=f"forecast_view_horizon_{dataset.fingerprint}").select(horizon).run()
            self.assertFalse(app.exception)
            rows = result.future_forecasts.loc[result.future_forecasts.horizon_days == horizon]
            self.assertEqual(len(rows), horizon)
            self.assertEqual(app.metric[0].value, f"{rows.predicted_units.sum():,.2f}")
            self.assertEqual(len(app.dataframe[-1].value), horizon)
            self.assertEqual(app.session_state["horizon_days"], 14)
            fig = forecast_chart(dataset.tables["sales"], rows)
            self.assertEqual(list(fig.data[1].y), rows.estimated_upper_units.tolist())
            self.assertEqual(list(fig.data[2].y), rows.estimated_lower_units.tolist())
            self.assertEqual(list(fig.data[3].y), rows.predicted_units.tolist())
            exported = pd.read_csv(__import__("io").BytesIO(csv_bytes(rows)))
            np.testing.assert_allclose(exported.predicted_units, rows.predicted_units, atol=1e-12)
        self.assertEqual(len(result.future_forecasts), 49)
        self.assertEqual(len(result.interval_evaluation), 3)
        with tempfile.TemporaryDirectory() as root:
            directory = save_analysis(dataset, result, root)
            self.assertTrue((directory / "interval_evaluation.csv").exists())
            self.assertTrue((directory / "future_forecasts.csv").exists())
            from scripts.reproduce_run import reproduce
            self.assertEqual(reproduce(directory, retrain=True), 14)

    def test_no_history_and_short_history_have_no_false_totals_or_ranges(self):
        dataset = long_dataset()
        dataset.tables["sales"] = dataset.tables["sales"].iloc[:13]
        result = run_model_analysis(dataset, PlanningSettings())
        app = AppTest.from_function(render_forecast, args=(dataset, result)).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "Unavailable")
        self.assertTrue(app.warning)
        self.assertTrue(result.future_forecasts.estimated_upper_units.isna().all())
        dataset.tables["sales"] = long_dataset().tables["sales"].iloc[:30]
        result = run_model_analysis(dataset, PlanningSettings())
        app = AppTest.from_function(render_forecast, args=(dataset, result)).run()
        self.assertFalse(app.exception)
        self.assertNotEqual(app.metric[0].value, "Unavailable")
        self.assertTrue(any("Prediction range unavailable" in item.value for item in app.info))
        dataset.tables["products"] = pd.DataFrame({"product_id": ["001", "002"], "product_name": ["Test", "No history"]})
        result = run_model_analysis(dataset, PlanningSettings())
        app = AppTest.from_function(render_forecast, args=(dataset, result)).run()
        app.selectbox(key=f"forecast_product_{dataset.fingerprint}").select("002").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "Unavailable")


if __name__ == "__main__":
    unittest.main()
