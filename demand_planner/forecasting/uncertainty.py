"""Empirical daily prediction ranges; calibration precedes the reserved audit."""
import math
import numpy as np
import pandas as pd
from demand_planner.evaluation.metrics import forecast_metrics

INTERVAL_VERSION = "development-absolute-error-80-v1"
TARGET_COVERAGE = 0.8
MIN_CALIBRATION_DAYS = 20


def estimate_ranges(candidates, product_id, horizon, model):
    if model not in ("baseline", "ml"):
        raise ValueError("Unknown model for prediction range calibration.")
    rows = candidates.loc[(candidates.product_id == product_id) & (candidates.horizon_days == horizon)].copy()
    prediction = "predicted_units_ml" if model == "ml" else "predicted_units"
    eligibility = "score_eligible_ml" if model == "ml" else "score_eligible"
    usable = rows[eligibility].fillna(False).astype(bool) & rows.actual_units.notna() & rows[prediction].notna()
    calibration = rows.loc[rows.partition.eq("development") & usable]
    audit = rows.loc[rows.partition.eq("audit") & usable].copy()
    metrics = forecast_metrics(audit.actual_units, audit[prediction])
    record = {"product_id": product_id, "horizon_days": horizon, "selected_model": model,
              "interval_version": INTERVAL_VERSION, "target_daily_coverage_percent": 100 * TARGET_COVERAGE,
              "calibration_days": len(calibration), "calibration_folds": calibration.forecast_origin.nunique(),
              "calibration_end": calibration.date.max(), "error_radius_units": None,
              "audit_scored_days": metrics["scored_days"], "audit_mae": metrics["mae"],
              "audit_wape_percent": metrics["wape_percent"], "audit_covered_days": 0,
              "audit_coverage_percent": None, "interval_status": "unavailable", "interval_reason": ""}
    audit["range_prediction_units"] = audit[prediction]
    audit["estimated_lower_units"] = np.nan
    audit["estimated_upper_units"] = np.nan
    audit["range_covered"] = pd.array([pd.NA] * len(audit), dtype="boolean")
    if record["calibration_folds"] != 3 or len(calibration) < MIN_CALIBRATION_DAYS:
        record["interval_reason"] = "Prediction range unavailable: need three earlier development folds and at least 20 eligible out-of-sample errors."
        return record, audit
    if not audit.empty and calibration.date.max() > audit.forecast_origin.min():
        raise ValueError("Calibration targets must end before the audit forecasts begin.")
    errors = np.abs(calibration.actual_units.to_numpy(dtype=float) - calibration[prediction].to_numpy(dtype=float))
    if not np.isfinite(errors).all():
        raise ValueError("Calibration errors must be finite.")
    # Conservative finite-sample order statistic, NOT a time-series confidence guarantee.
    rank = min(len(errors), math.ceil((len(errors) + 1) * TARGET_COVERAGE))
    radius = float(np.sort(errors)[rank - 1])
    record.update(error_radius_units=radius, interval_status="estimated", interval_reason="")
    audit["estimated_lower_units"] = (audit[prediction] - radius).clip(lower=0)
    audit["estimated_upper_units"] = (audit[prediction] + radius).clip(lower=0)
    audit["range_covered"] = audit.actual_units.ge(audit.estimated_lower_units - 1e-9) & audit.actual_units.le(audit.estimated_upper_units + 1e-9)
    record["audit_covered_days"] = int(audit.range_covered.sum())
    if len(audit):
        record["audit_coverage_percent"] = 100 * record["audit_covered_days"] / len(audit)
    return record, audit


def add_ranges(forecast, record):
    result = forecast.copy()
    result["predicted_units"] = result.predicted_units.clip(lower=0)
    radius = record["error_radius_units"]
    result["estimated_lower_units"] = (result.predicted_units - radius).clip(lower=0) if radius is not None else np.nan
    result["estimated_upper_units"] = (result.predicted_units + radius).clip(lower=0) if radius is not None else np.nan
    for key in ("interval_version", "target_daily_coverage_percent", "calibration_days", "error_radius_units",
                "audit_scored_days", "audit_coverage_percent", "interval_status", "interval_reason"):
        result[key] = record[key]
    # Keep unavailable numeric metadata numeric when combining product results.
    for key in ("error_radius_units", "audit_coverage_percent"):
        result[key] = pd.to_numeric(result[key]).astype(float)
    result.loc[result.predicted_units.isna(), "interval_status"] = "unavailable"
    result.loc[result.predicted_units.isna(), "interval_reason"] = "Point forecast unavailable; inspect the forecast reason."
    return result
