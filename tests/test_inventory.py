import unittest
from dataclasses import replace
import pandas as pd
from streamlit.testing.v1 import AppTest
from demand_planner.domain import DatasetBundle, PlanningSettings, AnalysisResults
from demand_planner.inventory.planning import plan_inventory


def fixture(stock=3, demand=2.5, lead=3, review=4, receipts=()):
    cutoff = pd.Timestamp("2025-01-01")
    dataset = DatasetBundle({
        "sales": pd.DataFrame({"date": [cutoff], "product_id": ["001"], "units_sold": [2]}),
        "products": pd.DataFrame({"product_id": ["001"], "product_name": ["Tea"], "lead_time_days": [lead],
                                  "review_period_days": [review], "pack_size": [6], "minimum_order_qty": [10]}),
        "inventory": pd.DataFrame({"product_id": ["001"], "snapshot_date": [cutoff], "on_hand_units": [stock]}),
        "receipts": pd.DataFrame([{"product_id": "001", "expected_date": cutoff + pd.Timedelta(days=day), "quantity_units": quantity}
                                  for day, quantity in receipts], columns=["product_id", "expected_date", "quantity_units"])
    }, "Test", "inventory-test")
    forecast = pd.DataFrame({"product_id": "001", "date": pd.date_range(cutoff + pd.Timedelta(days=1), periods=28),
                             "horizon_days": 28, "predicted_units": demand})
    return dataset, forecast


def render_inventory(dataset, result):
    import streamlit as st
    from demand_planner.ui.state import initialize_state
    from demand_planner.ui.inventory import inventory_screen
    initialize_state()
    st.session_state.dataset = dataset
    st.session_state.results = result
    inventory_screen()


class InventoryTests(unittest.TestCase):
    def plan(self, settings=None, **kwargs):
        dataset, forecasts = fixture(**kwargs)
        return plan_inventory(dataset, forecasts, settings or PlanningSettings())

    def test_fractional_demand_formulas_and_whole_pack_order(self):
        dataset, forecasts = fixture()
        original = forecasts.copy(deep=True)
        projection, summary = plan_inventory(dataset, forecasts, PlanningSettings())
        row = summary.iloc[0]
        self.assertEqual(row.lead_time_demand_units, 7.5)
        self.assertEqual(row.protection_demand_units, 17.5)
        self.assertEqual(row.safety_stock_units, 5)
        self.assertEqual(row.reorder_point_units, 12.5)
        self.assertEqual(row.target_stock_units, 22.5)
        self.assertEqual(row.raw_order_units, 15)
        self.assertEqual(row.suggested_order_units, 18)
        self.assertEqual(row.estimated_stockout_date, pd.Timestamp("2025-01-03"))
        self.assertEqual(row.priority, 1)
        self.assertEqual(row.suggested_order_arrival_date, pd.Timestamp("2025-01-05"))
        self.assertEqual(projection.closing_stock_units.iloc[0], .5)
        self.assertEqual(projection.unmet_demand_units.sum(), 67)
        pd.testing.assert_frame_equal(forecasts, original)

    def test_zero_demand_does_not_trigger_minimum_order(self):
        projection, summary = self.plan(stock=0, demand=0)
        self.assertEqual(summary.suggested_order_units.iloc[0], 0)
        self.assertTrue(pd.isna(summary.estimated_stockout_date.iloc[0]))
        self.assertEqual(projection.unmet_demand_units.sum(), 0)

    def test_fixed_buffer_can_order_for_zero_demand(self):
        _, summary = self.plan(PlanningSettings(safety_stock_policy="fixed_units", safety_stock_units=10), stock=0, demand=0)
        self.assertEqual(summary.suggested_order_units.iloc[0], 12)

    def test_sufficient_stock(self):
        projection, summary = self.plan(stock=100)
        self.assertEqual(summary.suggested_order_units.iloc[0], 0)
        self.assertEqual(projection.closing_stock_units.iloc[-1], 30)
        self.assertEqual(summary.attention.iloc[0], "Monitor")

    def test_no_buffer_and_exact_exhaustion(self):
        projection, summary = self.plan(PlanningSettings(safety_stock_policy="none"), stock=5)
        self.assertEqual(summary.safety_stock_units.iloc[0], 0)
        self.assertEqual(projection.closing_stock_units.iloc[1], 0)
        self.assertEqual(summary.estimated_stockout_date.iloc[0], pd.Timestamp("2025-01-04"))

    def test_timely_and_late_delivery_have_same_position_but_different_risk(self):
        timely_projection, timely = self.plan(stock=0, receipts=[(1, 100)])
        late_projection, late = self.plan(stock=0, receipts=[(5, 100)])
        self.assertEqual(timely.inventory_position_units.iloc[0], late.inventory_position_units.iloc[0])
        self.assertEqual(late.suggested_order_units.iloc[0], 12)
        self.assertTrue(pd.isna(timely.estimated_stockout_date.iloc[0]))
        self.assertEqual(late.priority.iloc[0], 1)
        self.assertEqual(late_projection.unmet_demand_units.sum(), 10)
        self.assertEqual(timely_projection.unmet_demand_units.sum(), 0)
        self.assertEqual(late_projection.incoming_units.sum(), 100)

    def test_receipt_window_boundaries_and_grouping(self):
        projection, summary = self.plan(stock=0, receipts=[(7, 5), (7, 6), (8, 50), (29, 1000)])
        self.assertEqual(summary.incoming_protection_units.iloc[0], 11)
        self.assertEqual(projection.incoming_units.iloc[6], 11)
        self.assertEqual(projection.incoming_units.sum(), 61)
        self.assertEqual(summary.raw_order_units.iloc[0], 7.5)

    def test_long_lead_time_and_unsupported_window(self):
        projection, summary = self.plan(lead=21, review=7)
        self.assertEqual(summary.protection_demand_units.iloc[0], 70)
        self.assertEqual(len(projection), 28)
        projection, summary = self.plan(lead=28, review=1)
        self.assertTrue(projection.empty)
        self.assertEqual(summary.status.iloc[0], "unavailable")
        self.assertTrue(pd.isna(summary.suggested_order_units.iloc[0]))

    def test_global_review_applies_only_without_product_override(self):
        dataset, forecasts = fixture()
        dataset.tables["products"]["review_period_is_override"] = False
        _, summary = plan_inventory(dataset, forecasts, PlanningSettings(review_period_days=9))
        self.assertEqual(summary.protection_days.iloc[0], 12)
        dataset.tables["products"]["review_period_is_override"] = True
        _, summary = plan_inventory(dataset, forecasts, PlanningSettings(review_period_days=9))
        self.assertEqual(summary.protection_days.iloc[0], 7)

    def test_missing_stock_or_forecast_is_unavailable(self):
        for missing in ("stock", "forecast", "snapshot"):
            dataset, forecasts = fixture()
            if missing == "stock":
                dataset.tables["inventory"] = dataset.tables["inventory"].iloc[:0]
            elif missing == "forecast":
                forecasts.loc[0, "predicted_units"] = float("nan")
            else:
                dataset.tables["inventory"]["snapshot_date"] = pd.Timestamp("2024-12-31")
            projection, summary = plan_inventory(dataset, forecasts, PlanningSettings())
            self.assertTrue(projection.empty)
            self.assertTrue(pd.isna(summary.suggested_order_units.iloc[0]))

    def test_bad_dates_negative_demand_and_overdue_receipts_rejected(self):
        for problem in ("dates", "negative", "overdue"):
            dataset, forecasts = fixture(receipts=[(0, 5)] if problem == "overdue" else [])
            if problem == "dates":
                forecasts.loc[0, "date"] += pd.Timedelta(days=1)
            elif problem == "negative":
                forecasts.loc[0, "predicted_units"] = -1
            with self.assertRaises(ValueError):
                plan_inventory(dataset, forecasts, PlanningSettings())

    def test_ui_metrics_tables_and_downloads(self):
        dataset, forecasts = fixture()
        projection, summary = plan_inventory(dataset, forecasts, PlanningSettings())
        result = AnalysisResults(dataset.fingerprint, PlanningSettings(), inventory_projection=projection, reorder_suggestions=summary)
        app = AppTest.from_function(render_inventory, args=(dataset, result)).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[2].value, "18")
        pd.testing.assert_frame_equal(app.dataframe[1].value, projection)
        self.assertEqual(len(app.get("download_button")), 2)
        self.assertTrue(any("cannot guarantee" in item.value for item in app.caption))

    def test_empty_inventory_screen(self):
        app = AppTest.from_function(render_inventory, args=(None, None)).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.info)
