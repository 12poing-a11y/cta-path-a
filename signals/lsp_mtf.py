# -*- coding: utf-8 -*-
"""Multi-timeframe LSP: daily bias filter × 60m pierce-and-reclaim entries.

Causal rule: for a 60m signal on calendar day D, use the **previous completed
daily bar** bias (SMA). Flat days reject both directions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from signals.lsp_profile import LspDetection, LspParams, LspSignal, detect_lsp_sweeps

Bias = Literal["long", "short", "flat"]


@dataclass(frozen=True)
class DailyBiasParams:
    sma_len: int = 20

    def validated(self) -> DailyBiasParams:
        if self.sma_len < 5:
            raise ValueError("sma_len must be >= 5")
        return self


def _bar_date(bar: dict[str, Any]) -> str:
    return str(bar.get("date") or bar.get("datetime") or "")[:10]


def daily_bias_map(
    daily_bars: list[dict[str, Any]],
    params: DailyBiasParams | None = None,
) -> dict[str, Bias]:
    """Map each daily bar date → bias knowable at that day's close.

    Bias on day D uses closes up to and including D (SMA of last sma_len closes).
    When filtering 60m on day D, callers must look up bias for the prior session.
    """
    params = (params or DailyBiasParams()).validated()
    closes: list[float] = []
    dates: list[str] = []
    out: dict[str, Bias] = {}
    for b in daily_bars:
        d = _bar_date(b)
        if len(d) != 10:
            continue
        try:
            c = float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
        closes.append(c)
        dates.append(d)
        if len(closes) < params.sma_len:
            out[d] = "flat"
            continue
        sma = sum(closes[-params.sma_len :]) / params.sma_len
        if c > sma:
            out[d] = "long"
        elif c < sma:
            out[d] = "short"
        else:
            out[d] = "flat"
    return out


def prior_session_bias(bias_by_date: dict[str, Bias], day: str) -> Bias | None:
    """Bias from the latest daily session strictly before ``day``."""
    day = str(day or "")[:10]
    priors = [d for d in bias_by_date if d < day]
    if not priors:
        return None
    return bias_by_date[max(priors)]


def filter_signals_by_daily_bias(
    signals: list[LspSignal],
    bias_by_date: dict[str, Bias],
) -> tuple[list[LspSignal], list[dict[str, Any]]]:
    """Keep 60m signals only when direction matches prior-day daily bias."""
    kept: list[LspSignal] = []
    rejected: list[dict[str, Any]] = []
    for sig in signals:
        day = str(sig.signal_date or "")[:10]
        bias = prior_session_bias(bias_by_date, day)
        if bias is None:
            rejected.append(
                {
                    "signal_id": sig.signal_id,
                    "signal_date": sig.signal_date,
                    "direction": sig.direction,
                    "reason": "no_prior_daily",
                }
            )
            continue
        if bias == "flat":
            rejected.append(
                {
                    "signal_id": sig.signal_id,
                    "signal_date": sig.signal_date,
                    "direction": sig.direction,
                    "reason": "daily_flat",
                    "daily_bias": bias,
                }
            )
            continue
        if bias != sig.direction:
            rejected.append(
                {
                    "signal_id": sig.signal_id,
                    "signal_date": sig.signal_date,
                    "direction": sig.direction,
                    "reason": "against_daily",
                    "daily_bias": bias,
                }
            )
            continue
        kept.append(sig)
    return kept, rejected


def detect_lsp_60m_with_daily_filter(
    daily_bars: list[dict[str, Any]],
    bars_60: list[dict[str, Any]],
    *,
    lsp_params: LspParams | None = None,
    bias_params: DailyBiasParams | None = None,
) -> dict[str, Any]:
    """Run 60m detection then apply daily SMA bias filter."""
    bias_params = (bias_params or DailyBiasParams()).validated()
    lsp_params = (lsp_params or LspParams()).validated()
    bias = daily_bias_map(daily_bars, bias_params)
    raw = detect_lsp_sweeps(bars_60, lsp_params, timeframe="60")
    kept, rejected = filter_signals_by_daily_bias(raw.signals, bias)
    filtered = LspDetection(
        params=raw.params,
        profiles_sampled=raw.profiles_sampled,
        signals=kept,
        notes=list(raw.notes) + [f"daily_sma_filter={bias_params.sma_len}", f"rejected={len(rejected)}"],
    )
    return {
        "bias_params": asdict(bias_params),
        "n_daily_bias_days": len(bias),
        "n_raw_signals": len(raw.signals),
        "n_kept_signals": len(kept),
        "n_rejected": len(rejected),
        "rejected_sample": rejected[:20],
        "detection": filtered,
        "raw_detection": raw,
    }
