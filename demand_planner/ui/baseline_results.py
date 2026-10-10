"""Baseline forecasts and rolling-backtest results for the dashboard."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from demand_planner.domain import AnalysisResults
from demand_planner.data.exporting import csv_bytes
from demand_planner.ui.history_charts import values, TEAL, AMBER, RED
from demand_planner.ui.state import current_settings


def active_results() -> AnalysisResults | None:
    dataset, result = st.session_state.dataset, st.session_state.results
    if (dataset is not None and isinstance(result, AnalysisResults)
            and result.input_fingerprint == dataset.fingerprint and result.settings == current_settings()):
        return result
    return None


def prediction_chart(rows: pd.DataFrame) -> go.Figure:
    rows = rows.sort_values("date")
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=rows.date, y=values(rows.actual_units), name="Actual observed sales",
                               mode="lines+markers", line={"color": TEAL}, connectgaps=False,
                               hovertemplate="%{x|%d %b %Y}<br>Actual: %{y:.0f} units<extra></extra>"))
    figure.add_trace(go.Scatter(x=rows.date, y=values(rows.predicted_units), name="Weekday baseline",
                               mode="lines+markers", line={"color": AMBER, "dash": "dash"}, connectgaps=False,
                               customdata=rows.method.tolist(),
                               hovertemplate="%{x|%d %b %Y}<br>Prediction: %{y:.2f} units<br>%{customdata}<extra></extra>"))
    if "predicted_units_ml" in rows:
        figure.add_trace(go.Scatter(x=rows.date, y=values(rows.predicted_units_ml), name="ML regression",
                                   mode="lines+markers", line={"color": "#6C4AB6", "dash": "dot"}, connectgaps=False))
    stockouts = rows.loc[rows.stockout_flag.fillna(False).astype(bool)]
    if not stockouts.empty:
        figure.add_trace(go.Scatter(x=stockouts.date, y=values(stockouts.actual_units),
                                   name="Known stockout (not scored)", mode="markers",
                                   marker={"color": RED, "size": 10, "symbol": "diamond"}))
    figure.update_layout(height=410, template="plotly_white", hovermode="x unified",
                         margin={"l": 20, "r": 20, "t": 70, "b": 55},
                         legend={"orientation": "h", "y": 1.15, "yanchor": "bottom", "x": 0}, xaxis_title="Forecast target date",
                         yaxis={"title": "Units sold", "rangemode": "tozero"})
    return figure


def evaluation_screen() -> None:
    st.title("Model Performance")
    st.write("Compare forecasts with actual sales in rolling time-based tests.")
    if st.session_state.dataset is None:
        st.info("No data loaded. Open Data & Setup to load sample data or upload your CSVs.")
        return
    result = active_results()
    if result is None:
        st.info("Open Data & Setup and run analysis to generate baseline forecasts and backtests.")
        return
    st.caption("Fixed baseline, up to six non-overlapping folds per product/horizon, with at least 56 calendar "
               "training days. Each forecast starts the day after its origin. No future sales enter fitting.")
    summary = result.evaluation
    if not result.model_comparison.empty:
        st.subheader("ML versus baseline — selection and reserved audit")
        st.caption("ML must reduce MAE by at least 5% on the older three development folds. The newest three folds "
                   "are a reserved audit and do not change selection. Both models are compared on identical eligible dates. "
                   "Short histories or inadequate paired coverage retain the baseline.")
        comparison_columns = ["product_id", "product_name", "horizon_days", "selected_model", "development_baseline_mae",
                              "development_ml_mae", "development_improvement_percent", "audit_baseline_mae", "audit_ml_mae",
                              "audit_baseline_wape_percent", "audit_ml_wape_percent", "audit_ml_scored_days", "selection_reason", "audit_note"]
        comparison_display = result.model_comparison[comparison_columns].rename(columns={
            "product_id": "Product ID", "product_name": "Product", "horizon_days": "Horizon (days)",
            "selected_model": "Selected model", "development_baseline_mae": "Development baseline MAE",
            "development_ml_mae": "Development ML MAE", "development_improvement_percent": "Development improvement (%)",
            "audit_baseline_mae": "Audit baseline MAE", "audit_ml_mae": "Audit ML MAE",
            "audit_baseline_wape_percent": "Audit baseline WAPE (%)", "audit_ml_wape_percent": "Audit ML WAPE (%)",
            "audit_ml_scored_days": "Paired audit days", "selection_reason": "Selection reason", "audit_note": "Audit note"})
        st.dataframe(comparison_display, hide_index=True,
                     column_config={name: st.column_config.NumberColumn(format="%.3f") for name in comparison_display if "MAE" in name})
        st.download_button("Download model comparison", csv_bytes(result.model_comparison), file_name="model_comparison.csv", mime="text/csv")
    st.subheader("Baseline results by product and horizon — all folds")
    columns = ["product_id", "product_name", "horizon_days", "mae", "wape_percent", "scored_days", "scored_folds",
               "attempted_folds", "stockout_targets", "missing_actual_days", "unavailable_prediction_days", "status", "note"]
    display = summary[columns].rename(columns={"product_id": "Product ID", "product_name": "Product",
        "horizon_days": "Horizon (days)", "mae": "MAE (units/day)", "wape_percent": "WAPE (%)",
        "scored_days": "Scored days", "scored_folds": "Scored folds", "attempted_folds": "Attempted folds",
        "stockout_targets": "Stockout targets", "missing_actual_days": "Missing actual days",
        "unavailable_prediction_days": "Unavailable prediction days", "status": "Status", "note": "Note"})
    st.dataframe(display, hide_index=True, column_config={"MAE (units/day)": st.column_config.NumberColumn(format="%.3f"),
                                                         "WAPE (%)": st.column_config.NumberColumn(format="%.1f")})
    st.caption("MAE is mean absolute error over eligible dates. WAPE is pooled absolute error divided by pooled actual "
               "sales, expressed as a percentage. Zero actual totals leave WAPE unavailable; MAE remains defined. "
               "Known stockout targets and missing actuals are excluded. Partial rows have fewer folds or exclusions.")
    st.download_button("Download baseline evaluation", csv_bytes(summary), file_name="baseline_evaluation.csv",
                       mime="text/csv", key="evaluation_summary")
    filters = st.columns(2)
    names = summary.drop_duplicates("product_id").set_index("product_id").product_name.to_dict()
    product_id = filters[0].selectbox("Evaluation product", list(names), format_func=lambda item: f"{names[item]} ({item})",
                                     key=f"evaluation_product_{result.input_fingerprint}")
    horizon = filters[1].selectbox("Evaluation horizon (days)", [7, 14, 28],
                                   index=[7, 14, 28].index(result.settings.horizon_days),
                                   key=f"evaluation_horizon_{result.input_fingerprint}")
    selected = summary.loc[(summary.product_id == product_id) & (summary.horizon_days == horizon)].iloc[0]
    if not result.model_comparison.empty:
        decision = result.model_comparison.loc[(result.model_comparison.product_id == product_id) & (result.model_comparison.horizon_days == horizon)].iloc[0]
        st.info(decision.selection_reason)
        if decision.audit_note:
            st.warning(decision.audit_note)
        audit_metrics = st.columns(3)
        audit_metrics[0].metric("Audit baseline MAE", "Unavailable" if pd.isna(decision.audit_baseline_mae) else f"{decision.audit_baseline_mae:.3f}")
        audit_metrics[1].metric("Audit ML MAE", "Unavailable" if pd.isna(decision.audit_ml_mae) else f"{decision.audit_ml_mae:.3f}")
        audit_metrics[2].metric("Selected model", "ML regression" if decision.selected_model == "ml" else "Baseline")
        st.caption(f"Audit comparison covers {int(decision.audit_ml_scored_days)} identical scored dates.")
        selected_error = "unavailable" if pd.isna(decision.audit_selected_mae) else f"{decision.audit_selected_mae:.3f} units/day"
        st.caption(f"The selected model's own audit MAE is {selected_error} across {int(decision.audit_selected_scored_days)} eligible dates. "
                   "This denominator may exceed the paired comparison when the other candidate is unavailable.")
        st.caption("The metrics below describe the baseline across all available folds. "
                   "Independent paired audit metrics for both models appear in the comparison table above.")
    metrics = st.columns(3)
    metrics[0].metric("MAE (units/day)", "Unavailable" if pd.isna(selected.mae) else f"{selected.mae:.3f}")
    metrics[1].metric("WAPE", "Unavailable" if pd.isna(selected.wape_percent) else f"{selected.wape_percent:.1f}%")
    metrics[2].metric("Scored days", int(selected.scored_days))
    if selected.note:
        st.info(selected.note)
    if result.backtest_predictions.empty:
        return
    predictions = result.backtest_predictions.loc[(result.backtest_predictions.product_id == product_id) &
                                                  (result.backtest_predictions.horizon_days == horizon)]
    if predictions.empty:
        return
    origins = sorted(predictions.forecast_origin.unique())
    origin = st.selectbox("Forecast origin (last training day)", origins, index=len(origins) - 1,
                          format_func=lambda item: pd.Timestamp(item).date().isoformat(),
                          key=f"evaluation_origin_{result.input_fingerprint}_{product_id}_{horizon}")
    fold = predictions.loc[predictions.forecast_origin == origin].copy()
    if not result.candidate_predictions.empty:
        fold = result.candidate_predictions.loc[(result.candidate_predictions.product_id == product_id) &
            (result.candidate_predictions.horizon_days == horizon) & (result.candidate_predictions.forecast_origin == origin)].copy()
        st.caption(f"Window purpose: {fold.partition.iloc[0]}")
    st.subheader("Predictions against actual sales" if "predicted_units_ml" in fold else "Baseline predictions against actual sales")
    st.caption(f"{names[product_id]} ({product_id}) · {horizon}-day test. "
               f"Training uses only dates through {pd.Timestamp(origin).date()}. "
               f"Forecast targets: {fold.date.min().date()} through {fold.date.max().date()}.")
    st.plotly_chart(prediction_chart(fold), use_container_width=True, key="baseline_actual_chart", config={"displaylogo": False})
    table_columns = ["date", "actual_units", "predicted_units", "method", "score_eligible", "exclusion_reason", "absolute_error_units"]
    if "predicted_units_ml" in fold:
        table_columns += ["predicted_units_ml", "paired_eligible", "partition"]
    st.dataframe(fold[table_columns].rename(columns={"date": "Date", "actual_units": "Actual units",
                       "predicted_units": "Predicted units", "method": "Method", "score_eligible": "Scored",
                       "exclusion_reason": "Exclusion reason", "absolute_error_units": "Absolute error"}), hide_index=True)
    with st.expander("All folds for this product and horizon"):
        st.dataframe(result.backtest_folds.loc[(result.backtest_folds.product_id == product_id) &
                                              (result.backtest_folds.horizon_days == horizon)], hide_index=True)
    st.download_button("Download selected backtest predictions", csv_bytes(predictions),
                       file_name=f"baseline_backtest_{product_id}_{horizon}d.csv", mime="text/csv")


def product_forecast(product_id: str) -> bool:
    result = active_results()
    if result is None:
        return False
    forecast = result.daily_forecasts.loc[result.daily_forecasts.product_id == product_id]
    label = "ML regression" if "selected_model" in forecast and forecast.selected_model.eq("ml").all() else "Baseline"
    st.subheader(f"{label} forecast — next {result.settings.horizon_days} days")
    if "selection_reason" in forecast:
        st.caption(forecast.selection_reason.iloc[0])
    if not forecast.predicted_units.notna().any():
        st.warning(str(forecast.reason.iloc[0]))
    else:
        st.caption("ML forecasts recursively reuse predictions; baseline forecasts use recent weekdays or the recent mean. "
                   "Open Forecasts for prediction ranges and Inventory Planning for stock recommendations.")
        history = st.session_state.dataset.tables["sales"]
        origin = forecast.forecast_origin.iloc[0]
        history = history.loc[(history.product_id == product_id) & (history.date <= origin) &
                              (history.date >= origin - pd.Timedelta(days=55))]
        figure = go.Figure()
        figure.add_trace(go.Scatter(x=history.date, y=values(history.units_sold), name="Historical sales",
                                   mode="lines", line={"color": TEAL}, connectgaps=False))
        figure.add_trace(go.Scatter(x=forecast.date, y=values(forecast.predicted_units), name=f"{label} forecast",
                                   mode="lines+markers", line={"color": AMBER, "dash": "dash"}, connectgaps=False))
        figure.update_layout(height=350, template="plotly_white", xaxis_title="Date",
                             yaxis={"title": "Units", "rangemode": "tozero"})
        st.plotly_chart(figure, use_container_width=True, key="product_baseline_chart", config={"displaylogo": False})
    st.dataframe(forecast[["date", "predicted_units", "method", "matching_days", "status", "reason"]], hide_index=True)
    return True
