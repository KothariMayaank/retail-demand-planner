"""Reproducible acceptance run, CSV fixtures and independent manual arithmetic."""
from datetime import date
from pathlib import Path
import json
import math
import sys
from io import BytesIO
from zipfile import ZipFile
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demand_planner.config import PROJECT_ROOT, load_config
from demand_planner.data.loading import load_csv_bundle
from demand_planner.data.validation import validate_dataset
from demand_planner.data.schemas import SCHEMAS
from demand_planner.data.exporting import results_zip
from demand_planner.analysis import run_model_analysis
from demand_planner.domain import PlanningSettings
from demand_planner.artifacts import save_analysis
from scripts.reproduce_run import reproduce


def uploaded_files():
    cutoff = pd.Timestamp("2026-09-30")
    products = pd.DataFrame([{"product_id": f"{i:03d}", "product_name": f"Acceptance product {i}",
                             "lead_time_days": 3, "pack_size": 6, "minimum_order_qty": 12} for i in range(1, 11)])
    rows = []
    for i in range(1, 10):
        days = 10 if i == 3 else 20 if i == 4 else 350
        for index, day in enumerate(pd.date_range(end=cutoff, periods=days)):
            if i == 5 and index == 150:
                continue
            units = 0 if i == 2 else 2 + day.dayofweek if i == 1 else int(index % 17 == 0) if i >= 6 else 3
            rows.append({"date": day.strftime("%Y-%m-%d"), "product_id": f"{i:03d}", "units_sold": units, "stockout_flag": "false"})
    sales = pd.DataFrame(rows)
    inventory = pd.DataFrame({"product_id": products.product_id, "snapshot_date": "2026-09-30", "on_hand_units": 5})
    receipts = pd.DataFrame([{"receipt_id": "D1", "product_id": "001", "expected_date": "2026-10-03", "quantity_units": 12}])
    return {name: frame.to_csv(index=False).encode() for name, frame in
            (("products", products), ("sales", sales), ("inventory", inventory), ("receipts", receipts))}


def manual_check(dataset, result, product_id="P006"):
    """Direct arithmetic from rows, independent of forecast/inventory helper functions."""
    sales = dataset.tables["sales"]
    cutoff = sales.date.max()
    recent = sales.loc[(sales.product_id == product_id) & sales.date.between(cutoff - pd.Timedelta(days=27), cutoff)
                       & ~sales.stockout_flag.fillna(False)]
    future = result.future_forecasts.loc[(result.future_forecasts.product_id == product_id) & (result.future_forecasts.horizon_days == 28)]
    assert future.selected_model.eq("baseline").all(), "Manual weekday example must use baseline"
    predictions = np.array([recent.loc[recent.date.dt.dayofweek == day.dayofweek, "units_sold"].astype(float).mean() for day in future.date])
    np.testing.assert_allclose(future.predicted_units, predictions, atol=1e-10)
    row = result.reorder_suggestions.set_index("product_id").loc[product_id]
    lead, period = int(row.lead_time_days), int(row.protection_days)
    lead_demand, period_demand = sum(predictions[:lead]), sum(predictions[:period])
    safety = period_demand / period * 2
    receipts = dataset.tables["receipts"]
    incoming = receipts.loc[(receipts.product_id == product_id) & (receipts.expected_date <= cutoff + pd.Timedelta(days=period)), "quantity_units"].sum()
    stock = float(dataset.tables["inventory"].set_index("product_id").loc[product_id, "on_hand_units"])
    incoming_all = receipts.loc[receipts.product_id == product_id].groupby("expected_date").quantity_units.sum()
    before_arrival = stock
    pre_arrival_lost = 0.
    for day, demand in zip(future.date.iloc[:lead], predictions[:lead]):
        available = before_arrival + float(incoming_all.get(day, 0))
        pre_arrival_lost += max(0., demand - available)
        before_arrival = max(0., available - demand)
    remaining_demand = np.cumsum(predictions[lead:period])
    remaining_receipts = np.cumsum([float(incoming_all.get(day, 0)) for day in future.date.iloc[lead:period]])
    deficits = remaining_demand - remaining_receipts - before_arrival
    gap = max(0., float(max(deficits)), float(deficits[-1] + safety))
    order = math.ceil(max(gap, int(row.minimum_order_qty)) / int(row.pack_size)) * int(row.pack_size) if gap > 1e-9 else 0
    np.testing.assert_allclose([row.lead_time_demand_units, row.protection_demand_units, row.safety_stock_units,
                                row.reorder_point_units, row.target_stock_units, row.raw_order_units],
                               [lead_demand, period_demand, safety, lead_demand+safety, period_demand+safety, gap])
    assert order == row.suggested_order_units
    balance, shortage = stock, None
    for day, demand in zip(future.date, predictions):
        balance += float(incoming_all.get(day, 0))
        if demand > balance + 1e-9 and shortage is None:
            shortage = day
        balance = max(0, balance-demand)
    assert shortage == row.estimated_stockout_date
    candidates = result.candidate_predictions
    dev = candidates.loc[(candidates.product_id == product_id) & (candidates.horizon_days == 28)
                         & candidates.partition.eq("development") & candidates.score_eligible]
    errors = sorted(abs(dev.actual_units.astype(float) - dev.predicted_units))
    rank = min(len(errors), math.ceil((len(errors)+1)*.8))
    radius = errors[rank-1]
    interval = result.interval_evaluation.set_index(["product_id", "horizon_days"]).loc[(product_id,28)]
    assert math.isclose(radius, interval.error_radius_units)
    return {"product_id": product_id, "next_day": str(future.date.iloc[0].date()),
            "weekday_observations": recent.loc[recent.date.dt.dayofweek == future.date.iloc[0].dayofweek, "units_sold"].astype(int).tolist(),
            "next_day_forecast": predictions[0], "lead_days": lead, "protection_days": period,
            "lead_demand": lead_demand, "period_demand": period_demand, "buffer": safety,
            "reorder_point": lead_demand+safety, "target": period_demand+safety, "on_hand": stock,
            "incoming_in_period": int(incoming), "pre_arrival_lost_units": pre_arrival_lost,
            "raw_order": gap, "pack": int(row.pack_size),
            "minimum_order": int(row.minimum_order_qty), "rounded_order": int(order),
            "estimated_shortage_date": str(shortage.date()), "calibration_days": len(errors), "rank": rank, "range_radius": radius}


def verify():
    config = load_config()
    directory = PROJECT_ROOT / "outputs/verification"
    directory.mkdir(parents=True, exist_ok=True)
    files = uploaded_files()
    upload_dir = directory / "upload"
    upload_dir.mkdir(exist_ok=True)
    for name, content in files.items():
        (upload_dir / f"{name}.csv").write_bytes(content)
    (upload_dir / "malformed_sales.csv").write_bytes(b"date,product_id,units_sold\n2026-09-30,001,-5\n")
    report = validate_dataset(load_csv_bundle(files, "Acceptance upload"), as_of=date(2026,10,10))
    assert not report.has_errors
    result = run_model_analysis(report.dataset, PlanningSettings())
    assert len(result.future_forecasts) == 490
    for product_id in ("003", "005", "010"):
        assert result.future_forecasts.loc[result.future_forecasts.product_id == product_id].predicted_units.isna().all()
        assert result.reorder_suggestions.set_index("product_id").loc[product_id, "status"] == "unavailable"
    assert result.future_forecasts.loc[result.future_forecasts.product_id == "002"].predicted_units.eq(0).all()
    assert result.reorder_suggestions.set_index("product_id").loc["002", "suggested_order_units"] == 0
    assert result.future_forecasts.loc[result.future_forecasts.product_id == "004"].method.eq("recent_mean_28d_fallback").all()
    with ZipFile(BytesIO(results_zip(result))) as archive:
        exported = pd.read_csv(archive.open("reorder_suggestions.csv"), dtype={"product_id": str})
        assert exported.product_id.tolist() == result.reorder_suggestions.product_id.tolist()
        np.testing.assert_allclose(exported.suggested_order_units, result.reorder_suggestions.suggested_order_units.astype(float), equal_nan=True)
    bad = dict(files, sales=(upload_dir / "malformed_sales.csv").read_bytes())
    assert validate_dataset(load_csv_bundle(bad, "Malformed upload"), as_of=date(2026,10,10)).has_errors
    confirmed = validate_dataset(report.raw, as_of=date(2026,10,10), zero_fill_products=("005",))
    assert confirmed.summary.set_index("product_id").loc["005", "missing_days"] == 0
    upload_run = save_analysis(report.dataset, result)
    sample_report = validate_dataset(load_csv_bundle({name: (config.sample_directory/f"{name}.csv").read_bytes() for name in SCHEMAS}, "Synthetic sample"), as_of=date(2026,10,10))
    assert not sample_report.has_errors
    sample = run_model_analysis(sample_report.dataset, PlanningSettings())
    assert len(sample.future_forecasts) == 980 and len(sample.inventory_projection) == 560
    manual = manual_check(sample_report.dataset, sample)
    sample_run = save_analysis(sample_report.dataset, sample)
    reproduce(sample_run, retrain=True)
    comparison = sample.model_comparison
    audit_worse = comparison.loc[comparison.selected_model.eq("ml") & comparison.audit_ml_mae.gt(comparison.audit_baseline_mae)]
    summary = {"sample_run": str(sample_run), "upload_run": str(upload_run), "manual_check": manual,
               "sample_model_selections": comparison.selected_model.value_counts().to_dict(),
               "selected_ml_worse_on_audit": len(audit_worse),
               "ranges_below_80_percent_audit_coverage": int(sample.interval_evaluation.audit_coverage_percent.lt(80).sum()),
               "upload_unavailable_products": ["003 (10 days)", "005 (unresolved gap)", "010 (no sales history)"],
               "sample_forecast_rows": len(sample.future_forecasts), "sample_projection_rows": len(sample.inventory_projection)}
    (directory / "acceptance_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("PASS: sample and upload analysis, independent arithmetic, ZIP exports, malformed rejection, gaps, zero/limited sales, and saved-run retraining.")
    return summary


if __name__ == "__main__":
    verify()
