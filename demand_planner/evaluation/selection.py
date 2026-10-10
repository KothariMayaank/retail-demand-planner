"""Select on older development folds; reserve newer folds for independent audit."""
import pandas as pd
from demand_planner.evaluation.metrics import forecast_metrics

SELECTION_VERSION = "older-three-mae-five-percent-v1"
MIN_IMPROVEMENT = 0.05
MIN_COVERAGE = 0.8


def compare_models(baseline, ml, product_id, horizon):
    keys = ["product_id", "horizon_days", "forecast_origin", "date", "fold"]
    joined = baseline.merge(ml[keys + ["predicted_units", "score_eligible"]], on=keys, how="left",
                            suffixes=("", "_ml"), validate="one_to_one")
    origins = sorted(joined.forecast_origin.unique())
    # For fewer than six folds we cannot provide the required 3+3 split.
    development = origins[:3] if len(origins) == 6 else []
    audit = origins[3:] if len(origins) == 6 else origins[-3:]
    joined["partition"] = "diagnostic"
    joined.loc[joined.forecast_origin.isin(development), "partition"] = "development"
    joined.loc[joined.forecast_origin.isin(audit), "partition"] = "audit"
    joined["paired_eligible"] = joined.score_eligible & joined.score_eligible_ml.fillna(False).astype(bool)
    record = {"product_id": product_id, "horizon_days": horizon, "selected_model": "baseline",
              "selection_version": SELECTION_VERSION, "required_improvement_percent": 5.0,
              "development_folds": len(development), "audit_folds": len(audit),
              "selection_available_at": pd.Timestamp(development[-1]) + pd.Timedelta(days=horizon) if development else pd.NaT}
    for partition in ("development", "audit"):
        rows = joined.loc[joined.partition.eq(partition) & joined.paired_eligible]
        for model, column in (("baseline", "predicted_units"), ("ml", "predicted_units_ml")):
            metrics = forecast_metrics(rows.actual_units, rows[column])
            for name in ("mae", "wape_percent", "scored_days", "rmse", "bias_units"):
                record[f"{partition}_{model}_{name}"] = metrics[name]
    dev = joined.loc[joined.partition.eq("development")]
    coverage_ok = len(development) == 3 and all(
        group.paired_eligible.sum() >= MIN_COVERAGE * horizon and group.predicted_units_ml.notna().all()
        for _, group in dev.groupby("forecast_origin"))
    baseline_mae, ml_mae = record["development_baseline_mae"], record["development_ml_mae"]
    if not coverage_ok:
        record["selection_reason"] = "Baseline retained: need six folds and three development folds with complete ML predictions and at least 80% paired coverage each."
    elif baseline_mae is None or baseline_mae <= 0:
        record["selection_reason"] = "Baseline retained: no positive baseline error to improve."
    elif ml_mae <= baseline_mae * (1 - MIN_IMPROVEMENT):
        record["selected_model"] = "ml"
        record["selection_reason"] = "ML selected: development MAE improves by at least 5% on identical scored dates."
    else:
        record["selection_reason"] = "Baseline retained: ML does not improve development MAE by at least 5%."
    record["development_improvement_percent"] = 100 * (1 - ml_mae / baseline_mae) if baseline_mae and ml_mae is not None else None
    chosen = record["selected_model"]
    # Candidate comparisons need identical dates, but the selected policy still
    # has a measurable audit when the unselected candidate is unavailable.
    eligibility = "score_eligible_ml" if chosen == "ml" else "score_eligible"
    prediction = "predicted_units_ml" if chosen == "ml" else "predicted_units"
    own_audit = joined.loc[joined.partition.eq("audit") & joined[eligibility].fillna(False).astype(bool)]
    for name, value in forecast_metrics(own_audit.actual_units, own_audit[prediction]).items():
        record[f"audit_selected_{name}"] = value
    record["audit_note"] = ("ML performed worse in the reserved audit; selection remains frozen from development."
        if chosen == "ml" and record["audit_ml_mae"] is not None and
        record["audit_ml_mae"] > record["audit_baseline_mae"] else "")
    return joined, record
