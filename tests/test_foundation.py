import unittest
import pandas as pd
from streamlit.testing.v1 import AppTest
from demand_planner.config import PROJECT_ROOT, load_config
from demand_planner.data.loading import load_csv_bundle
from demand_planner.data.schemas import SCHEMAS
from demand_planner.data.validation import check_structure


def render_screen(name: str) -> None:
    from demand_planner.ui import screens
    from demand_planner.ui.state import initialize_state
    initialize_state()
    getattr(screens, name)()


class DataBoundaryTests(unittest.TestCase):
    def test_sample_bundle(self):
        config = load_config()
        files = {name: (config.sample_directory / f"{name}.csv").read_bytes() for name in SCHEMAS}
        dataset = load_csv_bundle(files, "Sample")
        self.assertEqual(check_structure(dataset.tables), [])
        self.assertEqual(len(dataset.tables["products"]), 20)
        self.assertEqual(len(dataset.tables["sales"]), 14600)
        self.assertEqual(dataset.fingerprint, load_csv_bundle(files, "Another source").fingerprint)

    def test_ids_and_gaps_are_not_coerced(self):
        dataset = load_csv_bundle({"sales": b"date,product_id,units_sold\n2025-01-01,001,0\n2025-01-03,001,NA\n"}, "Test")
        sales = dataset.tables["sales"]
        self.assertEqual(sales.product_id.tolist(), ["001", "001"])
        self.assertEqual(sales.units_sold.tolist(), ["0", "NA"])
        self.assertEqual(len(sales), 2)

    def test_bad_encoding_and_duplicate_headers(self):
        for content in (b"\xff", b"product_id,product_id\n001,001\n"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                load_csv_bundle({"products": content}, "Test")

    def test_missing_inputs_are_reported(self):
        issues = check_structure({"products": pd.DataFrame({"product_id": ["001"]})})
        self.assertTrue(any(issue.table == "inventory" for issue in issues))
        self.assertTrue(any("Missing columns" in issue.message for issue in issues))


class DashboardTests(unittest.TestCase):
    def test_entrypoint_sample_settings_and_reset(self):
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("No data loaded" in item.value for item in app.info))
        self.assertTrue(next(button for button in app.button if button.label == "Run analysis").disabled)
        next(button for button in app.button if button.label == "Load sample data").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["dataset"].tables["products"]), 20)
        self.assertEqual(len(app.session_state["dataset"].tables["sales"]), 14600)
        self.assertTrue(any("Stockout demonstration" in expander.label for expander in app.expander))
        self.assertEqual(set(app.session_state["dataset"].tables), set(SCHEMAS))
        app.session_state["results"] = "stale sentinel"
        app.selectbox(key="horizon_days").select(28).run()
        self.assertEqual(app.session_state["horizon_days"], 28)
        self.assertIsNone(app.session_state["results"])
        app.session_state["results"] = "stale sentinel"
        app.selectbox(key="safety_stock_policy").select("fixed_units").run()
        self.assertIsNone(app.session_state["results"])
        self.assertEqual(app.session_state["safety_stock_policy"], "fixed_units")
        next(button for button in app.button if button.label == "Clear loaded data").click().run()
        self.assertIsNone(app.session_state["dataset"])
        self.assertFalse(app.exception)

    def test_all_empty_screens(self):
        for name in ("overview", "product_detail", "historical_evaluation", "downloads"):
            with self.subTest(screen=name):
                app = AppTest.from_function(render_screen, args=(name,), default_timeout=30).run()
                self.assertFalse(app.exception)
                self.assertTrue(any("No data loaded" in item.value for item in app.info))

    def test_loaded_screens(self):
        config = load_config()
        dataset = load_csv_bundle({name: (config.sample_directory / f"{name}.csv").read_bytes()
                                   for name in SCHEMAS}, "Sample")
        for name in ("overview", "product_detail", "historical_evaluation", "downloads"):
            with self.subTest(screen=name):
                app = AppTest.from_function(render_screen, args=(name,), default_timeout=30)
                app.session_state["dataset"] = dataset
                app.run()
                self.assertFalse(app.exception)
                if name == "product_detail":
                    self.assertEqual(len(app.dataframe), 1)
                    app.selectbox[0].select("P020").run()
                    self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
