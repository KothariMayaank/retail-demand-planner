"""Audit-only, horizon-specific scorecards for reproducible project evidence."""
import numpy as np
import pandas as pd
from demand_planner.evaluation.metrics import forecast_metrics


def audit_scorecard(candidates, comparisons):
    """Compare baseline with the development-selected policy on identical days.

    Pool errors before dividing; never average SKU WAPEs. Each horizon has its
    own denominator because audit dates overlap across horizons. Selection is
    read from the frozen development decisions, never recomputed from audit.
    """
    if candidates.empty:
        return pd.DataFrame()
    rows = candidates.loc[candidates.partition.eq("audit")].merge(
        comparisons[["product_id", "horizon_days", "selected_model"]],
        on=["product_id", "horizon_days"], validate="many_to_one")
    choose_ml = rows.selected_model.eq("ml")
    rows["selected_prediction"] = rows.predicted_units.where(~choose_ml, rows.predicted_units_ml)
    selected_eligible = rows.score_eligible.where(~choose_ml, rows.score_eligible_ml).fillna(False).astype(bool)
    rows["comparison_eligible"] = rows.score_eligible.fillna(False).astype(bool) & selected_eligible
    records = []
    for horizon, attempted in rows.groupby("horizon_days", sort=True):
        paired = attempted.loc[attempted.comparison_eligible]
        baseline = forecast_metrics(paired.actual_units, paired.predicted_units)
        selected = forecast_metrics(paired.actual_units, paired.selected_prediction)
        wins, losses, ties = 0, 0, 0
        for _, product in paired.groupby("product_id"):
            before = np.abs(product.predicted_units.astype(float) - product.actual_units.astype(float)).mean()
            after = np.abs(product.selected_prediction.astype(float) - product.actual_units.astype(float)).mean()
            if np.isclose(before, after, rtol=1e-9, atol=1e-9):
                ties += 1
            elif after < before:
                wins += 1
            else:
                losses += 1
        record = {"horizon_days": int(horizon), "audit_target_rows": len(attempted),
                  "scored_days": len(paired), "excluded_days": len(attempted) - len(paired),
                  "evaluated_products": paired.product_id.nunique(),
                  "products_improved": wins, "products_worse": losses, "products_tied": ties,
                  "audit_start": attempted.date.min(), "audit_end": attempted.date.max(),
                  "mae_improvement_percent": 100 * (1 - selected["mae"] / baseline["mae"])
                  if baseline["mae"] else None}
        for name in ("mae", "wape_percent", "rmse", "bias_units"):
            record[f"baseline_{name}"] = baseline[name]
            record[f"selected_{name}"] = selected[name]
        records.append(record)
    return pd.DataFrame(records)
