"""Recent non-overlapping rolling-origin windows for a fixed baseline model."""
import pandas as pd
from demand_planner.evaluation.metrics import forecast_metrics
from demand_planner.forecasting.baseline import HORIZONS, forecast_baseline

MIN_TRAINING_DAYS = 56
MAX_FOLDS = 6


def rolling_backtest(sales: pd.DataFrame, product_id: str, horizon: int, *,
                     end_date=None, max_folds: int = MAX_FOLDS,
                     forecaster=forecast_baseline) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Backtest latest complete H-day blocks, stepping the training origin by H.

    Minimum initial calendar history is 56 days. Known stockout targets, missing
    actuals, and unavailable predictions are not scored. Every excluded target is
    retained with a reason. Pooled errors define product/horizon metrics, rather
    than averages of fold percentages. No model is selected using these results.
    """
    if horizon not in HORIZONS or max_folds < 1:
        raise ValueError("Use a 7-, 14- or 28-day horizon and a positive fold count.")
    product_sales = sales.loc[sales.product_id == product_id].copy()
    cutoff = pd.Timestamp(end_date if end_date is not None else sales.date.max()).normalize()
    first = product_sales.date.min()
    origins = []
    if pd.notna(first) and pd.notna(cutoff):
        for number in range(max_folds):
            origin = cutoff - pd.Timedelta(days=(number + 1) * horizon)
            if (origin - first).days + 1 >= MIN_TRAINING_DAYS:
                origins.append(origin)
    predictions, folds = [], []
    for number, origin in enumerate(sorted(origins), start=1):
        forecast = forecaster(product_sales, product_id, origin, horizon)
        actuals = product_sales[["date", "units_sold", "stockout_flag"]].rename(columns={"units_sold": "actual_units"})
        forecast = forecast.merge(actuals, on="date", how="left", validate="one_to_one")
        forecast["fold"] = number
        known_stockout = forecast.stockout_flag.fillna(False).astype(bool)
        missing_actual = forecast.actual_units.isna()
        missing_prediction = forecast.predicted_units.isna()
        forecast["score_eligible"] = ~known_stockout & ~missing_actual & ~missing_prediction
        forecast["exclusion_reason"] = ""
        forecast.loc[known_stockout, "exclusion_reason"] = "Known stockout target"
        forecast.loc[missing_actual, "exclusion_reason"] = "Missing actual sales"
        forecast.loc[missing_prediction, "exclusion_reason"] = "Unavailable forecast: " + forecast.loc[missing_prediction, "reason"]
        forecast["absolute_error_units"] = (forecast.predicted_units - forecast.actual_units.astype(float)).abs().where(forecast.score_eligible)
        scored = forecast.loc[forecast.score_eligible]
        metrics = forecast_metrics(scored.actual_units, scored.predicted_units)
        folds.append({"product_id": product_id, "horizon_days": horizon, "fold": number,
                      "forecast_origin": origin, "test_start": origin + pd.Timedelta(days=1),
                      "test_end": origin + pd.Timedelta(days=horizon), **metrics,
                      "stockout_targets": int(known_stockout.sum()), "missing_actual_days": int(missing_actual.sum()),
                      "unavailable_prediction_days": int(missing_prediction.sum()),
                      "fallback_prediction_days": int(forecast.method.eq("recent_mean_28d_fallback").sum())})
        predictions.append(forecast)
    prediction_columns = ["product_id", "forecast_origin", "date", "horizon_days", "predicted_units", "method",
                          "matching_days", "training_observations", "recent_observations", "status", "reason", "model_version",
                          "actual_units", "stockout_flag", "fold", "score_eligible", "exclusion_reason", "absolute_error_units"]
    prediction_table = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(columns=prediction_columns)
    for column in ("forecast_origin", "date"):
        prediction_table[column] = pd.to_datetime(prediction_table[column])
    fold_columns = ["product_id", "horizon_days", "fold", "forecast_origin", "test_start", "test_end", "scored_days",
                    "actual_units", "absolute_error_units", "mae", "wape_percent", "rmse", "bias_units", "stockout_targets", "missing_actual_days",
                    "unavailable_prediction_days", "fallback_prediction_days"]
    fold_table = pd.DataFrame(folds, columns=fold_columns)
    for column in ("forecast_origin", "test_start", "test_end"):
        fold_table[column] = pd.to_datetime(fold_table[column])
    for column in ("actual_units", "absolute_error_units", "mae", "wape_percent", "rmse", "bias_units"):
        fold_table[column] = pd.to_numeric(fold_table[column]).astype(float)
    scored = prediction_table.loc[prediction_table.score_eligible.astype(bool)]
    metrics = forecast_metrics(scored.actual_units, scored.predicted_units)
    summary = {"product_id": product_id, "horizon_days": horizon, **metrics,
               "attempted_folds": len(fold_table), "scored_folds": int(fold_table.scored_days.gt(0).sum()),
               "stockout_targets": int(fold_table.stockout_targets.sum()),
               "missing_actual_days": int(fold_table.missing_actual_days.sum()),
               "unavailable_prediction_days": int(fold_table.unavailable_prediction_days.sum()),
               "fallback_prediction_days": int(fold_table.fallback_prediction_days.sum()),
               "evaluation_start": prediction_table.date.min() if not prediction_table.empty else pd.NaT,
               "evaluation_end": prediction_table.date.max() if not prediction_table.empty else pd.NaT,
               "status": "unavailable" if not metrics["scored_days"] else
                         "partial" if len(folds) < max_folds or metrics["scored_days"] < len(prediction_table) else "complete",
               "note": "Insufficient history: at least 56 training days plus one full test horizon are needed." if not folds else
                       "No eligible actual/predicted pairs; inspect fold exclusions." if not metrics["scored_days"] else
                       "WAPE unavailable because scored actual sales total zero." if metrics["actual_units"] == 0 else ""}
    return prediction_table, fold_table, summary
