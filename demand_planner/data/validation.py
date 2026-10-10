"""Strict CSV validation and auditable daily preprocessing; no UI dependencies."""
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256
import math
import re
from typing import Protocol
from zoneinfo import ZoneInfo
import pandas as pd
from demand_planner.data.schemas import REQUIRED_TABLES, SCHEMAS
from demand_planner.domain import DatasetBundle


@dataclass(frozen=True)
class ValidationIssue:
    table: str
    message: str
    severity: str = "error"
    row: int | None = None
    product_id: str = ""
    code: str = ""


class DatasetValidator(Protocol):
    def validate(self, dataset: DatasetBundle) -> list[ValidationIssue]: ...


def check_structure(tables: dict[str, pd.DataFrame]) -> list[ValidationIssue]:
    issues = []
    for name in REQUIRED_TABLES:
        if name not in tables:
            issues.append(ValidationIssue(name, "Required CSV is missing."))
    for name, table in tables.items():
        if name not in SCHEMAS:
            issues.append(ValidationIssue(name, "Unknown input table."))
            continue
        schema = SCHEMAS[name]
        missing = set(schema.required) - set(table.columns)
        if missing:
            issues.append(ValidationIssue(name, "Missing columns: " + ", ".join(sorted(missing))))
        if table.empty and name != "receipts":
            issues.append(ValidationIssue(name, "CSV contains no data rows."))
    return issues


@dataclass
class ValidationReport:
    raw: DatasetBundle
    dataset: DatasetBundle | None
    issues: list[ValidationIssue]
    summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_dates: pd.DataFrame = field(default_factory=pd.DataFrame)
    zero_fill_products: tuple[str, ...] = ()
    default_review_period_days: int = 7

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    def issue_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{"severity": issue.severity, "file": f"{issue.table}.csv",
                              "row": issue.row, "product_id": issue.product_id,
                              "code": issue.code, "message": issue.message} for issue in self.issues],
                            columns=["severity", "file", "row", "product_id", "code", "message"])


def validate_dataset(raw: DatasetBundle, *, zero_fill_products: tuple[str, ...] = (),
                     as_of: date | None = None, default_review_period_days: int = 7) -> ValidationReport:
    """Validate values and joins, then sort and optionally fill explicitly approved gaps.

    Dates before a product's first observation are outside its established history.
    All later missing dates through the shared sales cutoff are forecast blockers.
    CSV row numbers count the header as row 1; input tables remain untouched.
    """
    as_of = as_of or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if not 1 <= default_review_period_days <= 27:
        raise ValueError("Default review interval must be between 1 and 27 days.")
    issues = check_structure(raw.tables)
    report = ValidationReport(raw, None, issues, zero_fill_products=tuple(sorted(set(zero_fill_products))),
                              default_review_period_days=default_review_period_days)
    if report.has_errors:
        return report
    tables = {name: frame.copy(deep=True).reset_index(drop=True) for name, frame in raw.tables.items()}

    def add(name, message, code, index=None, product_id="", severity="error"):
        if index is not None and not product_id and "product_id" in tables[name]:
            product_id = str(tables[name].at[index, "product_id"])
        issues.append(ValidationIssue(name, message, severity,
                                      int(index) + 2 if index is not None else None, product_id, code))

    def integer_column(name, column, minimum=0, maximum=2**63 - 1, default=None):
        values = []
        if column not in tables[name]:
            tables[name][column] = str(default) if default is not None else ""
        for index, value in tables[name][column].items():
            text = str(value).strip()
            if not text and default is not None:
                values.append(default)
                continue
            # Avoid float conversion, integer precision loss and excessive digit parsing.
            stripped = text.lstrip("0") or "0"
            if not re.fullmatch(r"[0-9]+", text) or len(stripped) > 19:
                add(name, f"{column} must be a whole number of at least {minimum}; blanks are not zero.", "quantity", index)
                values.append(pd.NA)
                continue
            number = int(stripped)
            if not minimum <= number <= maximum:
                add(name, f"{column} must be between {minimum} and {maximum}.", "quantity", index)
                values.append(pd.NA)
            else:
                values.append(number)
        tables[name][column] = pd.array(values, dtype="Int64")

    def date_column(name, column):
        values = []
        for index, value in tables[name][column].items():
            text = str(value)
            parsed = pd.NaT
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
                    raise ValueError("format")
                parsed = pd.Timestamp(date.fromisoformat(text))
                # Enforce the supported pandas nanosecond date range explicitly.
                _ = parsed.value
            except (ValueError, OverflowError):
                parsed = pd.NaT
                add(name, f"{column} must be a valid YYYY-MM-DD date in the supported 1678–2261 range.", "date", index)
            values.append(parsed)
        tables[name][column] = pd.to_datetime(values)

    for name, frame in tables.items():
        extras = set(frame.columns) - set(SCHEMAS[name].required + SCHEMAS[name].optional)
        if extras:
            add(name, "Additional columns are ignored: " + ", ".join(sorted(extras)), "extra_columns", severity="warning")
            tables[name] = frame.drop(columns=list(extras))
        for column in ("product_id", "receipt_id"):
            if column not in tables[name]:
                continue
            for index, value in tables[name][column].items():
                text = str(value)
                if not text.strip() or text != text.strip():
                    add(name, f"{column} must be nonblank text without surrounding spaces. IDs are case-sensitive.", "identifier", index)

    products = tables["products"]
    for index, value in products.product_name.items():
        if not str(value).strip():
            add("products", "product_name must not be blank.", "missing_value", index)
    products["review_period_is_override"] = products["review_period_days"].astype(str).str.strip().ne("") if "review_period_days" in products else False
    for column, minimum, maximum, default in (
        ("lead_time_days", 1, 28, None), ("review_period_days", 1, 27, default_review_period_days),
        ("pack_size", 1, 2**63 - 1, 1), ("minimum_order_qty", 0, 2**63 - 1, 0)):
        integer_column("products", column, minimum, maximum, default)
    if "service_level" not in products:
        products["service_level"] = ""
    levels = []
    for index, value in products.service_level.items():
        try:
            level = .95 if not str(value).strip() else float(value)
            if not math.isfinite(level) or not .80 <= level <= .99:
                raise ValueError("range")
            levels.append(level)
        except (ValueError, TypeError):
            levels.append(float("nan"))
            add("products", "service_level must be between 0.80 and 0.99; blank uses 0.95.", "service_level", index)
    products["service_level"] = levels

    date_column("sales", "date")
    integer_column("sales", "units_sold")
    sales = tables["sales"]
    if "stockout_flag" not in sales:
        sales["stockout_flag"] = ""
    flags = []
    for index, value in sales.stockout_flag.items():
        text = str(value).strip().lower()
        if text not in ("", "true", "false"):
            add("sales", "stockout_flag must be true, false or blank (unknown availability).", "stockout_flag", index)
        flags.append({"true": True, "false": False}.get(text, pd.NA))
    sales["stockout_flag"] = pd.array(flags, dtype="boolean")
    sales["is_zero_filled"] = False
    for index in sales.index[sales.date >= pd.Timestamp(as_of)]:
        add("sales", f"Sales must cover complete days before {as_of.isoformat()}; today's or future sales are not accepted.", "incomplete_day", index)

    date_column("inventory", "snapshot_date")
    integer_column("inventory", "on_hand_units")
    if "receipts" in tables:
        date_column("receipts", "expected_date")
        integer_column("receipts", "quantity_units", minimum=1)

    keys = {"products": ["product_id"], "sales": ["product_id", "date"],
            "inventory": ["product_id"], "receipts": ["receipt_id"]}
    ids = set(products.product_id)
    for name, frame in tables.items():
        for index in frame.index[frame.duplicated(keys[name], keep=False)]:
            add(name, "Duplicate record for " + ", ".join(keys[name]) + "; correct or aggregate it before upload.", "duplicate", index)
        if name != "products":
            for index in frame.index[~frame.product_id.isin(ids)]:
                add(name, "Product ID is not listed in products.csv.", "unknown_product", index)
    for product_id in set(zero_fill_products) - ids:
        add("sales", "Zero-sales confirmation refers to an unknown product.", "zero_confirmation", product_id=product_id)

    cutoff = sales.date.max()
    inventory = tables["inventory"]
    if pd.notna(cutoff):
        for index in inventory.index[inventory.snapshot_date.notna() & (inventory.snapshot_date != cutoff)]:
            add("inventory", f"snapshot_date must match the final complete sales date, {cutoff.date().isoformat()}.", "snapshot_mismatch", index)
        if "receipts" in tables:
            receipts = tables["receipts"]
            for index in receipts.index[receipts.expected_date.notna() & (receipts.expected_date <= cutoff)]:
                add("receipts", "Expected receipt is overdue at the inventory snapshot; correct its date or remove it.", "overdue_receipt", index)
        if (as_of - cutoff.date()).days > 7:
            add("sales", f"Latest sales are {(as_of - cutoff.date()).days} days old. Inventory planning is anchored to this historical cutoff.", "stale_data", severity="warning")
    if report.has_errors:
        return report

    summary, gaps, fills = [], [], []
    first_store_date = sales.date.min()
    for product in products.itertuples():
        product_id = product.product_id
        history = sales.loc[sales.product_id == product_id].sort_values("date")
        has_inventory = product_id in set(inventory.product_id)
        protection_ok = product.lead_time_days + product.review_period_days <= 28
        if not has_inventory:
            add("inventory", "No inventory row for this product; its forecast is allowed but inventory planning is unavailable.", "missing_inventory", product_id=product_id, severity="warning")
        if not protection_ok:
            add("products", "Lead time plus review interval exceeds 28 days; inventory recommendations are unavailable.", "protection_period", product_id=product_id, severity="warning")
        if history.empty:
            add("sales", "No sales history for this product; forecasting is unavailable.", "missing_history", product_id=product_id, severity="warning")
            summary.append({"product_id": product_id, "recorded_days": 0, "expected_days": 0,
                            "missing_days": 0, "zero_filled_days": 0, "known_stockout_days": 0,
                            "unknown_availability_days": 0, "forecast_ready": False, "inventory_ready": False})
            continue
        expected = pd.date_range(history.date.min(), cutoff, freq="D")
        missing = expected.difference(pd.DatetimeIndex(history.date))
        confirmed = product_id in zero_fill_products
        for day in missing:
            gaps.append({"product_id": product_id, "date": day, "confirmed_zero": confirmed})
            if confirmed:
                fills.append({"product_id": product_id, "date": day, "units_sold": 0,
                              "stockout_flag": pd.NA, "is_zero_filled": True})
        remaining = 0 if confirmed else len(missing)
        if len(missing):
            message = (f"{len(missing)} missing dates explicitly confirmed as zero sales. Availability remains unknown."
                       if confirmed else f"{len(missing)} missing dates from the first observation through the store cutoff. "
                       "Forecasting is blocked until corrected or explicitly confirmed as zero sales.")
            add("sales", message, "confirmed_zero" if confirmed else "missing_dates", product_id=product_id, severity="warning")
        if history.date.min() > first_store_date:
            add("sales", "History starts after other products. Earlier dates remain outside this product's established history; no zeros were added there.", "later_start", product_id=product_id, severity="warning")
        known_stockouts = int(history.stockout_flag.fillna(False).sum())
        unknown = int(history.stockout_flag.isna().sum()) + (len(missing) if confirmed else 0)
        if known_stockouts:
            add("sales", f"{known_stockouts} known stockout days. Observed sales may understate demand; these targets are excluded from evaluation and ordinary fitting.", "stockouts", product_id=product_id, severity="warning")
        if unknown:
            add("sales", f"Stock availability is unknown on {unknown} days. Their observed sales remain usable; lost demand cannot be identified.", "unknown_availability", product_id=product_id, severity="warning")
        usable_days = len(history) + (len(missing) if confirmed else 0) - known_stockouts
        if usable_days < 14:
            add("sales", "Fewer than 14 usable days; forecasting is unavailable.", "short_history", product_id=product_id, severity="warning")
        elif len(expected) < 56:
            add("sales", "Short history: forecasts are provisional and full model selection is unavailable.", "provisional_history", product_id=product_id, severity="warning")
        ordinary = history.loc[~history.stockout_flag.fillna(False), "units_sold"].astype(float)
        if len(ordinary) >= 28:
            q1, q3 = ordinary.quantile([.25, .75])
            spikes = int((ordinary > max(q3 + 3 * (q3 - q1), 3 * ordinary.median(), 5)).sum())
            if spikes:
                add("sales", f"{spikes} unusually high sales days. Review possible promotions or entry errors; no values were removed.", "sales_spikes", product_id=product_id, severity="warning")
        indexed = history.set_index("date").units_sold.reindex(expected)
        zero = indexed.eq(0)
        longest_zero_run = int(zero.groupby((~zero).cumsum()).sum().max())
        if longest_zero_run >= 14:
            add("sales", f"A zero-sales run lasts {longest_zero_run} days. Check inactivity or unrecorded stockouts; values are preserved.", "zero_run", product_id=product_id, severity="warning")
        ready = remaining == 0 and usable_days >= 14
        summary.append({"product_id": product_id, "recorded_days": len(history), "expected_days": len(expected),
                        "missing_days": remaining, "zero_filled_days": len(missing) if confirmed else 0,
                        "known_stockout_days": known_stockouts, "unknown_availability_days": unknown,
                        "forecast_ready": ready, "inventory_ready": ready and has_inventory and protection_ok})
    if fills:
        inserted = pd.DataFrame(fills).astype({"units_sold": "Int64", "stockout_flag": "boolean",
                                               "is_zero_filled": bool})
        sales = pd.concat([sales, inserted], ignore_index=True)
        sales["units_sold"] = pd.array(sales.units_sold, dtype="Int64")
        sales["stockout_flag"] = pd.array(sales.stockout_flag, dtype="boolean")
        sales["is_zero_filled"] = sales.is_zero_filled.astype(bool)
        tables["sales"] = sales
    tables["sales"] = tables["sales"].sort_values(["product_id", "date"]).reset_index(drop=True)
    tables["products"] = products.sort_values("product_id").reset_index(drop=True)
    tables["inventory"] = inventory.sort_values("product_id").reset_index(drop=True)
    if "receipts" in tables:
        tables["receipts"] = tables["receipts"].sort_values(["expected_date", "product_id"]).reset_index(drop=True)
    fingerprint = sha256((raw.fingerprint + "|confirmed_zero=" + repr(report.zero_fill_products)).encode()).hexdigest()
    report.dataset = DatasetBundle(tables, raw.source, fingerprint)
    report.summary = pd.DataFrame(summary)
    report.missing_dates = pd.DataFrame(gaps, columns=["product_id", "date", "confirmed_zero"])
    return report
