"""Forecasting interface; the matching-weekday baseline is in baseline.py."""
from typing import Protocol
import pandas as pd
from demand_planner.domain import PlanningSettings


class Forecaster(Protocol):
    def forecast(self, sales: pd.DataFrame, settings: PlanningSettings) -> pd.DataFrame: ...
