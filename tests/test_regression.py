import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest
from demand_planner.forecasting.regression import training_features, fit_regression, predict_artifact, forecast_regression
from demand_planner.forecasting.baseline import forecast_baseline
from demand_planner.evaluation.backtesting import rolling_backtest
from demand_planner.evaluation.selection import compare_models
from demand_planner.analysis import run_model_analysis
from demand_planner.artifacts import save_analysis
from demand_planner.domain import DatasetBundle, PlanningSettings
from scripts.reproduce_run import reproduce
from test_baseline import sales_fixture, render_results, render_completed_screen


def long_dataset():
    sales = sales_fixture(350)
    return DatasetBundle({"sales": sales, "products": pd.DataFrame({"product_id": ["001"], "product_name": ["Test"]}),
                          "inventory": pd.DataFrame({"product_id": ["001"]}),
                          "receipts": pd.DataFrame(columns=["product_id"])}, "Test", "regression-fixture")


class RegressionTests(unittest.TestCase):
    def test_feature_row_uses_prior_values_not_same_day_target(self):
        sales = sales_fixture(150)
        sales["units_sold"] = np.arange(150)
        _, _, features, _ = training_features(sales, "001", sales.date.max())
        row = features.iloc[40]
        self.assertEqual(row.lag_1, 39)
        self.assertEqual(row.lag_28, 12)
        self.assertEqual(row.mean_7, np.mean(np.arange(33, 40)))
        changed = sales.copy()
        changed.loc[40:, "units_sold"] = 99999
        _, _, after, _ = training_features(changed, "001", sales.date.max())
        assert_frame_equal(features.iloc[:41], after.iloc[:41])

    def test_cutoff_isolates_fitting_scaler_flags_and_features(self):
        sales = sales_fixture(300)
        origin = sales.date.iloc[149]
        expected = fit_regression(sales.iloc[:150], "001", origin)
        sales.loc[150:, "units_sold"] = 100000
        sales.loc[150:, "stockout_flag"] = True
        self.assertEqual(expected, fit_regression(sales, "001", origin))
        for horizon in (7, 14, 28):
            result = forecast_regression(sales, "001", origin, horizon)
            self.assertEqual(result.date.tolist(), list(pd.date_range(origin + pd.Timedelta(days=1), periods=horizon)))
            self.assertTrue(np.isfinite(result.predicted_units).all())
            self.assertTrue(result.predicted_units.ge(0).all())

    def test_stockout_signal_substitution_is_causal_and_targets_excluded(self):
        sales = sales_fixture(150)
        sales.loc[35, "stockout_flag"] = True
        sales.loc[35, "units_sold"] = 90000
        _, signal, _, eligible = training_features(sales, "001", sales.date.max())
        self.assertAlmostEqual(signal.iloc[35], sales.units_sold.iloc[:35].mean())
        self.assertFalse(eligible.iloc[35])
        sales.loc[36:, "units_sold"] = 100000
        _, after, _, _ = training_features(sales, "001", sales.date.max())
        self.assertEqual(signal.iloc[35], after.iloc[35])

    def test_ridge_solution_matches_independent_augmented_least_squares(self):
        sales = sales_fixture(150)
        training, _, features, eligible = training_features(sales, "001", sales.date.max())
        model = fit_regression(sales, "001", sales.date.max())
        x = features.loc[eligible].to_numpy()
        np.testing.assert_allclose(model["mean"], x.mean(axis=0))
        z = (x - model["mean"]) / model["scale"]
        y = training.loc[eligible, "observed_units"].to_numpy() - model["intercept"]
        augmented = np.vstack([z, np.sqrt(model["alpha"]) * np.eye(z.shape[1])])
        expected = np.linalg.lstsq(augmented, np.concatenate([y, np.zeros(z.shape[1])]), rcond=None)[0]
        np.testing.assert_allclose(model["coefficients"], expected, atol=1e-10)

    def test_recursive_predictions_use_own_previous_predictions(self):
        model = fit_regression(sales_fixture(150), "001", pd.Timestamp("2025-05-30"))
        # Controlled lag-1-only model: each day equals prior signal + 1.
        model["mean"] = [0.0] * len(model["features"])
        model["scale"] = [1.0] * len(model["features"])
        model["coefficients"] = [float(name == "lag_1") for name in model["features"]]
        model["intercept"] = 1.0
        model["signal_tail"] = [2.0] * 28
        self.assertEqual(predict_artifact(model, 7).predicted_units.tolist(), [3., 4., 5., 6., 7., 8., 9.])
        assert_frame_equal(predict_artifact(model, 28), predict_artifact(json.loads(json.dumps(model)), 28))

    def test_short_history_gaps_zero_sales_and_price_promotion_exclusion(self):
        short = sales_fixture(117)
        self.assertTrue(forecast_regression(short, "001", short.date.max(), 7).predicted_units.isna().all())
        sales = sales_fixture(150)
        self.assertTrue(forecast_regression(sales.drop(index=50), "001", sales.date.max(), 7).predicted_units.isna().all())
        expected = fit_regression(sales, "001", sales.date.max())
        sales["price"] = np.arange(150)
        sales["promotion"] = True
        self.assertEqual(expected, fit_regression(sales, "001", sales.date.max()))
        sales["units_sold"] = 0
        self.assertTrue(forecast_regression(sales, "001", sales.date.max(), 28).predicted_units.eq(0).all())

    def test_same_origins_targets_and_stockout_scores_as_baseline(self):
        sales = sales_fixture(350)
        sales.loc[340, "stockout_flag"] = True
        for horizon in (7, 14, 28):
            baseline, _, _ = rolling_backtest(sales, "001", horizon)
            ml, _, _ = rolling_backtest(sales, "001", horizon, forecaster=forecast_regression)
            assert_frame_equal(baseline[["forecast_origin", "date", "fold", "score_eligible"]],
                               ml[["forecast_origin", "date", "fold", "score_eligible"]])


class SelectionTests(unittest.TestCase):
    def candidates(self):
        baseline, _, _ = rolling_backtest(sales_fixture(350), "001", 7)
        baseline["predicted_units"] = baseline.actual_units + 2
        ml = baseline.copy()
        ml["predicted_units"] = ml.actual_units + 1
        return baseline, ml

    def test_improvement_threshold_ties_and_zero_baseline_retain_baseline(self):
        baseline, ml = self.candidates()
        _, record = compare_models(baseline, ml, "001", 7)
        self.assertEqual(record["selected_model"], "ml")
        self.assertEqual(record["development_improvement_percent"], 50)
        ml["predicted_units"] = baseline.actual_units + 1.95
        self.assertEqual(compare_models(baseline, ml, "001", 7)[1]["selected_model"], "baseline")
        ml["predicted_units"] = baseline.predicted_units
        self.assertEqual(compare_models(baseline, ml, "001", 7)[1]["selected_model"], "baseline")
        baseline["predicted_units"] = baseline.actual_units
        self.assertEqual(compare_models(baseline, ml, "001", 7)[1]["selected_model"], "baseline")

    def test_audit_actuals_cannot_change_selection_and_decision_predates_audit(self):
        baseline, ml = self.candidates()
        joined, before = compare_models(baseline, ml, "001", 7)
        self.assertLessEqual(before["selection_available_at"], joined.loc[joined.partition.eq("audit"), "forecast_origin"].min())
        baseline.loc[baseline.fold > 3, "actual_units"] = 99999
        ml.loc[ml.fold > 3, "predicted_units"] = 0
        _, after = compare_models(baseline, ml, "001", 7)
        self.assertEqual(before["selected_model"], after["selected_model"])
        self.assertEqual(before["development_ml_mae"], after["development_ml_mae"])
        self.assertNotEqual(before["audit_ml_mae"], after["audit_ml_mae"])
        self.assertTrue(after["audit_note"])

    def test_missing_ml_or_inadequate_history_retain_baseline(self):
        baseline, ml = self.candidates()
        ml.loc[0, "predicted_units"] = np.nan
        ml.loc[0, "score_eligible"] = False
        self.assertEqual(compare_models(baseline, ml, "001", 7)[1]["selected_model"], "baseline")
        self.assertEqual(compare_models(baseline.loc[baseline.fold > 1], ml.loc[ml.fold > 1], "001", 7)[1]["selected_model"], "baseline")


class ArtifactAndInterfaceTests(unittest.TestCase):
    def test_model_artifacts_checksums_replay_and_complete_retraining(self):
        dataset = long_dataset()
        results = run_model_analysis(dataset, PlanningSettings())
        with tempfile.TemporaryDirectory() as directory:
            run = save_analysis(dataset, results, directory)
            self.assertEqual(reproduce(run, retrain=True), 14)
            manifest = json.loads((run / "manifest.json").read_text())
            self.assertIn("code/demand_planner/forecasting/regression.py", manifest["files_sha256"])
            self.assertIn("signal_tail", json.loads((run / "trained_models.json").read_text())["001"]["model"])
            with (run / "daily_forecasts.csv").open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                reproduce(run)

    def test_comparison_interface_both_predictions_and_selected_forecast(self):
        dataset = long_dataset()
        result = run_model_analysis(dataset, PlanningSettings())
        app = AppTest.from_function(render_results, args=(dataset, result), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("ML versus baseline" in heading.value for heading in app.subheader))
        self.assertIn("predicted_units_ml", app.dataframe[2].value.rename(columns={"Predicted units": "predicted_units"}))
        for screen in ("product_detail", "downloads"):
            app = AppTest.from_function(render_completed_screen, args=(dataset, result, screen)).run()
            self.assertFalse(app.exception)
            if screen == "downloads":
                self.assertEqual(len(app.get("download_button")), 13)


if __name__ == "__main__":
    unittest.main()
