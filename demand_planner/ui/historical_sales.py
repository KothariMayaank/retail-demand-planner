"""Historical sales exploration screen."""
from datetime import timedelta
import streamlit as st
from demand_planner.analytics.history import daily_history, summarize_sales, weekday_summary, compare_products, flagged_periods
from demand_planner.data.exporting import csv_bytes
from demand_planner.ui.history_charts import daily_chart, weekday_chart, comparison_chart


def historical_sales() -> None:
    st.title("Sales History")
    st.write("Explore recorded sales, weekday patterns and product totals over the same date range.")
    dataset = st.session_state.dataset
    if dataset is None:
        st.info("No data loaded. Open Data & Setup to load sample data or upload your CSVs.")
        return
    sales, products = dataset.tables["sales"], dataset.tables["products"]
    if sales.empty:
        st.info("No sales history is available. Load daily sales in Data & Setup.")
        return
    if not hasattr(sales.date, "dt"):
        st.info("Load and validate the dataset in Data & Setup before exploring its sales.")
        return
    st.caption(f"Source: {dataset.source}. All values below describe observed sales.")
    ids = products.product_id.tolist()
    names = products.set_index("product_id").product_name.to_dict()
    suffix = dataset.fingerprint
    minimum, maximum = sales.date.min().date(), sales.date.max().date()
    filters = st.columns([2, 2, 1])
    selected = filters[0].selectbox("Product", ids, format_func=lambda item: f"{names[item]} ({item})",
                                   key=f"history_product_{suffix}")
    dates = filters[1].date_input("Date range (inclusive)", value=(max(minimum, maximum - timedelta(days=89)), maximum),
                                  min_value=minimum, max_value=maximum, key=f"history_dates_{suffix}")
    window = filters[2].selectbox("Rolling average (days)", [7, 14, 28], key="history_rolling_days")
    if len(dates) != 2:
        st.info("Select both a start and an end date to display the history.")
        return
    start, end = dates
    if start > end:
        st.error("Choose a start date on or before the end date.")
        return
    daily = daily_history(sales, selected, start, end, window)
    metrics = summarize_sales(daily)
    columns = st.columns(3)
    columns[0].metric("Total units sold", f"{metrics.total_units:,}" if metrics.total_units is not None else "Unavailable")
    columns[1].metric("Average daily sales", f"{metrics.average_daily_units:.2f}" if metrics.average_daily_units is not None else "Unavailable")
    columns[2].metric("Days with zero sales", f"{metrics.zero_sales_percent:.1f}%" if metrics.zero_sales_percent is not None else "Unavailable")
    st.caption(f"Based on {metrics.recorded_days} recorded or confirmed days out of {metrics.expected_days} days "
               "of established history in this range. Averages and zero percentages exclude gaps and include "
               "observed stockout sales and explicitly confirmed zeros. Values are rounded for display.")
    if not metrics.recorded_days:
        st.info("No recorded sales for this product in the selected range. Unavailable values are not zero sales.")
    if metrics.missing_days:
        st.warning(f"{metrics.missing_days} missing {'day' if metrics.missing_days == 1 else 'days'}: "
                   "the total is incomplete. Gaps are excluded from metrics "
                   "and break both chart lines. Resolve them in Data & Setup.")
    if metrics.stockout_days:
        st.warning(f"{metrics.stockout_days} known stockout {'day' if metrics.stockout_days == 1 else 'days'}: "
                   "recorded sales may understate demand. "
                   "Red shading and diamonds identify these days.")
    if metrics.confirmed_zero_days:
        st.caption(f"{metrics.confirmed_zero_days} days were explicitly confirmed as zero sales; purple squares mark them.")
    if metrics.unknown_availability_days:
        st.caption(f"Stock availability is unknown on {metrics.unknown_availability_days} recorded days.")
    st.subheader("Daily sales")
    st.plotly_chart(daily_chart(daily, window), use_container_width=True, key="historical_daily", config={"displaylogo": False})
    st.caption(f"The {window}-day average uses complete trailing calendar windows within the selected range. "
               "It starts after the first full window and resumes only after a full window following a gap. "
               "Gray shading marks missing records; pale blue marks dates before this product's established history.")
    periods = flagged_periods(daily)
    if not periods.empty:
        with st.expander("Stockout periods, gaps and confirmed zeros", expanded=bool(metrics.missing_days or metrics.stockout_days)):
            st.dataframe(periods.rename(columns={"status": "Status", "start_date": "Start date",
                                                "end_date": "End date", "days": "Days"}), hide_index=True)
    st.subheader("Weekday patterns")
    weekdays = weekday_summary(daily)
    st.plotly_chart(weekday_chart(weekdays), use_container_width=True, key="historical_weekdays", config={"displaylogo": False})
    st.caption("Each bar averages the available recorded days for that weekday. Missing weekdays have no estimate. "
               "Stockouts and promotions can affect the observed pattern.")
    with st.expander("Daily values and weekday calculations"):
        st.dataframe(daily[["date", "units_sold", "rolling_average", "stockout_flag", "is_zero_filled", "status"]].rename(
            columns={"date": "Date", "units_sold": "Units sold", "rolling_average": "Rolling average",
                     "stockout_flag": "Known stockout", "is_zero_filled": "Confirmed zero", "status": "Status"}),
            hide_index=True, column_config={"Rolling average": st.column_config.NumberColumn(format="%.2f")})
        st.dataframe(weekdays.rename(columns={"weekday": "Weekday", "total_units": "Units sold",
                     "average_daily_units": "Average / day", "recorded_days": "Recorded days",
                     "missing_days": "Missing days", "zero_sales_percent": "Zero sales (%)", "stockout_days": "Stockout days"}),
                     hide_index=True, column_config={"Average / day": st.column_config.NumberColumn(format="%.2f"),
                                                    "Zero sales (%)": st.column_config.NumberColumn(format="%.1f")})
        st.download_button("Download filtered daily sales", csv_bytes(daily), file_name=f"historical_sales_{selected}.csv",
                           mime="text/csv")
    st.subheader("Compare product totals")
    comparison_ids = st.multiselect("Products to compare", ids, default=ids,
                                     format_func=lambda item: f"{names[item]} ({item})", key=f"history_compare_{suffix}")
    if not comparison_ids:
        st.info("Select at least one product to compare totals.")
        return
    comparison = compare_products(sales, products, comparison_ids, start, end)
    if comparison.missing_days.gt(0).any():
        st.warning("Amber bars have incomplete records. Compare their totals using the coverage shown in the table.")
    st.plotly_chart(comparison_chart(comparison, selected), use_container_width=True, key="historical_comparison",
                    config={"displaylogo": False})
    st.caption("All products use the selected dates. Coverage starts at each product's first observation; "
               "newer products can have fewer established days. Totals measure selling units, including packs as "
               "one unit, and do not represent revenue. Empty histories remain unavailable.")
    st.dataframe(comparison.rename(columns={"product_id": "Product ID", "product_name": "Product",
        "total_units": "Units sold", "average_daily_units": "Average / day", "zero_sales_percent": "Zero sales (%)",
        "recorded_days": "Recorded days", "expected_days": "Established days", "missing_days": "Missing days",
        "coverage_percent": "Coverage (%)", "stockout_days": "Stockout days", "confirmed_zero_days": "Confirmed zeros"}),
        hide_index=True, column_config={"Average / day": st.column_config.NumberColumn(format="%.2f"),
                                       "Zero sales (%)": st.column_config.NumberColumn(format="%.1f"),
                                       "Coverage (%)": st.column_config.NumberColumn(format="%.1f")})
    st.download_button("Download product comparison", csv_bytes(comparison), file_name="historical_product_comparison.csv",
                       mime="text/csv")
