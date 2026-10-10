"""Recent matching-weekday baseline, with explicit fallback and failure statuses."""
import pandas as pd
from demand_planner.data.preprocessing import prepare_training_series

HORIZONS = (7, 14, 28)
LOOKBACK_DAYS = 28
MIN_USABLE_DAYS = 14
MIN_WEEKDAY_MATCHES = 2
MODEL_VERSION = "weekday-baseline-v1"


def forecast_baseline(sales: pd.DataFrame, product_id: str, origin, horizon: int) -> pd.DataFrame:
    """Forecast origin+1 through origin+horizon; never read future rows for fitting.

    Use the latest 28 calendar days, excluding known stockouts. With at least
    28 calendar days of history and two matching observations, take that weekday
    mean. Otherwise use the recent non-stockout mean. Fewer than 14 usable
    training observations, training gaps, or no recent usable observations yield
    unavailable predictions rather than zero. Unknown availability remains usable.
    """
    if horizon not in HORIZONS:
        raise ValueError("Forecast horizon must be 7, 14 or 28 days.")
    origin = pd.Timestamp(origin).normalize()
    targets = pd.date_range(origin + pd.Timedelta(days=1), periods=horizon, freq="D")
    result = pd.DataFrame({"product_id": product_id, "forecast_origin": origin, "date": targets,
                           "horizon_days": horizon, "predicted_units": float("nan"),
                           "method": "unavailable", "matching_days": 0,
                           "training_observations": 0, "recent_observations": 0,
                           "status": "unavailable", "reason": "", "model_version": MODEL_VERSION})
    try:
        training = prepare_training_series(sales, product_id, origin)
    except ValueError as exc:
        result["reason"] = str(exc)
        return result
    usable = training.loc[training.score_eligible]
    result["training_observations"] = len(usable)
    if len(usable) < MIN_USABLE_DAYS:
        result["reason"] = "Fewer than 14 non-stockout training observations."
        return result
    recent = usable.loc[usable.date >= origin - pd.Timedelta(days=LOOKBACK_DAYS - 1)]
    result["recent_observations"] = len(recent)
    if recent.empty:
        result["reason"] = "No usable sales in the latest 28 calendar days."
        return result
    fallback = float(recent.observed_units.mean())
    enough_calendar_history = (origin - training.date.min()).days + 1 >= LOOKBACK_DAYS
    for index, target in enumerate(targets):
        matches = recent.loc[recent.date.dt.dayofweek == target.dayofweek]
        result.at[index, "matching_days"] = len(matches)
        if enough_calendar_history and len(matches) >= MIN_WEEKDAY_MATCHES:
            result.at[index, "predicted_units"] = float(matches.observed_units.mean())
            result.at[index, "method"] = "weekday_mean_28d"
            result.at[index, "status"] = "ready"
        else:
            result.at[index, "predicted_units"] = fallback
            result.at[index, "method"] = "recent_mean_28d_fallback"
            result.at[index, "status"] = "fallback"
            result.at[index, "reason"] = ("Fewer than 28 calendar days of history." if not enough_calendar_history
                                           else "Fewer than two usable matching weekdays in the recent window.")
    return result
