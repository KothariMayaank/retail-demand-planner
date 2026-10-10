"""Shared formatting keeps displayed units consistent without changing results."""
import streamlit as st


def inventory_columns():
    return {
        "product_id": "Product ID", "product_name": "Product", "attention": "Action to review",
        "estimated_stockout_date": st.column_config.DateColumn("Estimated shortage", format="YYYY-MM-DD"),
        "suggested_order_units": st.column_config.NumberColumn("Suggested order (units)", format="%d"),
        "on_hand_units": st.column_config.NumberColumn("Current stock (units)", format="%.0f"),
        "incoming_protection_units": st.column_config.NumberColumn("Incoming within planning period (units)", format="%.0f"),
        "lead_time_days": "Lead time (days)", "review_period_days": "Review interval (days)", "status": "Planning status"}
