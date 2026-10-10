"""Run with: python -m streamlit run app.py"""
import streamlit as st
from demand_planner.ui import screens
from demand_planner.ui.historical_sales import historical_sales
from demand_planner.ui.forecasting import forecasting_screen
from demand_planner.ui.inventory import inventory_screen
from demand_planner.ui.state import initialize_state, invalidate_results
from demand_planner.config import public_demo_mode, save_local_runs

st.set_page_config(page_title="Retail Demand Planner", page_icon="📦", layout="wide")
initialize_state()
if public_demo_mode():
    st.info("Synthetic portfolio demo — all data and reported results are simulated. Uploads are disabled; no analysis files are saved on the server.")
elif st.session_state.dataset is not None and st.session_state.dataset.source == "Synthetic sample":
    st.info("Synthetic demonstration data — forecasts, evaluation scores and order suggestions are simulated, not real-store results.")
with st.sidebar:
    st.title("Retail Demand Planner")
    st.caption("One store · Sales and inventory planning")
    st.selectbox("Forecast horizon (days)", [7, 14, 28], key="horizon_days", on_change=invalidate_results)
    st.number_input("Review interval (days)", min_value=1, max_value=27,
                    key="review_period_days", on_change=invalidate_results)
    st.selectbox("Safety-stock policy", ["demand_days", "fixed_units", "none"],
                 format_func=lambda value: {"demand_days": "Days of forecast demand", "fixed_units": "Fixed units", "none": "No buffer"}[value],
                 key="safety_stock_policy", on_change=invalidate_results)
    if st.session_state.safety_stock_policy == "demand_days":
        st.number_input("Buffer days", min_value=0.0, max_value=28.0, step=0.5,
                        key="safety_stock_days", on_change=invalidate_results)
    elif st.session_state.safety_stock_policy == "fixed_units":
        st.number_input("Buffer units", min_value=0, key="safety_stock_units", on_change=invalidate_results)
    st.caption("Buffers are planning choices, not guaranteed service levels. Product review intervals override the default when supplied.")
    st.caption("Analysis files are saved locally under outputs/runs." if save_local_runs() else "Results stay in this session and can be downloaded. No analysis files are saved.")
    st.caption("No paid services or ordering integrations.")

page = st.navigation([
    st.Page(screens.data_setup, title="Data & Setup", default=True, url_path="setup"),
    st.Page(screens.overview, title="Overview", url_path="overview"),
    st.Page(historical_sales, title="Sales History", url_path="history"),
    st.Page(forecasting_screen, title="Forecasts", url_path="forecast"),
    st.Page(inventory_screen, title="Inventory Planning", url_path="inventory"),
    st.Page(screens.historical_evaluation, title="Model Performance", url_path="evaluation"),
    st.Page(screens.downloads, title="Export Results", url_path="downloads"),
])
page.run()
