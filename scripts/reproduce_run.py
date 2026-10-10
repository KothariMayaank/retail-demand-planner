"""Verify saved forecasts, or rerun the complete comparison from normalized inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demand_planner.domain import DatasetBundle, PlanningSettings
from demand_planner.forecasting.baseline import forecast_baseline
from demand_planner.forecasting.regression import predict_artifact
from demand_planner.analysis import run_model_analysis


def read_saved_csv(path, **kwargs):
    """Only empty cells are missing; identifiers such as NA/NULL are literal text."""
    return pd.read_csv(path, keep_default_na=False, na_values=[""], **kwargs)


def reproduce(run, retrain=False):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files_sha256"].items():
        if hashlib.sha256((run / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Saved file checksum differs: {name}")
    tables = {}
    for path in (run / "inputs").glob("*.csv"):
        frame = read_saved_csv(path, dtype={"product_id": str, "receipt_id": str, "stockout_flag": "boolean"})
        for name in ("date", "snapshot_date", "expected_date"):
            if name in frame:
                frame[name] = pd.to_datetime(frame[name])
        tables[path.stem] = frame
    settings = PlanningSettings(**manifest["settings"])
    models = json.loads((run / "trained_models.json").read_text(encoding="utf-8"))
    expected = read_saved_csv(run / "daily_forecasts.csv", dtype={"product_id": str}, parse_dates=["date"])
    for product_id, group in expected.groupby("product_id", sort=False):
        chosen = group.selected_model.iloc[0]
        regenerated = (predict_artifact(models[product_id]["model"], settings.horizon_days) if chosen == "ml" else
                       forecast_baseline(tables["sales"], product_id, manifest["forecast_origin"], settings.horizon_days))
        if not group.date.reset_index(drop=True).equals(regenerated.date):
            raise ValueError(f"Target dates differ for {product_id}")
        np.testing.assert_allclose(group.predicted_units, regenerated.predicted_units, rtol=1e-10, atol=1e-10, equal_nan=True)
    if retrain:
        for name, expected_hash in manifest["source_sha256"].items():
            current = Path(__file__).resolve().parents[1] / name
            if hashlib.sha256(current.read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f"Code differs from saved run: {name}. Use its code snapshot to reproduce training.")
        result = run_model_analysis(DatasetBundle(tables, manifest["source"], manifest["input_fingerprint"]), settings)
        saved = read_saved_csv(run / "model_comparison.csv", dtype={"product_id": str})
        for column in ("selected_model", "product_id", "horizon_days"):
            if result.model_comparison[column].tolist() != saved[column].tolist():
                raise ValueError(f"Model comparison differs: {column}")
        for column in ("development_baseline_mae", "development_ml_mae", "audit_baseline_mae", "audit_ml_mae"):
            np.testing.assert_allclose(result.model_comparison[column].astype(float), saved[column], rtol=1e-10, atol=1e-10, equal_nan=True)
        if (run / "future_forecasts.csv").exists() and (run / "future_forecasts.csv").stat().st_size > 1:
            saved_future = read_saved_csv(run / "future_forecasts.csv", dtype={"product_id": str})
            for column in ("predicted_units", "estimated_lower_units", "estimated_upper_units"):
                np.testing.assert_allclose(result.future_forecasts[column], saved_future[column], rtol=1e-10, atol=1e-10, equal_nan=True)
            saved_intervals = read_saved_csv(run / "interval_evaluation.csv", dtype={"product_id": str})
            for column in ("error_radius_units", "audit_coverage_percent", "audit_scored_days", "audit_covered_days"):
                np.testing.assert_allclose(result.interval_evaluation[column].astype(float), saved_intervals[column], rtol=1e-10, atol=1e-10, equal_nan=True)
        for name in ("inventory_projection", "reorder_suggestions"):
            path = run / f"{name}.csv"
            if path.exists() and path.stat().st_size > 2:
                frame = getattr(result, name)
                saved_frame = read_saved_csv(path, dtype={"product_id": str})
                # Compare the entire result including dates, unavailable values and explanations.
                regenerated_frame = read_saved_csv(__import__("io").StringIO(frame.to_csv(index=False, date_format="%Y-%m-%d")), dtype={"product_id": str})
                pd.testing.assert_frame_equal(regenerated_frame, saved_frame, check_exact=False, rtol=1e-10, atol=1e-10)
    return len(expected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--retrain", action="store_true")
    arguments = parser.parse_args()
    print(f"PASS: reproduced {reproduce(arguments.run_directory, arguments.retrain)} forecast rows and verified saved checksums.")
