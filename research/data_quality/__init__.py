# -*- coding: utf-8 -*-
"""Data validity + tradability protocol (extends research_quality semantics)."""

from research.data_quality.calendar import (
    active_front_contract_on_date,
    annotate_bars_with_calendar,
    delivery_flags_for_date,
    estimate_last_trade_day,
)
from research.data_quality.masks import (
    DATA_STATUS,
    classify_bar,
    data_valid_mask,
    quality_score,
    tradability_mask,
)
from research.data_quality.dual_source_diff import (
    build_report as build_dual_source_diff_report,
    diff_bars,
    diff_seat_product,
    write_report as write_dual_source_diff_report,
)
from research.data_quality.schema import bar_quality_record, config_version_stamp

__all__ = [
    "DATA_STATUS",
    "active_front_contract_on_date",
    "annotate_bars_with_calendar",
    "bar_quality_record",
    "build_dual_source_diff_report",
    "classify_bar",
    "config_version_stamp",
    "data_valid_mask",
    "delivery_flags_for_date",
    "diff_bars",
    "diff_seat_product",
    "estimate_last_trade_day",
    "quality_score",
    "tradability_mask",
    "write_dual_source_diff_report",
]
