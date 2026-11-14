# -*- coding: utf-8 -*-
"""Statistical validation: PSR, DSR, PBO, walk-forward (research only)."""

from lab.validation.dsr import deflated_sharpe_ratio
from lab.validation.effective_trials import effective_trials
from lab.validation.pbo import pbo_sensitivity, probability_of_backtest_overfitting
from lab.validation.psr import probabilistic_sharpe_ratio
from lab.validation.purge import average_rank, time_split_with_purge
from lab.validation.report import validation_bundle_from_day_pnls, validation_bundle_from_returns
from lab.validation.walk_forward import walk_forward_segments

__all__ = [
    "average_rank",
    "deflated_sharpe_ratio",
    "effective_trials",
    "pbo_sensitivity",
    "probability_of_backtest_overfitting",
    "probabilistic_sharpe_ratio",
    "time_split_with_purge",
    "validation_bundle_from_day_pnls",
    "validation_bundle_from_returns",
    "walk_forward_segments",
]
