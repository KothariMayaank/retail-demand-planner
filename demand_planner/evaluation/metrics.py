"""Evaluation metrics for already aligned, eligible observed/predicted pairs."""
import numpy as np


def forecast_metrics(actual, predicted) -> dict:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.ndim != 1 or predicted.ndim != 1 or actual.shape != predicted.shape:
        raise ValueError("Actual and predicted values must be aligned one-dimensional arrays.")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Scored values must be finite; filter unavailable observations explicitly.")
    if (actual < 0).any() or (predicted < 0).any():
        raise ValueError("Scored quantities cannot be negative.")
    if not len(actual):
        return {"scored_days": 0, "actual_units": None, "absolute_error_units": None,
                "mae": None, "wape_percent": None, "rmse": None, "bias_units": None}
    error = float(np.abs(predicted - actual).sum())
    denominator = float(actual.sum())
    return {"scored_days": len(actual), "actual_units": denominator,
            "absolute_error_units": error, "mae": error / len(actual),
            "wape_percent": 100 * error / denominator if denominator > 0 else None,
            "rmse": float(np.sqrt(np.mean((predicted - actual) ** 2))),
            "bias_units": float(np.mean(predicted - actual))}
