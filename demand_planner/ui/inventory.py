"""Inventory recommendations and projections using unrounded forecast demand."""
import plotly.graph_objects as go
import streamlit as st
from demand_planner.data.exporting import csv_bytes
from demand_planner.ui.baseline_results import active_results
from demand_planner.ui.presentation import inventory_columns


def inventory_screen():
    st.title("Inventory Planning")
    st.write("Review shortages first, then quantities to replenish at this review.")
    result = active_results()
    if result is None or result.reorder_suggestions.empty:
        st.info("Load data and run analysis in Data & Setup to calculate inventory recommendations.")
        return
    summary = result.reorder_suggestions
    ready = summary.loc[summary.status == "ready"]
    columns = st.columns(3)
    columns[0].metric("Products with projected shortages", int(ready.estimated_stockout_date.notna().sum()))
    columns[1].metric("Products to order", int(ready.suggested_order_units.gt(0).sum()))
    columns[2].metric("Suggested order units", int(ready.suggested_order_units.sum()) if len(ready) else "Unavailable")
    if len(ready) < len(summary):
        st.warning(f"Planning is unavailable for {len(summary) - len(ready)} products. Review their data or lead-time/review window before placing orders.")
    st.caption("Uses each product's selected 28-day forecast, regardless of the sales display horizon. "
               "Stockouts are estimates; orders and buffers cannot guarantee prevention. "
               "Listed receipts arrive in full at the start of their expected date; missing receipts mean none assumed. "
               "The protection period is supplier lead time plus the review interval.")
    display = ["product_id", "product_name", "attention", "estimated_stockout_date", "suggested_order_units",
               "on_hand_units", "incoming_protection_units", "lead_time_days", "review_period_days", "status"]
    st.dataframe(summary[display], hide_index=True, column_config=inventory_columns())
    ids = summary.product_id.tolist()
    names = summary.set_index("product_id").product_name.to_dict()
    selected = st.selectbox("Product to inspect", ids, format_func=lambda value: f"{names[value]} ({value})")
    row = summary.loc[summary.product_id == selected].iloc[0]
    st.subheader(row.attention)
    st.write(row.explanation)
    if row.status == "ready":
        columns = st.columns(4)
        for column, label, value in zip(columns, ["Lead-time demand (units)", "Reorder point (units)", "Target stock (units)", "Suggested order (units)"],
                                         [row.lead_time_demand_units, row.reorder_point_units, row.target_stock_units, row.suggested_order_units]):
            column.metric(label, f"{value:,.2f}" if label != "Suggested order (units)" else f"{value:,d}")
        st.caption(f"Raw replenishment gap: {row.raw_order_units:.2f} units. Pack size: {row.pack_size}; minimum positive order: {row.minimum_order_qty}. "
                   f"Safety buffer: {row.safety_stock_units:.2f} units. Next review: {row.next_review_date.date()}. "
                   f"An order placed now is assumed to arrive {row.suggested_order_arrival_date.date()}.")
        projection = result.inventory_projection.loc[result.inventory_projection.product_id == selected]
        figure = go.Figure()
        figure.add_scatter(x=projection.date, y=projection.closing_stock_units, name="Closing stock", mode="lines")
        figure.add_scatter(x=projection.date, y=projection.forecast_demand_units, name="Forecast daily demand", mode="lines")
        figure.add_bar(x=projection.date, y=projection.incoming_units, name="Listed deliveries", opacity=0.5)
        figure.update_layout(xaxis_title="Date", yaxis_title="Units", legend=dict(orientation="h"))
        st.plotly_chart(figure, use_container_width=True)
        st.caption("Projection includes current stock and listed receipts. Suggested orders are excluded until recorded as receipts. "
                   "Unmet demand is treated as lost sales, without backorders. Forecasts and projected stock retain fractional units.")
        st.dataframe(projection, hide_index=True, column_config={
            "product_id": "Product ID", "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            **{name: st.column_config.NumberColumn(label, format="%.2f") for name, label in {
                "opening_stock_units": "Opening stock (units)", "incoming_units": "Incoming (units)",
                "available_units": "Available (units)", "forecast_demand_units": "Forecast demand (units)",
                "fulfilled_units": "Fulfilled demand (units)", "unmet_demand_units": "Unmet demand (units)",
                "closing_stock_units": "Closing stock (units)"}.items()}})
    st.download_button("Download reorder suggestions", csv_bytes(summary), "reorder_suggestions.csv", "text/csv")
    if not result.inventory_projection.empty:
        st.download_button("Download stock projections", csv_bytes(result.inventory_projection), "inventory_projection.csv", "text/csv")
