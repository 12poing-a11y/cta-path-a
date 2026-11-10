# -*- coding: utf-8 -*-
"""Liquidity Sweep Profile (LSP) v1 — causal HVN/VA sweep + reclaim (shadow).

Research only. Not Path-A. Profile at bar ``i`` uses bars ``[i-lookback, i)``
only (no future volume). A signal fires when bar ``i`` pierces VAH/VAL (or HVN
edge) and **closes back inside**, then the simulator fills the next open.

This is intentionally simpler than the ChatGPT multi-TF (15/5/1) design:
daily + 60m first; no Delta/OI gate in v1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Direction = Literal["long", "short"]


@dataclass(frozen=True)
class LspParams:
    lookback: int = 48
    bins: int = 24
    value_area_frac: float = 0.70
    # Require pierce beyond edge by this fraction of (vah-val) (0 = touch enough).
    pierce_buffer_frac: float = 0.0
    max_signals: int = 500

    def validated(self) -> LspParams:
        if self.lookback < 10:
            raise ValueError("lookback must be >= 10")
        if self.bins < 5:
            raise ValueError("bins must be >= 5")
        if not (0.5 <= self.value_area_frac <= 0.95):
            raise ValueError("value_area_frac must be in [0.5, 0.95]")
        if self.pierce_buffer_frac < 0:
            raise ValueError("pierce_buffer_frac must be >= 0")
        if self.max_signals < 1:
            raise ValueError("max_signals must be >= 1")
        return self


@dataclass
class ProfileSnapshot:
    end_index: int  # exclusive end of bars used
    poc: float
    vah: float
    val: float
    total_volume: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LspSignal:
    signal_id: str
    direction: Direction
    signal_index: int
    signal_date: str
    pierce_price: float
    reclaim_close: float
    edge: float  # vah for short, val for long
    poc: float
    vah: float
    val: float
    stop_price: float
    timeframe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LspDetection:
    params: dict[str, Any]
    profiles_sampled: int
    signals: list[LspSignal] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": self.params,
            "profiles_sampled": self.profiles_sampled,
            "n_signals": len(self.signals),
            "signals": [s.to_dict() for s in self.signals],
            "notes": self.notes,
        }


def _typical_volume_points(bars: list[dict[str, Any]]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for b in bars:
        try:
            h, l, c = float(b["high"]), float(b["low"]), float(b["close"])
            v = float(b.get("volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if v <= 0 or l <= 0 or h < l:
            continue
        mid = (h + l + c) / 3.0
        pts.append((mid, v))
    return pts


def build_profile(bars: list[dict[str, Any]], params: LspParams) -> ProfileSnapshot | None:
    """Volume-at-typical-price histogram → POC / VAH / VAL (value area)."""
    params = params.validated()
    pts = _typical_volume_points(bars)
    if len(pts) < 5:
        return None
    prices = [p for p, _ in pts]
    lo, hi = min(prices), max(prices)
    if hi <= lo:
        return None
    width = (hi - lo) / params.bins
    vol = [0.0] * params.bins
    for p, v in pts:
        idx = int((p - lo) / width)
        if idx >= params.bins:
            idx = params.bins - 1
        if idx < 0:
            idx = 0
        vol[idx] += v
    total = sum(vol)
    if total <= 0:
        return None
    poc_i = max(range(params.bins), key=lambda i: vol[i])
    # Expand value area around POC until covering value_area_frac of volume.
    left = right = poc_i
    covered = vol[poc_i]
    target = total * params.value_area_frac
    while covered < target and (left > 0 or right < params.bins - 1):
        left_v = vol[left - 1] if left > 0 else -1.0
        right_v = vol[right + 1] if right < params.bins - 1 else -1.0
        if right_v >= left_v and right < params.bins - 1:
            right += 1
            covered += vol[right]
        elif left > 0:
            left -= 1
            covered += vol[left]
        else:
            break
    poc = lo + (poc_i + 0.5) * width
    val = lo + left * width
    vah = lo + (right + 1) * width
    return ProfileSnapshot(
        end_index=-1,
        poc=float(poc),
        vah=float(vah),
        val=float(val),
        total_volume=float(total),
    )


def detect_lsp_sweeps(
    bars: list[dict[str, Any]],
    params: LspParams | None = None,
    *,
    timeframe: str = "",
) -> LspDetection:
    """Scan bars for pierce-and-reclaim of causal value-area edges."""
    params = (params or LspParams()).validated()
    notes: list[str] = []
    signals: list[LspSignal] = []
    sampled = 0
    if len(bars) < params.lookback + 2:
        notes.append("bars shorter than lookback+2")
        return LspDetection(params=asdict(params), profiles_sampled=0, signals=[], notes=notes)

    for i in range(params.lookback, len(bars)):
        window = bars[i - params.lookback : i]
        snap = build_profile(window, params)
        if snap is None:
            continue
        sampled += 1
        snap.end_index = i
        try:
            h = float(bars[i]["high"])
            l = float(bars[i]["low"])
            c = float(bars[i]["close"])
        except (KeyError, TypeError, ValueError):
            continue
        band = max(snap.vah - snap.val, 1e-9)
        buf = band * params.pierce_buffer_frac
        date = str(bars[i].get("date") or bars[i].get("datetime") or i)

        # Sweep high / VAH → short if close reclaims below VAH
        if h > snap.vah + buf and c < snap.vah:
            signals.append(
                LspSignal(
                    signal_id=f"S{i}",
                    direction="short",
                    signal_index=i,
                    signal_date=date,
                    pierce_price=h,
                    reclaim_close=c,
                    edge=snap.vah,
                    poc=snap.poc,
                    vah=snap.vah,
                    val=snap.val,
                    stop_price=h,
                    timeframe=timeframe,
                )
            )
        # Sweep low / VAL → long if close reclaims above VAL
        elif l < snap.val - buf and c > snap.val:
            signals.append(
                LspSignal(
                    signal_id=f"L{i}",
                    direction="long",
                    signal_index=i,
                    signal_date=date,
                    pierce_price=l,
                    reclaim_close=c,
                    edge=snap.val,
                    poc=snap.poc,
                    vah=snap.vah,
                    val=snap.val,
                    stop_price=l,
                    timeframe=timeframe,
                )
            )
        if len(signals) >= params.max_signals:
            notes.append(f"hit max_signals={params.max_signals}")
            break

    return LspDetection(
        params=asdict(params),
        profiles_sampled=sampled,
        signals=signals,
        notes=notes,
    )


def params_from_config(cfg: dict[str, Any]) -> LspParams:
    p = cfg.get("params") or cfg
    return LspParams(
        lookback=int(p.get("lookback", 48)),
        bins=int(p.get("bins", 24)),
        value_area_frac=float(p.get("value_area_frac", 0.70)),
        pierce_buffer_frac=float(p.get("pierce_buffer_frac", 0.0)),
        max_signals=int(p.get("max_signals", 500)),
    ).validated()


def load_run_config(path) -> dict[str, Any]:
    import json
    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8"))
