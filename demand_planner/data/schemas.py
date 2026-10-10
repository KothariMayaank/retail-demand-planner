from dataclasses import dataclass


@dataclass(frozen=True)
class CsvSchema:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


SCHEMAS = {
    "products": CsvSchema(("product_id", "product_name", "lead_time_days"),
                          ("category", "review_period_days", "service_level", "pack_size", "minimum_order_qty")),
    "sales": CsvSchema(("date", "product_id", "units_sold"), ("stockout_flag",)),
    "inventory": CsvSchema(("snapshot_date", "product_id", "on_hand_units")),
    "receipts": CsvSchema(("receipt_id", "product_id", "expected_date", "quantity_units")),
}
REQUIRED_TABLES = ("products", "sales", "inventory")
