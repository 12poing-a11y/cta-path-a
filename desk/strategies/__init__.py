# -*- coding: utf-8 -*-
from desk.strategies.base import Availability, StrategySpec
from desk.strategies.registry import all_strategies, get_strategy, scan_extra

__all__ = [
    "Availability",
    "StrategySpec",
    "all_strategies",
    "get_strategy",
    "scan_extra",
]
