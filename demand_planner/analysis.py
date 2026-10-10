"""Orchestrate validated data through current forecasting and evaluation engines."""
import pandas as pd
from demand_planner.domain import AnalysisResults, DatasetBundle, PlanningSettings
from demand_planner.evaluation.backtesting import rolling_backtest
from demand_planner.forecasting.baseline import HORIZONS, forecast_baseline
from demand_planner.forecasting.regression import fit_regression, predict_artifact, forecast_regression
from demand_planner.evaluation.selection import compare_models
from demand_planner.forecasting.uncertainty import estimate_ranges, add_ranges
from demand_planner.inventory.planning import plan_inventory


def run_baseline_analysis(dataset: DatasetBundle, settings: PlanningSettings) -> AnalysisResults:
    sales, products = dataset.tables["sales"], dataset.tables["products"]
    if not pd.api.types.is_datetime64_any_dtype(sales.date):
        raise ValueError("Load and validate CSV data before running analysis.")
    cutoff = sales.date.max()
    forecasts, predictions, folds, summaries = [], [], [], []
    for product_id in products.product_id:
        history = sales.loc[sales.product_id == product_id]
        forecasts.append(forecast_baseline(history, product_id, cutoff, settings.horizon_days))
        for horizon in HORIZONS:
            predicted, fold_table, summary = rolling_backtest(history, product_id, horizon, end_date=cutoff)
            if not predicted.empty:
                predictions.append(predicted)
            if not fold_table.empty:
                folds.append(fold_table)
            summaries.append(summary)
    evaluation = pd.DataFrame(summaries).merge(products[["product_id", "product_name"]], on="product_id", validate="many_to_one")
    return AnalysisResults(input_fingerprint=dataset.fingerprint, settings=settings, data_source=dataset.source,
                           daily_forecasts=pd.concat(forecasts, ignore_index=True), evaluation=evaluation,
                           backtest_predictions=pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
                           backtest_folds=pd.concat(folds, ignore_index=True) if folds else pd.DataFrame())


def run_model_analysis(dataset: DatasetBundle, settings: PlanningSettings) -> AnalysisResults:
    """Compare on identical folds, freeze selection before audit, refit at store cutoff."""
    result = run_baseline_analysis(dataset, settings)
    sales, products = dataset.tables["sales"], dataset.tables["products"]
    cutoff = sales.date.max()
    comparisons, candidates, selected_forecasts, intervals, range_audits = [], [], [], [], []
    for product_id in products.product_id:
        history = sales.loc[sales.product_id == product_id]
        cache = {}

        def cached_forecast(frame, item, origin, horizon):
            if origin not in cache:
                try:
                    cache[origin] = fit_regression(frame, item, origin)
                except ValueError:
                    cache[origin] = None
            return predict_artifact(cache[origin], horizon) if cache[origin] is not None else forecast_regression(frame, item, origin, horizon)

        decisions, product_candidates = {}, []
        for horizon in HORIZONS:
            ml, _, _ = rolling_backtest(history, product_id, horizon, end_date=cutoff, forecaster=cached_forecast)
            baseline = result.backtest_predictions
            if baseline.empty:
                baseline, _, _ = rolling_backtest(history, product_id, horizon, end_date=cutoff)
            else:
                baseline = baseline.loc[(baseline.product_id == product_id) & (baseline.horizon_days == horizon)]
            joined, comparison = compare_models(baseline, ml, product_id, horizon)
            comparisons.append(comparison)
            if not joined.empty:
                candidates.append(joined)
            product_candidates.append(joined)
            decisions[horizon] = comparison
        try:
            model = fit_regression(history, product_id, cutoff)
            result.trained_models[product_id] = {"status": "trained", "model": model}
        except ValueError as exc:
            model = None
            result.trained_models[product_id] = {"status": "unavailable", "reason": str(exc)}
        joined_tables = [table for table in product_candidates if not table.empty]
        joined_candidates = pd.concat(joined_tables, ignore_index=True) if joined_tables else product_candidates[0]
        for horizon in HORIZONS:
            decision = decisions[horizon]
            chosen = "ml" if decision["selected_model"] == "ml" and model is not None else "baseline"
            forecast = (predict_artifact(model, horizon) if chosen == "ml" else forecast_baseline(history, product_id, cutoff, horizon))
            forecast["selected_model"] = chosen
            forecast["selection_reason"] = decision["selection_reason"] if decision["selected_model"] == chosen else "Baseline retained: ML refit unavailable at current cutoff."
            interval, audit = estimate_ranges(joined_candidates, product_id, horizon, chosen)
            intervals.append(interval)
            if not audit.empty:
                audit["range_model"] = chosen
                range_audits.append(audit)
            selected_forecasts.append(add_ranges(forecast, interval))
    result.future_forecasts = pd.concat(selected_forecasts, ignore_index=True)
    result.daily_forecasts = result.future_forecasts.loc[result.future_forecasts.horizon_days == settings.horizon_days].reset_index(drop=True)
    result.interval_evaluation = pd.DataFrame(intervals)
    result.interval_audit_predictions = pd.concat(range_audits, ignore_index=True) if range_audits else pd.DataFrame()
    result.model_comparison = pd.DataFrame(comparisons).merge(products[["product_id", "product_name"]], on="product_id", validate="many_to_one")
    result.candidate_predictions = pd.concat(candidates, ignore_index=True) if candidates else pd.DataFrame()
    result.inventory_projection, result.reorder_suggestions = plan_inventory(dataset, result.future_forecasts, settings)
    for name in ("daily_forecasts", "future_forecasts", "inventory_projection", "reorder_suggestions", "evaluation",
                 "backtest_predictions", "backtest_folds", "model_comparison", "candidate_predictions",
                 "interval_evaluation", "interval_audit_predictions"):
        frame = getattr(result, name)
        if not frame.empty:
            frame["data_source"] = dataset.source
            frame["synthetic_data"] = dataset.source == "Synthetic sample"
    return result
