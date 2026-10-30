# -*- coding: utf-8 -*-
"""Paper-only sentiment sleeve: MDS + EHI (ChatGPT 三层情绪策略简化落地).

Layer 1 — MDS (Momentum Divergence Score): direction of seat net vs price.
Layer 2 — EHI (Emotion Heat Index): |net| / open_interest (or volume proxy).
Layer 3 — optional logistic blend (weights only; no live orders).

Commodity basket weights from share (normalized locally). Paper sleeve only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "sentiment_mds"
OUT.mkdir(parents=True, exist_ok=True)

# Share weights (commodity sentiment basket); renormalized over available codes.
COMMODITY_WEIGHTS: dict[str, float] = {
    "SC": 0.12,
    "FU": 0.08,
    "BU": 0.06,
    "RU": 0.10,
    "NR": 0.05,
    "CU": 0.12,
    "AL": 0.08,
    "ZN": 0.06,
    "NI": 0.05,
    "AU": 0.08,
    "AG": 0.06,
    "I": 0.08,
    "JM": 0.06,
    "J": 0.05,
    "RB": 0.08,
    "HC": 0.05,
    "SS": 0.04,
    "V": 0.04,
    "MA": 0.04,
    "TA": 0.04,
    "EG": 0.03,
    "EB": 0.03,
    "FG": 0.03,
    "SA": 0.03,
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def mds_from_row(net: float, net_chg: float, ret: float) -> float:
    """Positive when seat flow and price agree; negative when diverge."""
    flow = _sign(net_chg if abs(net_chg) > 1e-12 else net)
    px = _sign(ret)
    if flow == 0 or px == 0:
        return 0.0
    return float(flow * px)


def ehi_from_row(net: float, oi: float | None, vol: float | None) -> float:
    """|net| / OI; fall back to |net| / vol if OI missing."""
    denom = _f(oi, 0.0)
    if denom <= 0:
        denom = _f(vol, 0.0)
    if denom <= 0:
        return 0.0
    return abs(_f(net)) / denom


def score_symbol(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("code") or "").upper()
    net = _f(row.get("net"))
    net_chg = _f(row.get("net_chg"), net)
    ret = _f(row.get("ret_1d"), _f(row.get("ret")))
    oi = row.get("oi") if row.get("oi") is not None else row.get("open_interest")
    vol = row.get("volume") if row.get("volume") is not None else row.get("vol")
    mds = mds_from_row(net, net_chg, ret)
    ehi = ehi_from_row(net, _f(oi) if oi is not None else None, _f(vol) if vol is not None else None)
    # Soft gate: need heat to trust MDS direction
    signal = 0
    if ehi >= 0.02 and mds > 0:
        signal = 1 if net >= 0 else -1
    elif ehi >= 0.02 and mds < 0:
        signal = 0  # divergence → flat / caution
    return {
        "code": code,
        "mds": round(mds, 4),
        "ehi": round(ehi, 6),
        "net": net,
        "net_chg": net_chg,
        "ret_1d": ret,
        "signal": signal,
        "weight": COMMODITY_WEIGHTS.get(code, 0.0),
    }


def blend_p3(mds: float, ehi: float, *, w_mds: float = 0.55, w_ehi: float = 0.45) -> float:
    """Layer-3 style score in [-1, 1] without fitting a live model."""
    # Map EHI into [0,1] soft cap
    ehi_n = min(1.0, max(0.0, ehi / 0.15))
    raw = w_mds * mds + w_ehi * (ehi_n if mds >= 0 else -ehi_n)
    return max(-1.0, min(1.0, raw))


def build_snapshot(
    seat_rows: list[dict[str, Any]],
    *,
    asof: str,
    price_by_code: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    price_by_code = price_by_code or {}
    scored: list[dict[str, Any]] = []
    for row in seat_rows:
        code = str(row.get("code") or "").upper()
        if not code:
            continue
        merged = dict(row)
        merged["code"] = code
        px = price_by_code.get(code) or {}
        if merged.get("ret_1d") is None and merged.get("ret") is None:
            merged["ret_1d"] = px.get("ret_1d") if px.get("ret_1d") is not None else (px.get("ret") or 0.0)
        if merged.get("oi") is None and merged.get("open_interest") is None:
            if px.get("oi") is not None:
                merged["oi"] = px.get("oi")
            elif px.get("open_interest") is not None:
                merged["oi"] = px.get("open_interest")
        if merged.get("volume") is None and px.get("volume") is not None:
            merged["volume"] = px.get("volume")
        s = score_symbol(merged)
        s["p3"] = round(blend_p3(s["mds"], s["ehi"]), 4)
        scored.append(s)

    # Renormalize weights over scored basket members
    w_sum = sum(COMMODITY_WEIGHTS.get(s["code"], 0.0) for s in scored if s["code"] in COMMODITY_WEIGHTS)
    portfolio = 0.0
    longs: list[str] = []
    shorts: list[str] = []
    for s in scored:
        w = COMMODITY_WEIGHTS.get(s["code"], 0.0)
        wn = (w / w_sum) if w_sum > 0 else 0.0
        s["w_norm"] = round(wn, 6)
        portfolio += wn * s["p3"]
        if s["signal"] > 0:
            longs.append(s["code"])
        elif s["signal"] < 0:
            shorts.append(s["code"])

    snap = {
        "asof": asof,
        "generated_at": _iso_now(),
        "sleeve": "sentiment_mds_paper",
        "live": False,
        "portfolio_p3": round(portfolio, 4),
        "stance": "risk_on" if portfolio > 0.15 else ("risk_off" if portfolio < -0.15 else "neutral"),
        "longs": longs,
        "shorts": shorts,
        "n": len(scored),
        "symbols": sorted(scored, key=lambda x: (-abs(x.get("p3") or 0), x["code"])),
        "note": "Paper-only MDS+EHI sleeve from ChatGPT share; does not place live orders.",
    }
    return snap


def price_row_from_bars(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """ret_1d (close/prev close - 1), OI and volume from the last two daily bars."""
    if len(bars) < 2:
        return {}
    b0, b1 = bars[-2], bars[-1]
    c0, c1 = _f(b0.get("close")), _f(b1.get("close"))
    oi = b1.get("oi") if b1.get("oi") is not None else b1.get("open_interest")
    return {
        "ret_1d": round(c1 / c0 - 1.0, 6) if c0 > 0 else None,
        "oi": oi,
        "volume": b1.get("volume"),
        "bar_date": b1.get("date"),
        "prev_date": b0.get("date"),
        "close": c1,
    }


def write_snapshot(snap: dict[str, Any], *, out_dir: Path | None = None, update_latest: bool = True) -> Path:
    """Write dated snapshot. Shadow runs pass out_dir and update_latest=False."""
    asof = str(snap.get("asof") or "unknown")
    out = out_dir or OUT
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"sentiment_{asof}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    if not update_latest:
        return path
    latest = out / "latest.json"
    latest.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_latest() -> dict[str, Any] | None:
    p = OUT / "latest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
