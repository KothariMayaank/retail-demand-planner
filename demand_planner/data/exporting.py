"""CSV reports safe to open in spreadsheet software."""
import pandas as pd
from dataclasses import asdict
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED
from demand_planner.evaluation.reporting import audit_scorecard


def csv_bytes(frame: pd.DataFrame) -> bytes:
    result = frame.copy()
    for column in result:
        if pd.api.types.is_object_dtype(result[column]) or pd.api.types.is_string_dtype(result[column]):
            result[column] = result[column].map(
                lambda value: "'" + value if isinstance(value, str) and
                value.lstrip().startswith(("=", "+", "-", "@")) else value)
    return result.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8")


def results_zip(result):
    """Portable reports only; excludes uploaded raw data and executable models."""
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name in ("daily_forecasts", "future_forecasts", "inventory_projection", "reorder_suggestions",
                     "evaluation", "backtest_predictions", "backtest_folds", "model_comparison", "candidate_predictions",
                     "interval_evaluation", "interval_audit_predictions"):
            frame = getattr(result, name)
            if not frame.empty:
                archive.writestr(f"{name}.csv", csv_bytes(frame))
        if not result.candidate_predictions.empty and not result.model_comparison.empty:
            scorecard = audit_scorecard(result.candidate_predictions, result.model_comparison)
            scorecard["data_source"] = result.data_source
            scorecard["synthetic_data"] = result.data_source == "Synthetic sample"
            archive.writestr("audit_scorecard.csv", csv_bytes(scorecard))
        archive.writestr("settings.json", json.dumps(asdict(result.settings), indent=2))
        archive.writestr("metadata.json", json.dumps({"data_source": result.data_source,
                         "synthetic_data": result.data_source == "Synthetic sample",
                         "input_fingerprint": result.input_fingerprint}, indent=2))
        archive.writestr("README.txt", "Retail Demand Planner results\n"
                         f"Data source: {result.data_source or 'Not recorded'}\n"
                         "Forecasts and projections retain fractional expected units. Orders round upward to packs.\n"
                         "Inventory uses the selected 28-day forecast; listed receipts arrive at start of expected date.\n"
                         "Suggested orders are excluded from projections until recorded as receipts.\n"
                         "Stockout dates and prediction ranges are estimates, not guarantees.\n"
                         "MAE: mean absolute daily error (units). WAPE: absolute error / actual sales, percent; undefined for zero actual total.\n"
                         "Known stockout and missing actual targets are excluded from evaluation.\n"
                         "Audit scorecard compares baseline with frozen development-selected models on identical eligible dates per horizon.\n"
                         "RMSE penalizes large errors; bias is mean(prediction - actual), positive for overforecasting. Do not pool overlapping horizons.\n"
                         f"Input fingerprint: {result.input_fingerprint}\n")
    return buffer.getvalue()
