"""Persist trusted local JSON models, normalized inputs and reproducibility metadata."""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
from uuid import uuid4
from demand_planner.config import PROJECT_ROOT
from demand_planner.forecasting.regression import MODEL_VERSION, ALPHA, MIN_TRAINING_ROWS
from demand_planner.evaluation.selection import SELECTION_VERSION
from demand_planner.inventory.planning import POLICY_VERSION
from demand_planner.forecasting.uncertainty import INTERVAL_VERSION, TARGET_COVERAGE, MIN_CALIBRATION_DAYS


def save_analysis(dataset, result, output_root=None):
    root = Path(output_root) if output_root is not None else PROJECT_ROOT / "outputs/runs"
    run = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run.mkdir(parents=True)
    files = {}

    def write(name, content):
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        files[name] = sha256(content).hexdigest()

    for name, frame in dataset.tables.items():
        # Exact normalized values, including zero-fill provenance; never formula-escape model inputs.
        write(f"inputs/{name}.csv", frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8"))
    for name, frame in (("daily_forecasts", result.daily_forecasts), ("baseline_evaluation", result.evaluation),
                        ("baseline_folds", result.backtest_folds), ("baseline_predictions", result.backtest_predictions),
                        ("model_comparison", result.model_comparison), ("candidate_predictions", result.candidate_predictions),
                        ("future_forecasts", result.future_forecasts), ("interval_evaluation", result.interval_evaluation),
                        ("interval_audit_predictions", result.interval_audit_predictions),
                        ("inventory_projection", result.inventory_projection), ("reorder_suggestions", result.reorder_suggestions)):
        write(f"{name}.csv", frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8"))
    write("trained_models.json", json.dumps(result.trained_models, indent=2, allow_nan=False).encode("utf-8"))
    sources = {str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
               for path in sorted((PROJECT_ROOT / "demand_planner").rglob("*.py"))}
    for name in sources:
        write(f"code/{name}", (PROJECT_ROOT / name).read_bytes())
    for name in ("requirements.txt", "requirements-lock.txt", "config/settings.toml"):
        write(f"code/{name}", (PROJECT_ROOT / name).read_bytes())
    manifest = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "input_fingerprint": dataset.fingerprint, "source": dataset.source,
                "forecast_origin": dataset.tables["sales"].date.max().isoformat(), "settings": asdict(result.settings),
                "model_version": MODEL_VERSION, "alpha": ALPHA, "minimum_training_rows": MIN_TRAINING_ROWS,
                "selection_version": SELECTION_VERSION, "backtest": {"max_folds": 6, "minimum_calendar_training_days": 56,
                "horizons": [7, 14, 28], "development_folds": "oldest three of six", "audit_folds": "newest three of six"},
                "python": platform.python_version(), "packages": {name: version(name) for name in ("numpy", "pandas", "streamlit")},
                "prediction_ranges": {"version": INTERVAL_VERSION, "target_daily_coverage": TARGET_COVERAGE,
                    "minimum_calibration_days": MIN_CALIBRATION_DAYS, "calibration": "development only; pooled lead times within horizon",
                    "coverage_evaluation": "reserved audit; known stockouts excluded", "rounding": "none; display only, 2 decimals"},
                "inventory_policy": {"version": POLICY_VERSION, "forecast_horizon": 28,
                    "delivery_timing": "listed receipts at start of expected date; new order after lead_time full sales days",
                    "missing_receipts": "assume none", "suggested_orders_in_projection": False,
                    "rounding": "order only: upward to pack size, respecting minimum positive order"},
                "files_sha256": files, "source_sha256": sources,
                "exogenous_policy": "Historical price/promotions and synthetic reference truth are excluded.",
                "reproduction": "Use normalized inputs, saved settings and matching code/dependencies; JSON model reproduces forecasts without retraining."}
    write("manifest.json", json.dumps(manifest, indent=2, allow_nan=False).encode("utf-8"))
    result.artifact_directory = str(run)
    return run
