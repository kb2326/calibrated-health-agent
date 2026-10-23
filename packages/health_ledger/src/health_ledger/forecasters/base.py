"""What a forecaster is: a function from (conn, day, snapshot) to one Forecast."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from health_ledger.dist import Dist

TARGETS = ("mood", "energy", "soreness")


@dataclass(frozen=True)
class Forecast:
    """Per target, exactly one of a distribution (`probs`) or an abstain reason.

    `inputs` carries what a forecaster read beyond the shared snapshot (forecaster 7's notes)
    and its model usage; the lock records both.
    """

    probs: dict[str, Dist] = field(default_factory=dict)
    abstain: dict[str, str] = field(default_factory=dict)
    inputs: dict | None = None

    @classmethod
    def abstain_all(cls, reason: str) -> Forecast:
        return cls(abstain=dict.fromkeys(TARGETS, reason))


Forecaster = Callable[[sqlite3.Connection, date, dict], Forecast]
