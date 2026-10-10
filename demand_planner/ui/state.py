import streamlit as st
from demand_planner.domain import PlanningSettings
from demand_planner.config import load_config


def initialize_state() -> None:
    config = load_config()
    defaults = {"dataset": None, "results": None, "upload_revision": 0,
                "validation_report": None, "upload_attempt": None, "upload_error": None,
                "horizon_days": config.forecast_horizon_days,
                "review_period_days": config.review_period_days,
                "service_level": config.service_level, "safety_stock_policy": config.safety_stock_policy,
                "safety_stock_days": config.safety_stock_days, "safety_stock_units": config.safety_stock_units}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def invalidate_results() -> None:
    st.session_state.results = None
    report = st.session_state.get("validation_report")
    if report is not None and report.default_review_period_days != st.session_state.review_period_days:
        from demand_planner.data.validation import validate_dataset
        refreshed = validate_dataset(report.raw, zero_fill_products=report.zero_fill_products,
                                     default_review_period_days=st.session_state.review_period_days)
        st.session_state.validation_report = refreshed
        st.session_state.dataset = refreshed.dataset


def clear_data() -> None:
    st.session_state.dataset = None
    st.session_state.results = None
    st.session_state.upload_revision += 1
    st.session_state.validation_report = None
    st.session_state.upload_attempt = None
    st.session_state.upload_error = None


def current_settings() -> PlanningSettings:
    config = load_config()
    return PlanningSettings(horizon_days=st.session_state.horizon_days,
                            review_period_days=st.session_state.review_period_days,
                            service_level=st.session_state.service_level,
                            random_seed=config.random_seed,
                            simulation_count=config.simulation_count,
                            safety_stock_policy=st.session_state.safety_stock_policy,
                            safety_stock_days=st.session_state.safety_stock_days,
                            safety_stock_units=st.session_state.safety_stock_units)
