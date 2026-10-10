"""Rules that change demand history, scoring, joins or planning eligibility."""
from datetime import date
import unittest
import pandas as pd
from streamlit.testing.v1 import AppTest
from demand_planner.data.exporting import csv_bytes
from demand_planner.data.loading import load_csv_bundle
from demand_planner.data.preprocessing import prepare_training_series
from demand_planner.data.validation import validate_dataset

AS_OF = date(2026, 2, 1)


def valid_files() -> dict[str, bytes]:
    products = pd.DataFrame({"product_id": ["001", "002"], "product_name": ["Rice", "Milk"],
                             "lead_time_days": [3, 1]})
    sales = pd.DataFrame([{"date": day.strftime("%Y-%m-%d"), "product_id": product_id,
                           "units_sold": 3, "stockout_flag": "false"}
                          for product_id in ("001", "002") for day in pd.date_range("2026-01-01", "2026-01-28")])
    inventory = pd.DataFrame({"snapshot_date": ["2026-01-28"] * 2,
                              "product_id": ["001", "002"], "on_hand_units": [10, 20]})
    receipts = pd.DataFrame({"receipt_id": ["R001"], "product_id": ["001"],
                             "expected_date": ["2026-02-02"], "quantity_units": [12]})
    return {name: frame.to_csv(index=False, lineterminator="\n").encode() for name, frame in
            (("products", products), ("sales", sales), ("inventory", inventory), ("receipts", receipts))}


def raw_bundle():
    return load_csv_bundle(valid_files(), "Test upload")


def render_upload_flow(files):
    from demand_planner.ui.screens import _load, data_setup
    from demand_planner.ui.state import initialize_state
    import streamlit as st
    initialize_state()
    if "fixture_loaded" not in st.session_state:
        _load(files, "Test upload")
        st.session_state.fixture_loaded = True
    data_setup()


def render_failed_replacement(good):
    from demand_planner.ui.screens import _load, data_setup
    from demand_planner.ui.state import initialize_state
    import streamlit as st
    initialize_state()
    _load(good, "Good upload")
    bad = dict(good)
    bad["sales"] = b"date,product_id,units_sold\n2026-01-28,001,-9\n"
    _load(bad, "Bad upload")
    data_setup()


class ValidationTests(unittest.TestCase):
    def test_configured_review_changes_readiness_and_preserves_explicit_override(self):
        raw = raw_bundle()
        raw.tables["products"]["lead_time_days"] = ["23", "23"]
        raw.tables["products"]["review_period_days"] = ["", "7"]
        default = validate_dataset(raw, as_of=AS_OF)
        changed = validate_dataset(raw, as_of=AS_OF, default_review_period_days=2)
        self.assertEqual(default.summary.inventory_ready.tolist(), [False, False])
        self.assertEqual(changed.summary.inventory_ready.tolist(), [True, False])
        self.assertEqual(changed.dataset.tables["products"].review_period_days.tolist(), [2, 7])
    def test_review_override_provenance(self):
        raw = raw_bundle()
        raw.tables["products"]["review_period_days"] = ["", "4"]
        report = validate_dataset(raw, as_of=AS_OF)
        self.assertFalse(report.has_errors)
        self.assertEqual(report.dataset.tables["products"].review_period_is_override.tolist(), [False, True])
        self.assertEqual(report.dataset.tables["products"].review_period_days.tolist(), [7, 4])

    def test_normalization_preserves_originals_ids_and_real_zeros(self):
        raw = raw_bundle()
        raw.tables["sales"].loc[0, "units_sold"] = "0"
        original = raw.tables["sales"].copy(deep=True)
        report = validate_dataset(raw, as_of=AS_OF)
        self.assertFalse(report.has_errors)
        pd.testing.assert_frame_equal(original, raw.tables["sales"])
        prepared = report.dataset.tables["sales"]
        self.assertEqual(prepared.loc[0, "product_id"], "001")
        self.assertEqual(prepared.loc[0, "units_sold"], 0)
        self.assertFalse(prepared.loc[0, "is_zero_filled"])
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(prepared.date))
        self.assertTrue(report.summary.forecast_ready.all())

    def test_required_columns_and_blank_values_block(self):
        for table, column in (("sales", "units_sold"), ("sales", "date"),
                              ("inventory", "on_hand_units"), ("products", "product_name")):
            with self.subTest(table=table, column=column):
                raw = raw_bundle()
                raw.tables[table].loc[0, column] = ""
                report = validate_dataset(raw, as_of=AS_OF)
                self.assertTrue(report.has_errors)
                self.assertIsNone(report.dataset)
                self.assertTrue(any(issue.row == 2 for issue in report.issues))
        raw = raw_bundle()
        raw.tables["sales"] = raw.tables["sales"].drop(columns="date")
        self.assertTrue(validate_dataset(raw, as_of=AS_OF).has_errors)

    def test_negative_fractional_and_missing_quantities_are_not_zero(self):
        for value in ("-1", "1.5", "NA", "", "1e3", "9223372036854775808"):
            with self.subTest(value=value):
                raw = raw_bundle()
                raw.tables["sales"].loc[0, "units_sold"] = value
                report = validate_dataset(raw, as_of=AS_OF)
                self.assertTrue(report.has_errors)
                self.assertTrue(any(issue.code == "quantity" and issue.row == 2 for issue in report.issues))
        raw = raw_bundle()
        raw.tables["sales"].loc[0, "units_sold"] = "9007199254740993"
        self.assertEqual(validate_dataset(raw, as_of=AS_OF).dataset.tables["sales"].loc[0, "units_sold"], 9007199254740993)

    def test_dates_must_be_real_iso_and_complete(self):
        for value in ("2025-02-29", "01/02/2026", "2026-1-01", "2026-02-01", "2026-03-01", "9999-01-01"):
            with self.subTest(value=value):
                raw = raw_bundle()
                raw.tables["sales"].loc[0, "date"] = value
                self.assertTrue(validate_dataset(raw, as_of=AS_OF).has_errors)

    def test_duplicate_keys_block_without_aggregation(self):
        for table in ("products", "sales", "inventory", "receipts"):
            with self.subTest(table=table):
                raw = raw_bundle()
                raw.tables[table] = pd.concat([raw.tables[table], raw.tables[table].iloc[[0]]], ignore_index=True)
                report = validate_dataset(raw, as_of=AS_OF)
                self.assertTrue(any(issue.code == "duplicate" for issue in report.issues))
                self.assertIsNone(report.dataset)

    def test_matching_ids_and_whitespace(self):
        for table in ("sales", "inventory", "receipts"):
            with self.subTest(table=table):
                raw = raw_bundle()
                raw.tables[table].loc[0, "product_id"] = "missing"
                self.assertTrue(any(issue.code == "unknown_product" for issue in validate_dataset(raw, as_of=AS_OF).issues))
        raw = raw_bundle()
        raw.tables["products"].loc[0, "product_id"] = " 001"
        self.assertTrue(any(issue.code == "identifier" for issue in validate_dataset(raw, as_of=AS_OF).issues))

    def test_snapshot_alignment_and_overdue_receipts(self):
        raw = raw_bundle()
        raw.tables["inventory"].loc[0, "snapshot_date"] = "2026-01-27"
        self.assertTrue(any(issue.code == "snapshot_mismatch" for issue in validate_dataset(raw, as_of=AS_OF).issues))
        raw = raw_bundle()
        raw.tables["receipts"].loc[0, "expected_date"] = "2026-01-28"
        self.assertTrue(any(issue.code == "overdue_receipt" for issue in validate_dataset(raw, as_of=AS_OF).issues))

    def test_missing_inventory_and_long_protection_only_block_planning(self):
        raw = raw_bundle()
        raw.tables["inventory"] = raw.tables["inventory"].iloc[[0]].copy()
        raw.tables["products"].loc[0, "lead_time_days"] = "28"
        report = validate_dataset(raw, as_of=AS_OF)
        self.assertFalse(report.has_errors)
        self.assertTrue(report.summary.forecast_ready.all())
        self.assertFalse(report.summary.inventory_ready.any())

    def test_gaps_require_confirmation_and_change_provenance(self):
        raw = raw_bundle()
        raw.tables["sales"] = raw.tables["sales"].drop(index=9).reset_index(drop=True)
        report = validate_dataset(raw, as_of=AS_OF)
        self.assertEqual(len(report.dataset.tables["sales"]), 55)
        summary = report.summary.set_index("product_id")
        self.assertFalse(summary.loc["001", "forecast_ready"])
        self.assertTrue(summary.loc["002", "forecast_ready"])
        filled = validate_dataset(raw, as_of=AS_OF, zero_fill_products=("001",))
        inserted = filled.dataset.tables["sales"].loc[lambda frame: frame.is_zero_filled]
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted.iloc[0].units_sold, 0)
        self.assertTrue(pd.isna(inserted.iloc[0].stockout_flag))
        self.assertEqual(inserted.iloc[0].date, pd.Timestamp("2026-01-10"))
        self.assertNotEqual(report.dataset.fingerprint, filled.dataset.fingerprint)
        self.assertTrue(filled.summary.forecast_ready.all())
        self.assertEqual(len(raw.tables["sales"]), 55)
        with self.assertRaisesRegex(ValueError, "Missing daily"):
            prepare_training_series(report.dataset.tables["sales"], "001", "2026-01-28")
        prepared = prepare_training_series(filled.dataset.tables["sales"], "001", "2026-01-28")
        self.assertEqual(len(prepared), 28)

    def test_later_launch_is_not_backfilled_but_missing_tail_is(self):
        raw = raw_bundle()
        raw.tables["sales"] = raw.tables["sales"].loc[lambda frame: ~((frame.product_id == "002") &
                                                  ((frame.date < "2026-01-05") | (frame.date == "2026-01-28")))].copy()
        report = validate_dataset(raw, as_of=AS_OF)
        self.assertEqual(report.missing_dates.date.tolist(), [pd.Timestamp("2026-01-28")])
        filled = validate_dataset(raw, as_of=AS_OF, zero_fill_products=("002",))
        self.assertEqual(filled.dataset.tables["sales"].loc[lambda frame: frame.product_id == "002"].date.min(),
                         pd.Timestamp("2026-01-05"))

    def test_defaults_and_unknown_stock_availability(self):
        raw = raw_bundle()
        raw.tables["sales"] = raw.tables["sales"].drop(columns="stockout_flag")
        report = validate_dataset(raw, as_of=AS_OF)
        self.assertFalse(report.has_errors)
        self.assertTrue(report.dataset.tables["sales"].stockout_flag.isna().all())
        self.assertTrue(report.summary.forecast_ready.all())
        products = report.dataset.tables["products"]
        self.assertEqual(products.loc[0, "review_period_days"], 7)
        self.assertEqual(products.loc[0, "service_level"], .95)
        raw.tables["sales"]["stockout_flag"] = "yes"
        self.assertTrue(validate_dataset(raw, as_of=AS_OF).has_errors)

    def test_malformed_csv_records_are_not_silently_reindexed(self):
        for content in (b"date,product_id,units_sold\n2026-01-01,001,3,4\n",
                        b"date,product_id,units_sold\n2026-01-01,001\n",
                        b'date,product_id,units_sold\n"2026-01-01,001,3\n'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                load_csv_bundle({"sales": content}, "Malformed")

    def test_text_exports_do_not_execute_formulas(self):
        encoded = csv_bytes(pd.DataFrame({"product_id": ["=SUM(1+1)", "001"], "quantity": [0, 5]}))
        self.assertIn(b"'=SUM(1+1)", encoded)
        self.assertIn(b"001,5", encoded)


class StockoutTrainingTests(unittest.TestCase):
    def test_stockouts_excluded_from_scoring_and_imputed_from_training_only(self):
        raw = raw_bundle()
        raw.tables["sales"].loc[7, ["stockout_flag", "units_sold"]] = ["true", "0"]
        # A much later observation must never affect the earlier fold's substitution.
        raw.tables["sales"].loc[21, "units_sold"] = "900"
        validated = validate_dataset(raw, as_of=AS_OF).dataset.tables["sales"]
        ordinary = prepare_training_series(validated, "001", "2026-01-14")
        day = ordinary.loc[ordinary.date == pd.Timestamp("2026-01-08")].iloc[0]
        self.assertFalse(day.score_eligible)
        self.assertTrue(pd.isna(day.fit_units))
        imputed = prepare_training_series(validated, "001", "2026-01-14", impute_stockouts=True)
        day = imputed.loc[imputed.date == pd.Timestamp("2026-01-08")].iloc[0]
        self.assertEqual(day.fit_units, 3)
        self.assertEqual(day.observed_units, 0)
        self.assertTrue(day.stockout_imputed)
        self.assertFalse(day.score_eligible)
        self.assertEqual(validated.loc[7, "units_sold"], 0)

    def test_all_stockouts_and_missing_quantity_fail_clearly(self):
        raw = raw_bundle()
        raw.tables["sales"]["stockout_flag"] = "true"
        validated = validate_dataset(raw, as_of=AS_OF).dataset.tables["sales"]
        with self.assertRaisesRegex(ValueError, "non-stockout"):
            prepare_training_series(validated, "001", "2026-01-28", impute_stockouts=True)
        validated.loc[0, "units_sold"] = pd.NA
        with self.assertRaisesRegex(ValueError, "Missing sales quantities"):
            prepare_training_series(validated, "001", "2026-01-28")


class UploadInterfaceTests(unittest.TestCase):
    def test_failed_upload_preserves_current_dataset_and_shows_preview(self):
        app = AppTest.from_function(render_failed_replacement, args=(valid_files(),), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["dataset"].source, "Good upload")
        self.assertTrue(app.session_state["upload_attempt"].has_errors)
        self.assertTrue(any(expander.label == "Preview of rejected upload" for expander in app.expander))

    def test_confirmation_changes_data_and_readiness(self):
        files = valid_files()
        files["sales"] = files["sales"].replace(b"2026-01-10,001,3,false\n", b"")
        app = AppTest.from_function(render_upload_flow, args=(files,), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["dataset"].tables["sales"]), 55)
        app.multiselect[0].select("001").run()
        next(button for button in app.button if button.label == "Confirm listed dates as zero sales").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["dataset"].tables["sales"]), 56)
        self.assertTrue(app.session_state["validation_report"].summary.forecast_ready.all())
        self.assertEqual(app.session_state["validation_report"].zero_fill_products, ("001",))


if __name__ == "__main__":
    unittest.main()
