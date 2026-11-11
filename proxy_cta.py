# -*- coding: utf-8 -*-
"""Local paper proxies for 东证-style CWFT / front-next+short-trend.

These are research approximations on the Path-A universe using free bars +
carry gaps. They are NOT the Orient Securities factor library. Output JSON
files land in ``external/strategies/`` and register via desk extra specs.

Usage:
  python proxy_cta.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _ret(hist: list[dict], i: int, n: int) -> float | None:
    if i < n:
        return None
    a, b = hist[i - n]["close"], hist[i]["close"]
    if not a:
        return None
    return (b / a - 1.0) * 100.0


def _zcross(values: dict[str, float]) -> dict[str, float]:
    """Cross-sectional demean / std (0 if flat)."""
    if len(values) < 3:
        return {k: 0.0 for k in values}
    xs = list(values.values())
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / len(xs)
    sd = math.sqrt(var) if var > 1e-12 else 0.0
    if sd <= 0:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


def _carry_gap(pair) -> float | None:
    if not pair or len(pair) < 2:
        return None
    front, nxt = float(pair[0]), float(pair[1])
    if front <= 0:
        return None
    return (nxt - front) / front * 100.0


def _max_dd(equity: list[float]) -> float:
    peak = equity[0]
    dd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return dd * 100.0


POSITIONS_DISCLAIMER = (
    "研究模拟持仓·非实盘·与 Path-A paper_book 分离；"
    "由本地代理等权多空规则在最后一根日线收盘后推出（下一交易日目标仓），不构成交易建议。"
)
TRADE_LOG_MAX = 60


def _score_day(
    series: dict,
    idx: dict,
    curves: dict,
    d: str,
    mode: str,
    ablate: frozenset[str] | set[str] | None = None,
) -> dict[str, float]:
    """Raw factor score per code on date ``d`` (only codes with >=60 bars of history).

    ``ablate`` zeros named factor blocks (C/F/T/ST/LONG_MOM/SHORT_MOM) for research grids.
    """
    off = frozenset(ablate or ())
    scores: dict[str, float] = {}
    for code, pack in series.items():
        i = idx[code].get(d)
        if i is None or i < 60:
            continue
        hist = pack["hist"]
        r20 = _ret(hist, i, 20)
        r60 = _ret(hist, i, 60)
        r5 = _ret(hist, i, 5)
        if r20 is None or r60 is None:
            continue
        gap = _carry_gap((curves.get(code) or {}).get("carry", {}).get(d))
        # Factor building blocks (local proxies).
        c_raw = 0.0 if gap is None else -gap  # 贴水(负gap)偏多
        c_score = 0.0 if "C" in off else c_raw
        t_score = 0.0 if "T" in off else (0.5 * r20 + 0.5 * r60)
        st_score = 0.0 if "ST" in off else (r5 if r5 is not None else 0.0)
        # F uses the same carry-gap proxy when spot is missing; ablate independently of C.
        f_score = 0.0 if "F" in off else c_raw
        w_score = 0.0  # warrant unavailable → neutral
        long_mom = 0.0 if "LONG_MOM" in off else (0.3 * r20 + 0.7 * r60)
        short_mom = 0.0 if "SHORT_MOM" in off else (0.7 * r20 + 0.3 * (r5 or 0.0))
        if mode == "cwft":
            # 5:2:2:1 on C,W,F,T
            raw = 5 * c_score + 2 * w_score + 2 * f_score + 1 * t_score
        elif mode == "frontnext_st":
            # Main carry, short-trend as secondary (subtract when opposite).
            raw = 3.0 * c_score + 1.0 * st_score
        elif mode == "long_short_cwft":
            long_c = 5 * c_score + 2 * f_score + 1 * long_mom
            short_c = 5 * c_score + 2 * f_score + 1 * short_mom
            raw = 0.7 * long_c + 0.3 * short_c
        else:
            raw = t_score
        scores[code] = raw
    return scores


def _pick_legs(
    scores: dict[str, float], top_n: int
) -> tuple[list[str], list[str], dict[str, float]]:
    """Rank by cross-sectional z; long top_n, short bottom_n. Returns (longs, shorts, z)."""
    z = _zcross(scores)
    ranked = sorted(z.items(), key=lambda kv: kv[1], reverse=True)
    longs = [c for c, _ in ranked[:top_n]]
    shorts = [c for c, _ in ranked[-top_n:]]
    return longs, shorts, z


def _signed_pct(entry_px, px, direction: str) -> float | None:
    if not entry_px or not px:
        return None
    raw = px / entry_px - 1.0
    return round((raw if direction == "long" else -raw) * 100.0, 3) + 0.0  # no -0.0


def _pos_row(
    code: str,
    *,
    pack: dict,
    held: dict,
    d: str,
    idx: dict,
    weight: float,
    equity: float,
    z: float | None,
) -> dict:
    hist = pack["hist"]
    meta = pack.get("meta") or {}
    i = idx[code].get(d)
    last_px = hist[i]["close"] if i is not None else None
    direction = held["direction"]
    notional = abs(weight) * equity
    try:
        mult = float(meta.get("mult") or 0) or None
    except (TypeError, ValueError):
        mult = None
    lots_equiv = round(notional / (last_px * mult), 3) if (mult and last_px) else None
    return {
        "code": code,
        "name": meta.get("name"),
        "direction": direction,
        "weight": round(weight, 6),
        "notional_yuan": round(notional, 2),
        "lots_equiv": lots_equiv,
        "entry_date": held.get("entry_date"),
        "entry_price": held.get("entry_px"),
        "last_price": last_px,
        "unrealized_pct": _signed_pct(held.get("entry_px"), last_px, direction),
        "score_z": round(z, 3) if z is not None else None,
    }


def _simulate_cs(
    series: dict,
    curves: dict,
    *,
    name: str,
    mode: str,
    equity0: float = 200_000.0,
    top_n: int = 3,
    ablate: frozenset[str] | set[str] | None = None,
) -> dict:
    """Cross-section long top_n / short bottom_n, equal weight, daily rebalance.

    Holdings are derived from the *same* daily picks as the equity curve:
    ``final_positions`` (asof last scored bar) and ``trade_log`` (open/close events).
    ``ablate`` is forwarded to ``_score_day`` and echoed on the payload when non-empty.
    """
    dates = sorted({bar["date"] for pack in series.values() for bar in pack["hist"]})
    # Align index maps
    idx = {
        code: {bar["date"]: i for i, bar in enumerate(pack["hist"])}
        for code, pack in series.items()
    }
    equity = equity0
    curve: list[dict] = []
    rets_day: list[float] = []
    # code -> {direction, entry_date, entry_px}; reset when a leg flips side or drops out.
    held: dict[str, dict] = {}
    trade_log: list[dict] = []
    pos_asof: str | None = None
    pos_z: dict[str, float] = {}

    def _px(code: str, d: str):
        i = idx[code].get(d)
        return series[code]["hist"][i]["close"] if i is not None else None

    start_i = 60
    if len(dates) > start_i:
        curve.append({"date": dates[start_i], "equity": equity0})
    for d in dates[start_i + 1 :]:
        scores = _score_day(series, idx, curves, d, mode, ablate=ablate)
        if len(scores) < top_n * 2:
            curve.append({"date": d, "equity": round(equity, 2)})
            continue
        longs, shorts, z = _pick_legs(scores, top_n)
        target = {c: "long" for c in longs} | {c: "short" for c in shorts}
        # Holdings bookkeeping; entry = close of pick day (matches close[t]→close[t+1] curve).
        for code in list(held):
            h = held[code]
            if target.get(code) != h["direction"]:
                px = _px(code, d)
                trade_log.append(
                    {
                        "date": d, "code": code, "action": "close",
                        "direction": h["direction"], "price": px,
                        "entry_date": h["entry_date"],
                        "pnl_pct": _signed_pct(h["entry_px"], px, h["direction"]),
                    }
                )
                del held[code]
        for code, direction in target.items():
            if code in held:
                continue
            px = _px(code, d)
            held[code] = {"direction": direction, "entry_date": d, "entry_px": px}
            trade_log.append(
                {
                    "date": d, "code": code, "action": "open", "direction": direction,
                    "price": px, "entry_date": d, "pnl_pct": None,
                }
            )
        pos_asof = d
        pos_z = z
        day_ret = 0.0
        n_legs = 0
        for code in longs + shorts:
            i = idx[code].get(d)
            hist = series[code]["hist"]
            if i is None or i + 1 >= len(hist):
                continue
            # Next-day open-to-close approx: close[t+1]/close[t]
            px0 = hist[i]["close"]
            px1 = hist[i + 1]["close"]
            if not px0:
                continue
            r = (px1 / px0) - 1.0
            day_ret += r if code in longs else -r
            n_legs += 1
        if n_legs:
            day_ret /= n_legs
            # Half gross exposure each side ≈ 1x combined notional / n_legs already averaged
            equity *= 1.0 + day_ret
            rets_day.append(day_ret)
        curve.append({"date": d, "equity": round(equity, 2)})

    leg_w = 1.0 / (2 * top_n)  # gross 1x split equally over 2*top_n legs
    final_positions: list[dict] = []
    if pos_asof:
        for code, h in held.items():
            w = leg_w if h["direction"] == "long" else -leg_w
            final_positions.append(
                _pos_row(
                    code, pack=series[code], held=h, d=pos_asof, idx=idx,
                    weight=w, equity=equity, z=pos_z.get(code),
                )
            )
        final_positions.sort(
            key=lambda r: (r["direction"] != "long", -(r["score_z"] or 0.0))
        )

    if len(curve) < 2:
        return {"ok": False, "error": "curve too short", "strategy": name}

    eq = [c["equity"] for c in curve]
    ret_pct = (eq[-1] / eq[0] - 1.0) * 100.0
    dd = _max_dd(eq)
    # Annualize with 252d if we have daily rets
    if rets_day:
        mu = sum(rets_day) / len(rets_day)
        var = sum((r - mu) ** 2 for r in rets_day) / max(1, len(rets_day) - 1)
        vol = math.sqrt(var) * math.sqrt(252) if var > 0 else 0.0
        ann = mu * 252 * 100.0
        sharpe = (mu * 252 / vol) if vol > 0 else None
    else:
        ann = ret_pct
        sharpe = None
    calmar = (ann / dd) if dd > 0 else None
    out = {
        "ok": True,
        "strategy": name,
        "proxy_of": mode,
        "family": "commodity_proxy",
        "track_source": "local proxy_cta.py (Path-A universe)",
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "equity_start": equity0,
        "equity_end": round(eq[-1], 2),
        "ret_pct": round(ret_pct, 3),
        "ret_ann_pct": round(ann, 3) if ann is not None else None,
        "max_dd_pct": round(dd, 3),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "calmar": round(calmar, 3) if calmar is not None else None,
        "equity_curve": curve,
        "positions_asof": pos_asof,
        "positions_kind": "research_simulated_not_live",
        "positions_disclaimer": POSITIONS_DISCLAIMER,
        "final_positions": final_positions,
        "trade_log": trade_log[-TRADE_LOG_MAX:],
        "summary": (
            f"proxy {name} ret={ret_pct:.2f}% ann≈{ann:.2f}% "
            f"dd={dd:.2f}% sharpe={sharpe}"
        ),
    }
    if ablate:
        out["ablate"] = sorted(ablate)
    return out


def main() -> None:
    from historical_backtest import _fetch_pack, _load_cfg
    from public_curve import load_curves

    p = _load_cfg()
    symbols = p["cfg"]["symbols"]
    print("[proxy] fetch bars…")
    series, errors, _sources = _fetch_pack(symbols)
    if errors:
        print("[proxy] fetch errors", list(errors)[:5])
    codes = list(series.keys())
    print("[proxy] carry curves…")
    curves = load_curves(codes)

    specs = [
        ("proxy_cwft", "本地代理·CWFT", "cwft"),
        ("proxy_frontnext_st", "本地代理·C_frontnext&ShortTrend", "frontnext_st"),
        ("proxy_long_short_cwft", "本地代理·Long/Short CWFT", "long_short_cwft"),
    ]
    out_dir = ROOT / "external" / "strategies"
    extra_dir = ROOT / "desk" / "strategies" / "extra"
    out_dir.mkdir(parents=True, exist_ok=True)
    extra_dir.mkdir(parents=True, exist_ok=True)

    for sid, label, mode in specs:
        print(f"[proxy] simulate {sid}…")
        payload = _simulate_cs(series, curves, name=sid, mode=mode)
        payload["name"] = label
        payload["description"] = (
            f"{label}：东证 CWFT/期限结构思路的本地近似，"
            "用近远月升贴水 + 动量代理 C/F/T；仓单 W 缺数据时置 0。"
        )
        path = out_dir / f"{sid}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        extra = {
            "id": sid,
            "name": label,
            "description": payload["description"],
            "curve_file": f"external/strategies/{sid}.json",
            "tags": ["proxy", "dzqh_inspired", "commodity", mode],
        }
        (extra_dir / f"{sid}.json").write_text(
            json.dumps(extra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(" ", payload.get("summary"))


if __name__ == "__main__":
    main()
