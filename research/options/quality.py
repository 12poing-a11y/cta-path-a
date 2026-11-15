# -*- coding: utf-8 -*-
"""Option chain quality gate for research snapshots."""
from __future__ import annotations

from typing import Any


def assess_chain_quality(
    legs: list[dict[str, Any]],
    *,
    asof: str,
    underlying_settle: float | None,
    futures_date: str | None = None,
    min_legs: int = 8,
    min_settle_coverage: float = 0.5,
) -> dict[str, Any]:
    """Return status OK | WARN | REJECT with reasons.

    No Bid/Ask never alone REJECT — caps strategy state at WARN later.
    """
    reasons: list[str] = []
    warn: list[str] = []
    n = len(legs)
    with_settle = sum(1 for lg in legs if lg.get("settle") is not None and float(lg["settle"]) >= 0)
    with_bid_ask = sum(
        1
        for lg in legs
        if lg.get("bid") is not None
        and lg.get("ask") is not None
        and float(lg["bid"]) > 0
        and float(lg["ask"]) > 0
    )
    settle_cov = with_settle / n if n else 0.0

    if underlying_settle is None or float(underlying_settle) <= 0:
        reasons.append("underlying_settle_missing")
    if futures_date and futures_date != asof:
        reasons.append(f"futures_date_mismatch:{futures_date}!={asof}")
    if n < min_legs:
        reasons.append(f"legs_lt_{min_legs}:{n}")
    if n and settle_cov < min_settle_coverage:
        reasons.append(f"settle_coverage_lt_{min_settle_coverage:.0%}:{settle_cov:.1%}")

    if with_bid_ask == 0:
        warn.append("no_bid_ask")
    if n and with_bid_ask / n < 0.2:
        warn.append("thin_bid_ask")

    if reasons:
        status = "REJECT"
    elif warn:
        status = "WARN"
    else:
        status = "OK"

    return {
        "status": status,
        "reasons": reasons,
        "warnings": warn,
        "n_legs": n,
        "n_with_settle": with_settle,
        "n_with_bid_ask": with_bid_ask,
        "settle_coverage": round(settle_cov, 4),
        "pricing_note": (
            "no_bid_ask; use settle minus slip_ticks for credit entry research"
            if with_bid_ask == 0
            else "bid_ask_partial_or_full"
        ),
    }
