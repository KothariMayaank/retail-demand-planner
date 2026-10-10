"""Future point forecasts, empirical prediction ranges and historical diagnostics."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from demand_planner.data.exporting import csv_bytes
from demand_planner.ui.baseline_results import active_results
from demand_planner.ui.history_charts import values, TEAL, AMBER, RED


def forecast_chart(history, forecast):
    origin = forecast.forecast_origin.iloc[0]
    history = history.loc[(history.date <= origin) & (history.date >= origin - pd.Timedelta(days=83))].copy()
    if not history.empty:
        history = history.set_index("date").reindex(pd.date_range(history.date.min(), origin)).rename_axis("date").reset_index()
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=history.date, y=values(history.units_sold), name="Historical observed sales",
                               mode="lines", line={"color": TEAL}, connectgaps=False))
    if forecast.estimated_upper_units.notna().any():
        figure.add_trace(go.Scatter(x=forecast.date, y=values(forecast.estimated_upper_units), mode="lines",
                                   line={"width": 0}, showlegend=False, hoverinfo="skip", connectgaps=False))
        figure.add_trace(go.Scatter(x=forecast.date, y=values(forecast.estimated_lower_units), mode="lines",
                                   line={"width": 0}, fill="tonexty", fillcolor="rgba(108,74,182,0.18)",
                                   name="Estimated daily prediction range", hoverinfo="skip", connectgaps=False))
    figure.add_trace(go.Scatter(x=forecast.date, y=values(forecast.predicted_units), name="Future daily prediction",
                               mode="lines+markers", line={"color": AMBER, "dash": "dash"}, connectgaps=False,
                               hovertemplate="%{x|%d %b %Y}<br>Prediction: %{y:.2f} units<extra></extra>"))
    stockouts = history.loc[history.stockout_flag.fillna(False).astype(bool)]
    if not stockouts.empty:
        figure.add_trace(go.Scatter(x=stockouts.date, y=values(stockouts.units_sold), name="Known historical stockout",
                                   mode="markers", marker={"color": RED, "size": 8, "symbol": "diamond"}))
    figure.add_vline(x=origin.timestamp() * 1000, line_dash="dot", line_color="#777")
    figure.update_layout(height=430, template="plotly_white", hovermode="x unified",
                         margin={"l": 20, "r": 20, "t": 80, "b": 50},
                         legend={"orientation": "h", "y": 1.12, "yanchor": "bottom"},
                         xaxis_title="Date — dotted line marks last observed day",
                         yaxis={"title": "Units", "rangemode": "tozero"})
    return figure


def forecasting_screen():
    st.title("Forecasts")
    st.write("Explore future daily sales and estimated prediction ranges for one product.")
    if st.session_state.dataset is None:
        st.info("No data loaded. Open Data & Setup to load sample data or upload your CSVs.")
        return
    result = active_results()
    if result is None or result.future_forecasts.empty:
        st.info("Open Data & Setup and run analysis to generate forecasts and prediction ranges for all three horizons.")
        return
    products = st.session_state.dataset.tables["products"].set_index("product_id").product_name.to_dict()
    filters = st.columns(2)
    product_id = filters[0].selectbox("Forecast product", list(products), format_func=lambda item: f"{products[item]} ({item})",
                                     key=f"forecast_product_{result.input_fingerprint}")
    horizon = filters[1].selectbox("Forecast horizon", [7, 14, 28], index=[7, 14, 28].index(result.settings.horizon_days),
                                   key=f"forecast_view_horizon_{result.input_fingerprint}")
    forecast = result.future_forecasts.loc[(result.future_forecasts.product_id == product_id) &
                                           (result.future_forecasts.horizon_days == horizon)].copy()
    evaluation = result.interval_evaluation.loc[(result.interval_evaluation.product_id == product_id) &
                                               (result.interval_evaluation.horizon_days == horizon)].iloc[0]
    available = forecast.predicted_units.notna().all()
    model = "ML regression" if forecast.selected_model.iloc[0] == "ml" else "Weekday baseline"
    metrics = st.columns(3)
    metrics[0].metric("Forecast total (units)", f"{forecast.predicted_units.sum():,.2f}" if available else "Unavailable")
    metrics[1].metric("Average daily sales (units/day)", f"{forecast.predicted_units.mean():,.2f}" if available else "Unavailable")
    metrics[2].metric("Selected model", model)
    st.caption(f"{products[product_id]} ({product_id}) · Targets {forecast.date.min().date()} through {forecast.date.max().date()}. "
               f"Last observed store day: {forecast.forecast_origin.iloc[0].date()}.")
    st.caption(forecast.selection_reason.iloc[0])
    if not available:
        st.warning(f"Forecast unavailable: {forecast.reason.iloc[0]}")
    if evaluation.interval_status == "unavailable":
        st.info(evaluation.interval_reason)
    st.caption("Estimated prediction ranges target 80% daily coverage using earlier out-of-sample errors. "
               "They are not statistical confidence levels or a guarantee. Model selection and range calibration share "
               "the development windows; coverage is checked on separate later audit windows.")
    history = st.session_state.dataset.tables["sales"]
    history = history.loc[history.product_id == product_id]
    st.plotly_chart(forecast_chart(history, forecast), use_container_width=True, key="future_forecast_chart", config={"displaylogo": False})
    st.caption("Predictions are nonnegative fractional expected units. Bounds are clipped at zero. Values are displayed "
               "to two decimals; totals use unrounded daily predictions, and CSVs retain full precision. "
               "The daily ranges do not define a range for the combined forecast total. Gaps in history remain gaps.")
    st.subheader("Selected model — historical audit")
    st.caption("MAE measures the typical absolute daily error in units; lower is better. WAPE measures total absolute error "
               "as a percentage of actual sales and is unavailable when actual sales total zero. Coverage is the share of audit days inside the estimated range.")
    scores = st.columns(3)
    scores[0].metric("Audit MAE (units/day)", "Unavailable" if pd.isna(evaluation.audit_mae) else f"{evaluation.audit_mae:.3f}")
    scores[1].metric("Audit WAPE", "Unavailable" if pd.isna(evaluation.audit_wape_percent) else f"{evaluation.audit_wape_percent:.1f}%")
    scores[2].metric("Observed range coverage", "Unavailable" if pd.isna(evaluation.audit_coverage_percent) else f"{evaluation.audit_coverage_percent:.1f}%")
    st.caption(f"Calibration: {evaluation.calibration_days} eligible errors across {evaluation.calibration_folds} earlier folds. "
               f"Audit: {evaluation.audit_scored_days} eligible sales days; {evaluation.audit_covered_days} covered when ranges are available. "
               "Known stockout targets and missing actuals are excluded. Unknown availability remains usable; results concern observed sales.")
    if pd.notna(evaluation.audit_coverage_percent) and evaluation.audit_coverage_percent < 80:
        st.warning("Observed audit coverage is below the 80% target. The estimated range may be too narrow for this product and horizon.")
    if evaluation.error_radius_units == 0:
        st.info("Earlier backtest errors were zero at the chosen quantile. The estimated range has zero width; future variability may be larger.")
    comparison = result.model_comparison.loc[(result.model_comparison.product_id == product_id) & (result.model_comparison.horizon_days == horizon)].iloc[0]
    if comparison.audit_note:
        st.warning(comparison.audit_note)
    with st.expander("Historical model and range evaluation details"):
        st.dataframe(pd.DataFrame([evaluation]), hide_index=True)
        st.dataframe(pd.DataFrame([comparison]), hide_index=True)
    st.subheader("Future daily predictions")
    display = forecast[["date", "predicted_units", "estimated_lower_units", "estimated_upper_units", "status", "reason", "interval_status"]].rename(
        columns={"date": "Date", "predicted_units": "Predicted units", "estimated_lower_units": "Estimated lower units",
                 "estimated_upper_units": "Estimated upper units", "status": "Forecast status", "reason": "Reason", "interval_status": "Range status"})
    st.dataframe(display, hide_index=True, column_config={"Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                **{name: st.column_config.NumberColumn(format="%.2f") for name in ("Predicted units", "Estimated lower units", "Estimated upper units")}})
    forecast.insert(1, "product_name", products[product_id])
    st.download_button("Download forecast CSV", csv_bytes(forecast), file_name=f"forecast_{horizon}d.csv", mime="text/csv")
