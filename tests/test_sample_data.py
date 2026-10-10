"""Validate the generated fixture against the agreed input and demo contracts."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from demand_planner.config import load_config
from demand_planner.data.schemas import SCHEMAS
from scripts.generate_sample_data import generate


class SampleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = load_config().sample_directory
        cls.manifest = json.loads((cls.directory / "manifest.json").read_text(encoding="utf-8"))
        cls.tables = {name: pd.read_csv(cls.directory / f"{name}.csv", keep_default_na=False,
                                      dtype={"product_id": str}) for name in SCHEMAS}
        cls.truth = pd.read_csv(cls.directory / "reference/demand_reference.csv", keep_default_na=False)

    def test_exact_schemas_and_supplier_parameters(self):
        for name, table in self.tables.items():
            with self.subTest(table=name):
                template = pd.read_csv(self.directory.parent / "templates" / f"{name}.csv")
                self.assertEqual(list(table.columns), list(template.columns))
                self.assertEqual(set(table.columns), set(SCHEMAS[name].required + SCHEMAS[name].optional))
                self.assertFalse(table.isna().any().any())
        products = self.tables["products"]
        self.assertEqual(len(products), 20)
        self.assertTrue(products.product_id.is_unique)
        self.assertTrue(products.product_name.ne("").all())
        self.assertTrue(products.lead_time_days.between(1, 28).all())
        self.assertTrue((products.lead_time_days + products.review_period_days <= 28).all())
        self.assertTrue(products.service_level.between(.80, .99).all())
        for column, minimum in (("lead_time_days", 1), ("review_period_days", 1),
                                ("pack_size", 1), ("minimum_order_qty", 0)):
            self.assertTrue(pd.api.types.is_integer_dtype(products[column]))
            self.assertTrue((products[column] >= minimum).all())

    def test_daily_grid_ids_dates_and_integer_quantities(self):
        products, sales = self.tables["products"], self.tables["sales"]
        ids = set(products.product_id)
        self.assertEqual(len(sales), 14600)
        self.assertFalse(sales.duplicated(["date", "product_id"]).any())
        expected = pd.date_range("2024-10-10", "2026-10-09").strftime("%Y-%m-%d").tolist()
        for product_id, group in sales.groupby("product_id"):
            self.assertIn(product_id, ids)
            self.assertEqual(group.date.tolist(), expected)
        for name, table in self.tables.items():
            self.assertTrue(set(table.product_id) <= ids)
        for table, column in ((sales, "units_sold"), (self.tables["inventory"], "on_hand_units"),
                              (self.tables["receipts"], "quantity_units")):
            self.assertTrue(pd.api.types.is_integer_dtype(table[column]))
            self.assertTrue((table[column] >= 0).all())
        self.assertEqual(set(sales.stockout_flag), {True, False})
        for value in sales.date.unique():
            self.assertEqual(date.fromisoformat(value).isoformat(), value)

    def test_inventory_cutoff_and_receipts(self):
        inventory, receipts = self.tables["inventory"], self.tables["receipts"]
        self.assertEqual(set(inventory.product_id), set(self.tables["products"].product_id))
        self.assertTrue(inventory.product_id.is_unique)
        self.assertEqual(set(inventory.snapshot_date), {self.tables["sales"].date.max()})
        self.assertTrue(receipts.receipt_id.is_unique)
        self.assertTrue((receipts.quantity_units > 0).all())
        self.assertTrue((receipts.expected_date > "2026-10-09").all())

    def test_stockouts_reconcile_sales_and_demand(self):
        truth = self.truth
        sales = self.tables["sales"]
        joined = sales.merge(truth, on=["date", "product_id"], validate="one_to_one")
        self.assertEqual(len(joined), len(sales))
        self.assertTrue((joined.units_sold == joined.observed_sales_units).all())
        for column in ("latent_demand_units", "observed_sales_units", "lost_sales_units"):
            self.assertTrue(pd.api.types.is_integer_dtype(joined[column]))
            self.assertTrue((joined[column] >= 0).all())
        self.assertTrue((joined.latent_demand_units - joined.units_sold == joined.lost_sales_units).all())
        affected = joined.loc[joined.stockout_flag]
        self.assertEqual(len(affected), 9)
        self.assertEqual(set(affected.product_id), {"P003", "P006", "P015"})
        self.assertTrue(affected.stockout_event_id.ne("").all())
        self.assertTrue((affected.lost_sales_units > 0).all())
        availability = pd.to_numeric(affected.available_units_on_stockout_day)
        self.assertTrue((affected.units_sold == pd.concat([affected.latent_demand_units, availability], axis=1).min(axis=1)).all())
        self.assertTrue((joined.loc[~joined.stockout_flag].lost_sales_units == 0).all())
        events = pd.read_csv(self.directory / "reference/stockout_events.csv")
        self.assertTrue(events.stockout_event_id.is_unique)
        self.assertEqual(set(events.stockout_event_id), set(affected.stockout_event_id))

    def test_patterns_promotions_and_intermittency(self):
        truth = self.truth.copy()
        truth["day"] = pd.to_datetime(truth.date)
        water = truth.loc[truth.product_id == "P006"]
        self.assertGreater(water.loc[water.day.dt.weekday >= 5].latent_demand_units.mean(),
                           water.loc[water.day.dt.weekday < 5].latent_demand_units.mean())
        self.assertGreater(water.loc[water.day.dt.month.isin([5, 6])].latent_demand_units.mean(),
                           water.loc[water.day.dt.month.isin([11, 12])].latent_demand_units.mean())
        means = truth.groupby("product_id").latent_demand_units.mean()
        self.assertGreater(means.max(), means.min() * 20)
        for product_id in ("P017", "P018", "P019", "P020"):
            units = truth.loc[truth.product_id == product_id].latent_demand_units
            self.assertGreater(units.eq(0).mean(), .70)
            self.assertGreater(units.gt(0).sum(), 20)
        events = pd.read_csv(self.directory / "reference/promotions.csv")
        self.assertTrue(events.promotion_id.is_unique)
        self.assertEqual(len(events), 14)
        for event in events.itertuples():
            rows = truth.loc[truth.promotion_id == event.promotion_id]
            self.assertEqual(len(rows), 7)
            self.assertEqual(set(rows.product_id), {event.product_id})
            self.assertEqual(rows.date.min(), event.start_date)
            self.assertEqual(rows.date.max(), event.end_date)
            self.assertTrue((rows.promotion_multiplier == event.demand_multiplier).all())
        self.assertTrue((truth.loc[truth.promotion_id == ""].promotion_multiplier == 1).all())

    def test_reproducibility_and_manifest(self):
        self.assertIs(self.manifest["is_synthetic"], True)
        self.assertEqual(self.manifest["lost_sales_units"], int(self.truth.lost_sales_units.sum()))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            generate(destination)
            generated = [*self.manifest["sha256"], "manifest.json"]
            for relative in generated:
                with self.subTest(file=relative):
                    committed = (self.directory / relative).read_bytes()
                    self.assertEqual(committed, (destination / relative).read_bytes())
                    if relative != "manifest.json":
                        self.assertEqual(sha256(committed).hexdigest(), self.manifest["sha256"][relative])


if __name__ == "__main__":
    unittest.main()
