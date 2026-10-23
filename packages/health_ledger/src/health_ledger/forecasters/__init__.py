"""The forecasters that compete on one scoreboard, in registry order.

Registry keys are the names stored in `forecasts` and `scores`. A forecaster gets the
connection, the day and the feature snapshot; it must not read the journal for that day
or later, and it abstains (with a reason) rather than inventing a bet it cannot make.
"""
from __future__ import annotations

from health_ledger.forecasters import baselines, statistical
from health_ledger.forecasters.base import TARGETS, Forecast, Forecaster
from health_ledger.forecasters.baselines import outcome_history

FORECASTERS: dict[str, Forecaster] = {
    "climatology": baselines.climatology,
    "persistence": baselines.persistence,
    "seasonal_naive": baselines.seasonal_naive,
    "statistical": statistical.forecast,
}

__all__ = ["FORECASTERS", "TARGETS", "Forecast", "Forecaster", "outcome_history"]
