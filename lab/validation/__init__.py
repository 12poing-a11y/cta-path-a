# -*- coding: utf-8 -*-
"""Statistical validation: PSR, DSR, PBO, walk-forward (research only)."""

from lab.validation.dsr import deflated_sharpe_ratio
from lab.validation.effective_trials import effective_trials
from lab.validation.pbo import probability_of_backtest_overfitting
from lab.validation.psr import probabilistic_sharpe_ratio
from lab.validation.report import validation_bundle_from_day_pnls, validation_bundle_from_returns
from lab.validation.walk_forward import walk_forward_segments

__all__ = [
    "deflated_sharpe_ratio",
    "effective_trials",
    "probability_of_backtest_overfitting",
    "probabilistic_sharpe_ratio",
    "validation_bundle_from_day_pnls",
    "validation_bundle_from_returns",
    "walk_forward_segments",
]
