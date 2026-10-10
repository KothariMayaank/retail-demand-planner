import unittest
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest
from demand_planner.forecasting.baseline import forecast_baseline
from demand_planner.evaluation.backtesting import rolling_backtest
from demand_planner.evaluation.metrics import forecast_metrics
from demand_planner.analysis import run_baseline_analysis
from demand_planner.domain import DatasetBundle, PlanningSettings
from demand_planner.ui.baseline_results import prediction_chart


def sales_fixture(days=112):
    dates = pd.date_range("2025-01-01", periods=days)
    return pd.DataFrame({"date": dates, "product_id": "001", "units_sold": dates.dayofweek + 1,
                         "stockout_flag": pd.array([False] * days, dtype="boolean"),
                         "is_zero_filled": False})


def render_results(dataset, results):
    import streamlit as st
    from demand_planner.ui.state import initialize_state
    from demand_planner.ui.baseline_results import evaluation_screen
    initialize_state()
    st.session_state.dataset = dataset
    st.session_state.results = results
    evaluation_screen()


def render_setup(dataset):
    import streamlit as st
    from demand_planner.ui.state import initialize_state
    from demand_planner.ui.screens import data_setup
    initialize_state()
    st.session_state.dataset = dataset
    data_setup()


def render_completed_screen(dataset, results, screen):
    import streamlit as st
    from demand_planner.ui.state import initialize_state
    from demand_planner.ui import screens
    initialize_state()
    st.session_state.dataset = dataset
    st.session_state.results = results
    getattr(screens, screen)()


class BaselineTests(unittest.TestCase):
    def test_weekdays_and_exact_target_alignment_all_horizons(self):
        sales = sales_fixture(56)
        origin = sales.date.max()
        for horizon in (7, 14, 28):
            result = forecast_baseline(sales, "001", origin, horizon)
            self.assertEqual(result.date.tolist(), list(pd.date_range(origin + pd.Timedelta(days=1), periods=horizon)))
            self.assertEqual(result.predicted_units.tolist(), (result.date.dt.dayofweek + 1).astype(float).tolist())
            self.assertTrue(result.method.eq("weekday_mean_28d").all())
            self.assertTrue(result.matching_days.eq(4).all())

    def test_recent_window_excludes_older_sales(self):
        sales = sales_fixture(56)
        sales.loc[:27, "units_sold"] = 9999
        result = forecast_baseline(sales, "001", sales.date.max(), 7)
        self.assertEqual(result.predicted_units.tolist(), (result.date.dt.dayofweek + 1).astype(float).tolist())

    def test_short_history_fallback_and_minimum_history(self):
        sales = sales_fixture(14)
        result = forecast_baseline(sales, "001", sales.date.max(), 7)
        self.assertTrue(result.predicted_units.eq(4).all())
        self.assertTrue(result.status.eq("fallback").all())
        short = sales.iloc[:-1]
        unavailable = forecast_baseline(short, "001", short.date.max(), 7)
        self.assertTrue(unavailable.predicted_units.isna().all())
        self.assertTrue(unavailable.reason.str.contains("14 non-stockout").all())

    def test_zero_sales_are_valid_forecasts(self):
        sales = sales_fixture(56)
        sales["units_sold"] = 0
        result = forecast_baseline(sales, "001", sales.date.max(), 28)
        self.assertTrue(result.predicted_units.eq(0).all())
        self.assertTrue(result.status.eq("ready").all())

    def test_stockouts_are_excluded_and_sparse_weekday_falls_back(self):
        sales = sales_fixture(56)
        matching = sales.index[(sales.index >= 28) & (sales.date.dt.dayofweek == 0)][:3]
        sales.loc[matching, "stockout_flag"] = True
        sales.loc[matching, "units_sold"] = 9999
        result = forecast_baseline(sales, "001", sales.date.max(), 7)
        monday = result.loc[result.date.dt.dayofweek == 0].iloc[0]
        recent = sales.iloc[-28:]
        self.assertEqual(monday.method, "recent_mean_28d_fallback")
        self.assertEqual(monday.matching_days, 1)
        self.assertAlmostEqual(monday.predicted_units, recent.loc[~recent.stockout_flag, "units_sold"].mean())
        other = result.loc[result.date.dt.dayofweek != 0]
        self.assertEqual(other.predicted_units.tolist(), (other.date.dt.dayofweek + 1).astype(float).tolist())

    def test_future_rows_values_flags_and_other_products_cannot_change_forecast(self):
        sales = sales_fixture(112)
        origin = sales.date.iloc[55]
        expected = forecast_baseline(sales.iloc[:56], "001", origin, 28)
        changed = sales.copy()
        changed.loc[changed.date > origin, "units_sold"] = 100000
        changed.loc[changed.date > origin, "stockout_flag"] = True
        other = sales.copy()
        other["product_id"] = "002"
        other["units_sold"] = 100000
        assert_frame_equal(expected, forecast_baseline(pd.concat([changed, other]), "001", origin, 28))

    def test_gaps_and_no_recent_usable_history_are_unavailable(self):
        sales = sales_fixture(56)
        gap = sales.drop(index=20)
        self.assertTrue(forecast_baseline(gap, "001", sales.date.max(), 7).predicted_units.isna().all())
        sales.loc[28:, "stockout_flag"] = True
        result = forecast_baseline(sales, "001", sales.date.max(), 7)
        self.assertTrue(result.predicted_units.isna().all())
        self.assertTrue(result.reason.str.contains("No usable sales").all())


class MetricTests(unittest.TestCase):
    def test_known_arithmetic_and_zero_demand(self):
        metric = forecast_metrics([0, 2, 4], [1, 4, 3])
        self.assertEqual(metric["absolute_error_units"], 4)
        self.assertAlmostEqual(metric["mae"], 4 / 3)
        self.assertAlmostEqual(metric["wape_percent"], 100 * 4 / 6)
        zero = forecast_metrics([0, 0], [1, 2])
        self.assertEqual(zero["mae"], 1.5)
        self.assertIsNone(zero["wape_percent"])
        self.assertIsNone(forecast_metrics([], [])["mae"])

    def test_invalid_pairs_are_rejected(self):
        for actual, predicted in (([1], [1, 2]), ([[1]], [[1]]), ([np.nan], [1]),
                                  ([1], [np.inf]), ([-1], [1]), ([1], [-1])):
            with self.subTest(actual=actual, predicted=predicted), self.assertRaises(ValueError):
                forecast_metrics(actual, predicted)


class BacktestTests(unittest.TestCase):
    def test_fold_alignment_and_minimum_training_all_horizons(self):
        sales = sales_fixture(84)
        for horizon, expected_folds in ((7, 4), (14, 2), (28, 1)):
            predictions, folds, summary = rolling_backtest(sales, "001", horizon)
            self.assertEqual(len(folds), expected_folds)
            self.assertEqual(len(predictions), horizon * expected_folds)
            self.assertEqual(summary["mae"], 0)
            self.assertEqual(summary["wape_percent"], 0)
            self.assertEqual(summary["status"], "partial")
            self.assertFalse(predictions.date.duplicated().any())
            for fold in folds.itertuples():
                rows = predictions.loc[predictions.fold == fold.fold]
                self.assertGreaterEqual((fold.forecast_origin - sales.date.min()).days + 1, 56)
                self.assertEqual(rows.date.tolist(), list(pd.date_range(fold.forecast_origin + pd.Timedelta(days=1), periods=horizon)))
                self.assertEqual(rows.date.max(), fold.test_end)
                self.assertTrue(rows.date.gt(fold.forecast_origin).all())

    def test_future_changes_cannot_change_existing_origin_predictions(self):
        sales = sales_fixture(112)
        before, folds, _ = rolling_backtest(sales, "001", 14)
        origin = folds.forecast_origin.iloc[0]
        changed = sales.copy()
        changed.loc[changed.date > origin, "units_sold"] = 100000
        changed.loc[changed.date > origin, "stockout_flag"] = True
        after, _, _ = rolling_backtest(changed, "001", 14)
        columns = ["date", "predicted_units", "method", "training_observations"]
        assert_frame_equal(before.loc[before.forecast_origin == origin, columns].reset_index(drop=True),
                           after.loc[after.forecast_origin == origin, columns].reset_index(drop=True))

    def test_target_exclusions_and_missing_actual_remain_visible(self):
        sales = sales_fixture(84)
        sales.loc[60, "stockout_flag"] = True
        sales.loc[61, "stockout_flag"] = pd.NA
        sales = sales.drop(index=62)
        predictions, _, summary = rolling_backtest(sales, "001", 28)
        self.assertEqual(summary["stockout_targets"], 1)
        self.assertEqual(summary["missing_actual_days"], 1)
        self.assertEqual(summary["scored_days"], 26)
        self.assertFalse(predictions.loc[predictions.date == pd.Timestamp("2025-03-02"), "score_eligible"].iloc[0])
        self.assertTrue(predictions.loc[predictions.date == pd.Timestamp("2025-03-03"), "score_eligible"].iloc[0])
        self.assertTrue(predictions.loc[predictions.date == pd.Timestamp("2025-03-04"), "actual_units"].isna().all())
        self.assertTrue(predictions.loc[~predictions.score_eligible, "absolute_error_units"].isna().all())

    def test_training_gap_blocks_predictions_without_filling_zero(self):
        sales = sales_fixture(84).drop(index=10)
        predictions, _, summary = rolling_backtest(sales, "001", 28)
        self.assertEqual(summary["scored_days"], 0)
        self.assertEqual(summary["unavailable_prediction_days"], 28)
        self.assertEqual(summary["status"], "unavailable")
        self.assertTrue(predictions.predicted_units.isna().all())

    def test_zero_test_demand_has_defined_mae_and_undefined_wape(self):
        sales = sales_fixture(84)
        sales.loc[56:, "units_sold"] = 0
        _, _, summary = rolling_backtest(sales, "001", 28)
        self.assertEqual(summary["mae"], 4)
        self.assertIsNone(summary["wape_percent"])
        self.assertIn("total zero", summary["note"])

    def test_metrics_are_pooled_and_folds_are_capped(self):
        sales = sales_fixture(200)
        sales.loc[160:, "units_sold"] *= 3
        predictions, folds, summary = rolling_backtest(sales, "001", 7)
        self.assertEqual(len(folds), 6)
        scored = predictions.loc[predictions.score_eligible]
        expected_error = (scored.actual_units - scored.predicted_units).abs().sum()
        self.assertAlmostEqual(summary["mae"], expected_error / len(scored))
        self.assertAlmostEqual(summary["wape_percent"], 100 * expected_error / scored.actual_units.sum())
        self.assertNotAlmostEqual(summary["wape_percent"], folds.wape_percent.mean())

    def test_no_history_and_insufficient_history_keep_summary(self):
        for product_id in ("001", "missing"):
            predictions, folds, summary = rolling_backtest(sales_fixture(62), product_id, 7)
            self.assertTrue(predictions.empty)
            self.assertTrue(folds.empty)
            self.assertEqual(summary["status"], "unavailable")
            self.assertIsNone(summary["mae"])


class BaselineDashboardTests(unittest.TestCase):
    @staticmethod
    def dataset():
        return DatasetBundle(tables={"sales": sales_fixture(112),
            "products": pd.DataFrame({"product_id": ["001"], "product_name": ["Test product"]}),
            "inventory": pd.DataFrame(), "receipts": pd.DataFrame()}, source="Test", fingerprint="baseline-test")

    def test_run_analysis_button_produces_all_horizon_results(self):
        dataset = self.dataset()
        app = AppTest.from_function(render_setup, args=(dataset,), default_timeout=30).run()
        next(button for button in app.button if button.label == "Run analysis").click().run()
        self.assertFalse(app.exception)
        result = app.session_state["results"]
        self.assertEqual(len(result.daily_forecasts), 14)
        self.assertEqual(set(result.evaluation.horizon_days), {7, 14, 28})

    def test_evaluation_filters_values_and_chart_match_data(self):
        dataset = self.dataset()
        dataset.tables["sales"].loc[100, "stockout_flag"] = True
        results = run_baseline_analysis(dataset, PlanningSettings())
        app = AppTest.from_function(render_results, args=(dataset, results), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual([item.value for item in app.metric][:2], ["0.000", "0.0%"])
        next(widget for widget in app.selectbox if widget.label == "Evaluation horizon (days)").select(28).run()
        self.assertFalse(app.exception)
        summary = results.evaluation.loc[results.evaluation.horizon_days == 28].iloc[0]
        self.assertEqual(app.metric[2].value, str(summary.scored_days))
        rows = results.backtest_predictions.loc[results.backtest_predictions.horizon_days == 28]
        rows = rows.loc[rows.forecast_origin == rows.forecast_origin.max()]
        figure = prediction_chart(rows)
        self.assertEqual(list(figure.data[0].y), rows.actual_units.astype(float).tolist())
        self.assertEqual(list(figure.data[1].y), rows.predicted_units.tolist())
        self.assertEqual(len(figure.data[2].x), 1)

    def test_completed_product_overview_downloads_and_stale_results(self):
        dataset = self.dataset()
        results = run_baseline_analysis(dataset, PlanningSettings())
        for screen in ("product_detail", "overview", "downloads"):
            with self.subTest(screen=screen):
                app = AppTest.from_function(render_completed_screen, args=(dataset, results, screen)).run()
                self.assertFalse(app.exception)
                if screen == "product_detail":
                    self.assertEqual(len(app.get("plotly_chart")), 1)
                    self.assertEqual(len(app.dataframe[1].value), 14)
                elif screen == "overview":
                    self.assertEqual(app.metric[0].value, f"{results.daily_forecasts.predicted_units.sum():,.2f}")
                else:
                    self.assertEqual(len(app.get("download_button")), 8)
        results.input_fingerprint = "stale"
        app = AppTest.from_function(render_results, args=(dataset, results)).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("run analysis" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
