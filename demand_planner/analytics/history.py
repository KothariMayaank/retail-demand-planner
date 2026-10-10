"""Calendar-aware observed-sales summaries; missing observations never become zero."""
from dataclasses import dataclass
import pandas as pd

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class SalesMetrics:
    total_units: int | None
    average_daily_units: float | None
    zero_sales_percent: float | None
    recorded_days: int
    expected_days: int
    missing_days: int
    stockout_days: int
    confirmed_zero_days: int
    unknown_availability_days: int


def daily_history(sales: pd.DataFrame, product_id: str, start, end, rolling_days: int = 7) -> pd.DataFrame:
    """Inclusive date filter and a trailing full-calendar-window rolling mean.

    The calendar extends over the selected range, but dates before a product's
    first observation or after the store cutoff are outside established history.
    Rolling averages use only selected dates, require every day in the window,
    and include observed stockout sales. No demand reconstruction is performed.
    """
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start > end:
        raise ValueError("Start date must be on or before end date.")
    if rolling_days not in (7, 14, 28):
        raise ValueError("Rolling window must be 7, 14 or 28 calendar days.")
    if not pd.api.types.is_datetime64_any_dtype(sales.date):
        raise ValueError("Load and validate CSV data before exploring historical sales.")
    if sales.duplicated(["product_id", "date"]).any():
        raise ValueError("Duplicate daily observations must be resolved before exploration.")
    history = sales.loc[sales.product_id == product_id].copy()
    if "is_zero_filled" not in history:
        history["is_zero_filled"] = False
    history = history.set_index("date").sort_index()
    calendar = pd.date_range(start, end, freq="D", name="date")
    daily = history.reindex(calendar)[["units_sold", "stockout_flag", "is_zero_filled"]].copy()
    daily["product_id"] = product_id
    daily["units_sold"] = pd.array(daily.units_sold, dtype="Int64")
    daily["stockout_flag"] = pd.array(daily.stockout_flag, dtype="boolean")
    daily["is_zero_filled"] = daily.is_zero_filled.astype("boolean").fillna(False).astype(bool)
    daily["recorded"] = daily.units_sold.notna()
    daily["in_established_history"] = False
    if not history.empty:
        daily["in_established_history"] = (daily.index >= history.index.min()) & (daily.index <= sales.date.max())
    daily["status"] = "Recorded"
    daily.loc[daily.stockout_flag.isna() & daily.recorded, "status"] = "Availability unknown"
    daily.loc[daily.is_zero_filled, "status"] = "Confirmed zero"
    daily.loc[daily.stockout_flag.fillna(False), "status"] = "Known stockout"
    daily.loc[~daily.recorded & daily.in_established_history, "status"] = "Missing record"
    daily.loc[~daily.in_established_history, "status"] = "Outside product history"
    daily["rolling_average"] = daily.units_sold.astype(float).rolling(rolling_days, min_periods=rolling_days).mean()
    return daily.reset_index()


def summarize_sales(daily: pd.DataFrame) -> SalesMetrics:
    recorded = daily.loc[daily.recorded]
    count = len(recorded)
    # Python integer summation avoids overflow in signed-64-bit aggregate totals.
    total = sum(int(value) for value in recorded.units_sold) if count else None
    return SalesMetrics(
        total_units=total, average_daily_units=total / count if count else None,
        zero_sales_percent=100 * int(recorded.units_sold.eq(0).sum()) / count if count else None,
        recorded_days=count, expected_days=int(daily.in_established_history.sum()),
        missing_days=int(daily.status.eq("Missing record").sum()),
        stockout_days=int(recorded.stockout_flag.fillna(False).sum()),
        confirmed_zero_days=int(recorded.is_zero_filled.sum()),
        unknown_availability_days=int(recorded.stockout_flag.isna().sum()),
    )


def weekday_summary(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for number, name in enumerate(WEEKDAYS):
        group = daily.loc[daily.date.dt.dayofweek == number]
        metrics = summarize_sales(group)
        rows.append({"weekday": name, "total_units": metrics.total_units,
                     "average_daily_units": metrics.average_daily_units, "recorded_days": metrics.recorded_days,
                     "missing_days": metrics.missing_days, "zero_sales_percent": metrics.zero_sales_percent,
                     "stockout_days": metrics.stockout_days})
    return pd.DataFrame(rows)


def flagged_periods(daily: pd.DataFrame) -> pd.DataFrame:
    """Compact, inclusive spans for stockouts, gaps and confirmed zero records."""
    rows = []
    for status in ("Known stockout", "Missing record", "Confirmed zero", "Outside product history"):
        dates = daily.loc[daily.status == status, "date"]
        if dates.empty:
            continue
        groups = dates.diff().ne(pd.Timedelta(days=1)).cumsum()
        for _, span in dates.groupby(groups):
            rows.append({"status": status, "start_date": span.min(), "end_date": span.max(), "days": len(span)})
    return pd.DataFrame(rows, columns=["status", "start_date", "end_date", "days"]).sort_values(
        "start_date", ignore_index=True)


def compare_products(sales: pd.DataFrame, products: pd.DataFrame, product_ids: list[str], start, end) -> pd.DataFrame:
    rows = []
    for product in products.loc[products.product_id.isin(product_ids)].itertuples():
        metrics = summarize_sales(daily_history(sales, product.product_id, start, end))
        rows.append({"product_id": product.product_id, "product_name": product.product_name,
                     "total_units": metrics.total_units, "average_daily_units": metrics.average_daily_units,
                     "zero_sales_percent": metrics.zero_sales_percent, "recorded_days": metrics.recorded_days,
                     "expected_days": metrics.expected_days, "missing_days": metrics.missing_days,
                     "coverage_percent": 100 * metrics.recorded_days / metrics.expected_days if metrics.expected_days else None,
                     "stockout_days": metrics.stockout_days, "confirmed_zero_days": metrics.confirmed_zero_days})
    columns = ["product_id", "product_name", "total_units", "average_daily_units", "zero_sales_percent",
               "recorded_days", "expected_days", "missing_days", "coverage_percent", "stockout_days", "confirmed_zero_days"]
    result = pd.DataFrame(rows, columns=columns)
    result["total_units"] = pd.array(result.total_units, dtype="Int64")
    return result.sort_values(["total_units", "product_id"], ascending=[False, True], na_position="last", ignore_index=True)
