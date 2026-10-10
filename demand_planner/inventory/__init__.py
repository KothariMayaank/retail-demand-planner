"""Inventory planning interface; periodic review implementation is in planning.py."""
from typing import Protocol
import pandas as pd
from demand_planner.domain import DatasetBundle, PlanningSettings


class InventoryPlanner(Protocol):
    def plan(self, dataset: DatasetBundle, forecasts: pd.DataFrame,
             settings: PlanningSettings) -> tuple[pd.DataFrame, pd.DataFrame]: ...
