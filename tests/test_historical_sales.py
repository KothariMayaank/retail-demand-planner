"""Independent arithmetic checks for every historical dashboard measure and trace."""
from datetime import date
import unittest
import pandas as pd
from streamlit.testing.v1 import AppTest
from demand_planner.analytics.history import daily_history, summarize_sales, weekday_summary, compare_products, flagged_periods
from demand_planner.data.loading import load_csv_bundle
from demand_planner.data.validation import validate_dataset
from demand_planner.ui.history_charts import daily_chart, weekday_chart, comparison_chart


def history_fixture(confirm_zero=False):
    products = pd.DataFrame({"product_id": ["001", "002", "003"],
                             "product_name": ["Rice", "Milk", "New product"], "lead_time_days": [3, 1, 4]})
    rows = []
    for day in range(1, 15):
        if day != 5:
            rows.append([f"2026-01-{day:02d}", "001", 0 if day in (2, 3) else day,
                         "true" if day == 3 else "false"])
        if day >= 8:
            rows.append([f"2026-01-{day:02d}", "002", 10, ""])
    sales = pd.DataFrame(rows, columns=["date", "product_id", "units_sold", "stockout_flag"])
    inventory = pd.DataFrame({"snapshot_date": ["2026-01-14"] * 3,
                              "product_id": ["001", "002", "003"], "on_hand_units": [3, 4, 0]})
    files = {name: frame.to_csv(index=False, lineterminator="\n").encode() for name, frame in
             (("products", products), ("sales", sales), ("inventory", inventory))}
    raw = load_csv_bundle(files, "Arithmetic fixture")
    return validate_dataset(raw, as_of=date(2026, 1, 15), zero_fill_products=("001",) if confirm_zero else ())


def render_history(dataset):
    from demand_planner.ui.state import initialize_state
    from demand_planner.ui.historical_sales import historical_sales
    import streamlit as st
    initialize_state()
    st.session_state.dataset = dataset
    historical_sales()


class HistoryArithmeticTests(unittest.TestCase):
    def setUp(self):
        report = history_fixture()
        self.assertFalse(report.has_errors)
        self.dataset = report.dataset
        self.daily = daily_history(self.dataset.tables["sales"], "001", "2026-01-01", "2026-01-14")

    def test_totals_means_zero_rate_and_quality_counts(self):
        # 1..14 sums to 105; recorded zeroes replace 2 and 3, and day 5 is absent.
        metrics = summarize_sales(self.daily)
        self.assertEqual(metrics.total_units, 95)
        self.assertEqual(metrics.recorded_days, 13)
        self.assertEqual(metrics.expected_days, 14)
        self.assertEqual(metrics.missing_days, 1)
        self.assertEqual(metrics.stockout_days, 1)
        self.assertAlmostEqual(metrics.average_daily_units, 95 / 13)
        self.assertAlmostEqual(metrics.zero_sales_percent, 200 / 13)
        self.assertTrue(pd.isna(self.daily.loc[self.daily.date == pd.Timestamp("2026-01-05"), "units_sold"].iloc[0]))

    def test_full_calendar_rolling_window_and_inclusive_filter(self):
        daily = self.daily.set_index("date")
        self.assertTrue(daily.loc[:"2026-01-11", "rolling_average"].isna().all())
        self.assertEqual(daily.loc["2026-01-12", "rolling_average"], 9)
        self.assertEqual(daily.loc["2026-01-14", "rolling_average"], 11)
        filtered = daily_history(self.dataset.tables["sales"], "001", "2026-01-08", "2026-01-14")
        self.assertEqual(len(filtered), 7)
        self.assertEqual(summarize_sales(filtered).total_units, 77)
        self.assertTrue(filtered.rolling_average.iloc[:6].isna().all())
        self.assertEqual(filtered.rolling_average.iloc[6], 11)

    def test_weekday_aggregates_use_record_counts_not_calendar_counts(self):
        weekdays = weekday_summary(self.daily)
        monday = weekdays.loc[weekdays.weekday == "Monday"].iloc[0]
        self.assertEqual(monday.total_units, 12)
        self.assertEqual(monday.average_daily_units, 12)
        self.assertEqual(monday.recorded_days, 1)
        self.assertEqual(monday.missing_days, 1)
        self.assertEqual(weekdays.total_units.sum(), 95)
        self.assertEqual(weekdays.recorded_days.sum(), 13)
        thursday = weekdays.loc[weekdays.weekday == "Thursday"].iloc[0]
        self.assertEqual(thursday.average_daily_units, 4.5)
        friday = weekdays.loc[weekdays.weekday == "Friday"].iloc[0]
        self.assertEqual(friday.zero_sales_percent, 50)

    def test_comparison_same_dates_keeps_empty_history_unavailable(self):
        table = compare_products(self.dataset.tables["sales"], self.dataset.tables["products"],
                                 ["001", "002", "003"], "2026-01-01", "2026-01-14")
        self.assertEqual(table.product_id.tolist(), ["001", "002", "003"])
        self.assertEqual(table.total_units.iloc[:2].tolist(), [95, 70])
        self.assertTrue(pd.isna(table.total_units.iloc[2]))
        self.assertEqual(table.loc[1, "expected_days"], 7)
        self.assertEqual(table.loc[1, "recorded_days"], 7)
        self.assertAlmostEqual(table.loc[0, "coverage_percent"], 100 * 13 / 14)
        self.assertEqual(table.loc[1, "coverage_percent"], 100)
        self.assertTrue(pd.isna(table.loc[2, "coverage_percent"]))

    def test_explicit_zeros_have_provenance_and_correct_denominators(self):
        filled = history_fixture(confirm_zero=True).dataset
        daily = daily_history(filled.tables["sales"], "001", "2026-01-01", "2026-01-14")
        metrics = summarize_sales(daily)
        self.assertEqual(metrics.total_units, 95)
        self.assertEqual(metrics.recorded_days, 14)
        self.assertEqual(metrics.confirmed_zero_days, 1)
        self.assertEqual(metrics.missing_days, 0)
        self.assertAlmostEqual(metrics.average_daily_units, 95 / 14)
        self.assertAlmostEqual(metrics.zero_sales_percent, 300 / 14)
        self.assertEqual(daily.status.iloc[4], "Confirmed zero")
        self.assertAlmostEqual(daily.rolling_average.iloc[6], (1 + 0 + 0 + 4 + 0 + 6 + 7) / 7)

    def test_periods_and_no_history(self):
        periods = flagged_periods(self.daily)
        self.assertEqual(periods.status.tolist(), ["Known stockout", "Missing record"])
        self.assertEqual(periods.start_date.dt.day.tolist(), [3, 5])
        self.assertEqual(periods.days.tolist(), [1, 1])
        daily = daily_history(self.dataset.tables["sales"], "003", "2026-01-01", "2026-01-14")
        metrics = summarize_sales(daily)
        self.assertIsNone(metrics.total_units)
        self.assertIsNone(metrics.average_daily_units)
        self.assertIsNone(metrics.zero_sales_percent)
        self.assertEqual(metrics.missing_days, 0)
        self.assertEqual(metrics.expected_days, 0)
        self.assertTrue(weekday_summary(daily).average_daily_units.isna().all())

    def test_plot_values_reconcile_and_do_not_bridge_gaps(self):
        figure = daily_chart(self.daily, 7)
        self.assertEqual(len(figure.data[0].x), 14)
        self.assertIsNone(figure.data[0].y[4])
        self.assertFalse(figure.data[0].connectgaps)
        self.assertFalse(figure.data[1].connectgaps)
        self.assertEqual(sum(value for value in figure.data[0].y if value is not None), 95)
        self.assertEqual(figure.data[1].y[-1], 11)
        self.assertEqual(figure.data[2].name, "Known stockout")
        self.assertEqual(list(figure.data[2].y), [0])
        self.assertEqual(len(figure.layout.shapes), 2)
        weekdays = weekday_summary(self.daily)
        self.assertEqual(list(weekday_chart(weekdays).data[0].y), weekdays.average_daily_units.tolist())
        comparison = compare_products(self.dataset.tables["sales"], self.dataset.tables["products"],
                                      ["001", "002", "003"], "2026-01-01", "2026-01-14")
        bars = comparison_chart(comparison, "001")
        self.assertEqual(list(bars.data[0].x), [95, 70, None])


class HistoryInterfaceTests(unittest.TestCase):
    def test_screen_values_charts_and_filters(self):
        dataset = history_fixture().dataset
        app = AppTest.from_function(render_history, args=(dataset,), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["95", "7.31", "15.4%"])
        self.assertEqual(len(app.get("plotly_chart")), 3)
        self.assertTrue(any("1 missing day" in warning.value for warning in app.warning))
        self.assertTrue(any("1 known stockout day" in warning.value for warning in app.warning))
        app.selectbox(key=f"history_product_{dataset.fingerprint}").select("002").run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["70", "10.00", "0.0%"])
        app.date_input[0].set_value((date(2026, 1, 8), date(2026, 1, 14))).run()
        app.selectbox(key=f"history_product_{dataset.fingerprint}").select("001").run()
        self.assertEqual([metric.value for metric in app.metric], ["77", "11.00", "0.0%"])
        self.assertFalse(app.exception)
        app.selectbox(key=f"history_product_{dataset.fingerprint}").select("003").run()
        self.assertEqual([metric.value for metric in app.metric], ["Unavailable"] * 3)
        app.multiselect[0].set_value([]).run()
        self.assertTrue(any("Select at least one" in info.value for info in app.info))

    def test_empty_screen(self):
        app = AppTest.from_function(render_history, args=(None,), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("No data loaded" in info.value for info in app.info))
