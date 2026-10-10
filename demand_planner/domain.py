"""Shared input and result contracts for the implementation phases."""
from dataclasses import dataclass, field
import pandas as pd


@dataclass(frozen=True)
class PlanningSettings:
    horizon_days: int = 14
    review_period_days: int = 7
    service_level: float = 0.95
    random_seed: int = 42
    simulation_count: int = 1000
    safety_stock_policy: str = "demand_days"
    safety_stock_days: float = 2.0
    safety_stock_units: int = 10


@dataclass
class DatasetBundle:
    tables: dict[str, pd.DataFrame]
    source: str
    fingerprint: str


@dataclass
class AnalysisResults:
    """Only the future analysis pipeline may populate these result tables."""
    input_fingerprint: str
    settings: PlanningSettings
    daily_forecasts: pd.DataFrame = field(default_factory=pd.DataFrame)
    inventory_projection: pd.DataFrame = field(default_factory=pd.DataFrame)
    reorder_suggestions: pd.DataFrame = field(default_factory=pd.DataFrame)
    evaluation: pd.DataFrame = field(default_factory=pd.DataFrame)
    backtest_predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    backtest_folds: pd.DataFrame = field(default_factory=pd.DataFrame)
    model_comparison: pd.DataFrame = field(default_factory=pd.DataFrame)
    candidate_predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    trained_models: dict = field(default_factory=dict)
    artifact_directory: str | None = None
    future_forecasts: pd.DataFrame = field(default_factory=pd.DataFrame)
    interval_evaluation: pd.DataFrame = field(default_factory=pd.DataFrame)
    interval_audit_predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    data_source: str = ""
