# -*- coding: utf-8 -*-
"""15m ↔ 60m resonance filter for LSP events."""
from __future__ import annotations

from typing import Any, Sequence


def _parse_ts(s: str) -> str:
    return str(s or "")[:16]


def resonate_with_higher_tf(
    events_15: Sequence[dict[str, Any]],
    events_60: Sequence[dict[str, Any]],
    *,
    price_tol_pct: float = 0.003,
    time_bars_60_slack: int = 3,
) -> list[dict[str, Any]]:
    """Mark 15m events that share direction and nearby level with a 60m event."""
    h60 = list(events_60)
    out = []
    for e in events_15:
        ev = dict(e)
        matched = None
        lvl = float(ev.get("level_price") or 0)
        direction = ev.get("break_direction")
        ts = _parse_ts(ev.get("timestamp") or "")
        for h in h60:
            if h.get("break_direction") != direction:
                continue
            hl = float(h.get("level_price") or 0)
            if lvl <= 0 or hl <= 0:
                continue
            if abs(lvl - hl) / hl > price_tol_pct:
                continue
            # rough time proximity via string compare on date
            ht = _parse_ts(h.get("timestamp") or "")
            if ts[:10] == ht[:10] or abs(int(ev.get("bar_index") or 0) - int(h.get("bar_index") or 0)) < 9999:
                # same calendar day preferred
                if ts[:10] == ht[:10]:
                    matched = h
                    break
        ev["htf_resonance"] = matched is not None
        if matched:
            ev["htf_level_price"] = matched.get("level_price")
            ev["htf_outcome"] = matched.get("outcome")
        out.append(ev)
    return out


def resonance_stats(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    from collections import Counter

    res = [e for e in events if e.get("htf_resonance")]
    non = [e for e in events if not e.get("htf_resonance")]

    def probs(rows):
        c = Counter(e.get("outcome") for e in rows if e.get("outcome"))
        n = sum(c.values()) or 1
        return {k: round(v / n, 4) for k, v in sorted(c.items())}

    return {
        "n_resonant": len(res),
        "n_non_resonant": len(non),
        "resonant_outcome_probs": probs(res),
        "non_resonant_outcome_probs": probs(non),
    }
