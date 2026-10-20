# -*- coding: utf-8 -*-
"""Path-A portfolio rules: momentum floor, bucket dedupe, N-cap, notional + ATR risk caps."""
from __future__ import annotations

import math
from typing import Any


def compound_equity(live_equity: float, base_equity: float = 200_000, compound: bool = True) -> float:
    """Size on live equity when compounding; otherwise on base."""
    base = float(base_equity or 0)
    live = float(live_equity or 0)
    if not compound:
        return base if base > 0 else live
    eq = live if live > 0 else base
    return eq if eq > 0 else base


def risk_budget_yuan(equity: float, risk_pct: float = 1.5, l1_mult: float = 1.0) -> float:
    return float(equity) * float(risk_pct) / 100.0 * float(l1_mult)


def _strength(sig: dict) -> float:
    return abs(float(sig.get("r20") or 0)) + abs(float(sig.get("r60") or 0))


def _notional(lots: int, close: float | None, mult: float) -> float:
    if lots <= 0 or close is None or close <= 0 or mult <= 0:
        return 0.0
    return abs(lots) * float(close) * float(mult)


def _atr_risk(lots: int, atr: float | None, mult: float) -> float:
    if lots <= 0 or atr is None or atr <= 0 or mult <= 0:
        return 0.0
    return abs(lots) * float(atr) * float(mult)


def apply_portfolio_caps(
    candidates: list[dict[str, Any]],
    *,
    equity: float,
    max_positions: int = 3,
    max_gross_exposure_pct: float = 50.0,
    max_portfolio_risk_pct: float = 8.0,
    max_per_bucket: int = 1,
    min_r20_pct: float = 3.0,
    min_r60_pct: float = 5.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Pipeline:
      1) Drop weak momentum (|r20|<min_r20 or |r60|<min_r60)
      2) Rank by |r20|+|r60|
      3) Pick ≤ max_positions with ≤ max_per_bucket per sector bucket
      4) Scale lots so gross notional ≤ equity × max_gross_exposure_pct%
      5) Scale lots so Σ(lots×ATR×mult) ≤ equity × max_portfolio_risk_pct%

    Candidate fields: code, direction, lots, close, mult, r20, r60, optional atr/bucket.
    """
    meta: dict[str, Any] = {
        "max_positions": max_positions,
        "max_gross_exposure_pct": max_gross_exposure_pct,
        "max_portfolio_risk_pct": max_portfolio_risk_pct,
        "max_per_bucket": max_per_bucket,
        "min_r20_pct": min_r20_pct,
        "min_r60_pct": min_r60_pct,
        "candidates_n": len(candidates),
        "weak_filtered": [],
        "bucket_skipped": [],
        "scale_gross": 1.0,
        "scale_risk": 1.0,
        "scale": 1.0,
        "gross_before": 0.0,
        "gross_after": 0.0,
        "atr_risk_before": 0.0,
        "atr_risk_after": 0.0,
        "dropped": [],
    }
    if equity <= 0:
        return [], meta

    # 1) momentum floor
    strong: list[dict[str, Any]] = []
    for c in candidates:
        r20 = abs(float(c.get("r20") or 0))
        r60 = abs(float(c.get("r60") or 0))
        if r20 < float(min_r20_pct) or r60 < float(min_r60_pct):
            meta["weak_filtered"].append(c.get("code"))
            continue
        strong.append(dict(c))

    # 2–3) rank + bucket dedupe + N cap
    ranked = sorted(strong, key=_strength, reverse=True)
    selected: list[dict[str, Any]] = []
    bucket_counts: dict[str, int] = {}
    for c in ranked:
        if len(selected) >= max(0, int(max_positions)):
            meta["dropped"].append(c.get("code"))
            continue
        bucket = str(c.get("bucket") or "_")
        if int(max_per_bucket) > 0 and bucket_counts.get(bucket, 0) >= int(max_per_bucket):
            meta["bucket_skipped"].append(c.get("code"))
            continue
        selected.append(c)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    def _gross(rows: list[dict]) -> float:
        return sum(
            _notional(int(x.get("lots") or 0), x.get("close"), float(x.get("mult") or 0))
            for x in rows
        )

    def _risk(rows: list[dict]) -> float:
        return sum(
            _atr_risk(int(x.get("lots") or 0), x.get("atr"), float(x.get("mult") or 0))
            for x in rows
        )

    meta["gross_before"] = round(_gross(selected), 2)
    meta["atr_risk_before"] = round(_risk(selected), 2)

    gross_cap = equity * float(max_gross_exposure_pct) / 100.0
    risk_cap = equity * float(max_portfolio_risk_pct) / 100.0

    # 4) notional scale
    gross = _gross(selected)
    if gross > gross_cap and gross > 0:
        sg = gross_cap / gross
        meta["scale_gross"] = round(sg, 4)
        for c in selected:
            c["lots"] = int(math.floor(int(c.get("lots") or 0) * sg))
        selected = [c for c in selected if int(c.get("lots") or 0) > 0]

    # 5) ATR portfolio risk scale
    risk = _risk(selected)
    if risk > risk_cap and risk > 0:
        sr = risk_cap / risk
        meta["scale_risk"] = round(sr, 4)
        for c in selected:
            c["lots"] = int(math.floor(int(c.get("lots") or 0) * sr))
        selected = [c for c in selected if int(c.get("lots") or 0) > 0]

    meta["scale"] = round(float(meta["scale_gross"]) * float(meta["scale_risk"]), 4)

    # Hard trim if still over (floor rounding) — drop weakest first
    while selected and (_gross(selected) > gross_cap + 1e-6 or _risk(selected) > risk_cap + 1e-6):
        selected.sort(key=_strength)
        dropped = selected.pop(0)
        meta["dropped"].append(dropped.get("code"))

    # Refill from ranked if room after scaling zeros (respect bucket + caps)
    have = {c.get("code") for c in selected}
    if len(selected) < int(max_positions):
        bucket_counts = {}
        for c in selected:
            b = str(c.get("bucket") or "_")
            bucket_counts[b] = bucket_counts.get(b, 0) + 1
        scale = float(meta["scale"]) if float(meta["scale"]) > 0 else 1.0
        for c in ranked:
            if len(selected) >= int(max_positions):
                break
            if c.get("code") in have:
                continue
            bucket = str(c.get("bucket") or "_")
            if int(max_per_bucket) > 0 and bucket_counts.get(bucket, 0) >= int(max_per_bucket):
                continue
            trial = dict(c)
            trial["lots"] = int(math.floor(int(c.get("lots") or 0) * scale))
            if trial["lots"] <= 0:
                continue
            trial_rows = selected + [trial]
            if _gross(trial_rows) <= gross_cap + 1e-6 and _risk(trial_rows) <= risk_cap + 1e-6:
                selected.append(trial)
                have.add(trial.get("code"))
                bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    meta["gross_after"] = round(_gross(selected), 2)
    meta["atr_risk_after"] = round(_risk(selected), 2)
    meta["selected"] = [c.get("code") for c in selected]
    meta["gross_pct"] = round(meta["gross_after"] / equity * 100, 2) if equity else 0.0
    meta["atr_risk_pct"] = round(meta["atr_risk_after"] / equity * 100, 2) if equity else 0.0
    return selected, meta
