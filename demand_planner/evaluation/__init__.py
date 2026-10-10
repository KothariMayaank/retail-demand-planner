"""Historical evaluation interface; fixed-baseline rolling evaluation is implemented."""
from typing import Protocol
import pandas as pd
from demand_planner.domain import PlanningSettings


class HistoricalEvaluator(Protocol):
    def evaluate(self, sales: pd.DataFrame, settings: PlanningSettings) -> pd.DataFrame: ...
