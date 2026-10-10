"""Configuration paths are resolved from the project, never the caller's folder."""
from dataclasses import dataclass
from pathlib import Path
import tomllib
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def public_demo_mode():
    return os.environ.get("DEMAND_PLANNER_PUBLIC_DEMO", "false").lower() == "true"


def save_local_runs():
    return not public_demo_mode() and os.environ.get("DEMAND_PLANNER_SAVE_RUNS", "true").lower() == "true"


@dataclass(frozen=True)
class AppConfig:
    forecast_horizon_days: int
    review_period_days: int
    service_level: float
    random_seed: int
    simulation_count: int
    safety_stock_policy: str
    safety_stock_days: float
    safety_stock_units: int
    max_upload_mb: int
    sample_directory: Path
    template_directory: Path


def load_config() -> AppConfig:
    with (PROJECT_ROOT / "config/settings.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    planning, data = raw["planning"], raw["data"]
    planning.setdefault("safety_stock_policy", "demand_days")
    planning.setdefault("safety_stock_days", 2.0)
    planning.setdefault("safety_stock_units", 10)
    if planning["safety_stock_policy"] not in ("demand_days", "fixed_units", "none") or not 0 <= planning["safety_stock_days"] <= 28 or planning["safety_stock_units"] < 0:
        raise ValueError("Use a supported safety-stock policy and nonnegative buffer values.")
    if planning["forecast_horizon_days"] not in (7, 14, 28):
        raise ValueError("Forecast horizon must be 7, 14, or 28 days.")
    if not 1 <= planning["review_period_days"] <= 27:
        raise ValueError("Review period must be between 1 and 27 days.")
    if not 0.80 <= planning["service_level"] <= 0.99:
        raise ValueError("Service level must be between 0.80 and 0.99.")
    if data["max_upload_mb"] <= 0 or planning["simulation_count"] <= 0:
        raise ValueError("Upload limit and simulation count must be positive.")
    return AppConfig(**planning, max_upload_mb=data["max_upload_mb"],
                     sample_directory=PROJECT_ROOT / data["sample_directory"],
                     template_directory=PROJECT_ROOT / data["template_directory"])
