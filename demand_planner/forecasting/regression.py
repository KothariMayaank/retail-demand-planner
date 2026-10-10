"""Deterministic per-product standardized ridge regression, with recursive forecasts."""
import numpy as np
import pandas as pd
from demand_planner.data.preprocessing import prepare_training_series
from demand_planner.forecasting.baseline import forecast_baseline, HORIZONS

MODEL_VERSION = "ridge-recursive-v1"
ALPHA = 10.0
MIN_TRAINING_ROWS = 90
LAGS = (1, 7, 14, 28)


def training_features(sales, product_id, origin):
    training = prepare_training_series(sales, product_id, origin)
    observed = training.observed_units.where(training.score_eligible)
    # Stockout lag substitutions use ONLY earlier usable observations. No backfill.
    signal = observed.fillna(observed.expanding().mean().shift(1).fillna(0.0))
    features = calendar_features(training.date, training.date.min())
    for lag in LAGS:
        features[f"lag_{lag}"] = signal.shift(lag).to_numpy()
    past = signal.shift(1)
    for window in (7, 28):
        features[f"mean_{window}"] = past.rolling(window).mean().to_numpy()
    features["std_28"] = past.rolling(28).std(ddof=0).to_numpy()
    features["zero_rate_28"] = past.eq(0).astype(float).where(past.notna()).rolling(28).mean().to_numpy()
    eligible = features.notna().all(axis=1) & training.score_eligible
    return training, signal, features, eligible


def calendar_features(dates, first_date):
    dates = pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    phase = 2 * np.pi * (dates.dt.dayofyear - 1) / 365.25
    features = pd.DataFrame({"annual_sin": np.sin(phase), "annual_cos": np.cos(phase),
                             "trend_years": (dates - pd.Timestamp(first_date)).dt.days / 365.25})
    for weekday in range(7):
        features[f"weekday_{weekday}"] = (dates.dt.dayofweek == weekday).astype(float)
    return features


def fit_regression(sales, product_id, origin):
    training, signal, features, eligible = training_features(sales, product_id, origin)
    if int(eligible.sum()) < MIN_TRAINING_ROWS:
        raise ValueError("ML needs at least 90 usable training targets after the 28-day lag warm-up.")
    x = features.loc[eligible].to_numpy(dtype=float)
    y = training.loc[eligible, "observed_units"].to_numpy(dtype=float)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    z = (x - mean) / scale
    intercept = float(y.mean())
    coefficients = np.linalg.solve(z.T @ z + ALPHA * np.eye(z.shape[1]), z.T @ (y - intercept))
    return {"model_version": MODEL_VERSION, "product_id": product_id, "origin": pd.Timestamp(origin).isoformat(),
            "first_date": training.date.min().isoformat(), "training_rows": int(eligible.sum()),
            "features": list(features.columns), "alpha": ALPHA, "mean": mean.tolist(), "scale": scale.tolist(),
            "coefficients": coefficients.tolist(), "intercept": intercept, "signal_tail": signal.iloc[-28:].tolist(),
            "exogenous_policy": "No price/promotion features: future plans are not supplied.",
            "stockout_policy": "Exclude targets; fill lag signal with expanding mean of prior usable observations."}


def predict_artifact(model, horizon):
    if horizon not in HORIZONS or model["model_version"] != MODEL_VERSION:
        raise ValueError("Unsupported horizon or trained artifact version.")
    origin = pd.Timestamp(model["origin"])
    dates = pd.date_range(origin + pd.Timedelta(days=1), periods=horizon)
    signal = list(model["signal_tail"])
    predictions = []
    for day in dates:
        phase = 2 * np.pi * (day.dayofyear - 1) / 365.25
        row = {"annual_sin": np.sin(phase), "annual_cos": np.cos(phase),
               "trend_years": (day - pd.Timestamp(model["first_date"])).days / 365.25}
        row.update({f"weekday_{weekday}": float(day.dayofweek == weekday) for weekday in range(7)})
        for lag in LAGS:
            row[f"lag_{lag}"] = signal[-lag]
        for window in (7, 28):
            row[f"mean_{window}"] = np.mean(signal[-window:])
        row["std_28"] = np.std(signal[-28:])
        row["zero_rate_28"] = np.mean(np.asarray(signal[-28:]) == 0)
        x = np.asarray([row[name] for name in model["features"]], dtype=float)
        prediction = max(0.0, float(((x - model["mean"]) / model["scale"]) @ model["coefficients"] + model["intercept"]))
        if not np.isfinite(prediction):
            raise ValueError("ML produced a nonfinite recursive prediction.")
        predictions.append(prediction)
        signal.append(prediction)  # Next day never reads a future actual value.
    return pd.DataFrame({"product_id": model["product_id"], "forecast_origin": pd.Series([origin] * horizon, dtype="datetime64[ns]"), "date": dates,
                         "horizon_days": horizon, "predicted_units": predictions, "method": "ridge_recursive",
                         "matching_days": 0, "training_observations": model["training_rows"], "recent_observations": 28,
                         "status": "ready", "reason": "", "model_version": MODEL_VERSION})


def forecast_regression(sales, product_id, origin, horizon):
    try:
        return predict_artifact(fit_regression(sales, product_id, origin), horizon)
    except ValueError as exc:
        result = forecast_baseline(sales, product_id, origin, horizon)
        result["predicted_units"] = np.nan
        result["method"] = "unavailable"
        result["status"] = "unavailable"
        result["reason"] = str(exc)
        result["model_version"] = MODEL_VERSION
        return result
