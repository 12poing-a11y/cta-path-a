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


def _simulate_cs(
    series: dict,
    curves: dict,
    *,
    name: str,
    mode: str,
    equity0: float = 200_000.0,
    top_n: int = 3,
) -> dict:
    """Cross-section long top_n / short bottom_n, equal weight, daily rebalance."""
    dates = sorted({bar["date"] for pack in series.values() for bar in pack["hist"]})
    # Align index maps
    idx = {
        code: {bar["date"]: i for i, bar in enumerate(pack["hist"])}
        for code, pack in series.items()
    }
    equity = equity0
    curve: list[dict] = []
    rets_day: list[float] = []

    start_i = 60
    if len(dates) > start_i:
        curve.append({"date": dates[start_i], "equity": equity0})
    for d in dates[start_i + 1 :]:
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
            c_score = 0.0 if gap is None else -gap  # 贴水(负gap)偏多
            t_score = 0.5 * r20 + 0.5 * r60
            st_score = r5 if r5 is not None else 0.0
            f_score = c_score  # futures-spot proxy = same carry gap when spot missing
            w_score = 0.0  # warrant unavailable → neutral
            if mode == "cwft":
                # 5:2:2:1 on C,W,F,T
                raw = 5 * c_score + 2 * w_score + 2 * f_score + 1 * t_score
            elif mode == "frontnext_st":
                # Main carry, short-trend as secondary (subtract when opposite).
                raw = 3.0 * c_score + 1.0 * st_score
            elif mode == "long_short_cwft":
                long_c = 5 * c_score + 2 * f_score + 1 * (0.3 * r20 + 0.7 * r60)
                short_c = 5 * c_score + 2 * f_score + 1 * (0.7 * r20 + 0.3 * (r5 or 0.0))
                raw = 0.7 * long_c + 0.3 * short_c
            else:
                raw = t_score
            scores[code] = raw
        if len(scores) < top_n * 2:
            curve.append({"date": d, "equity": round(equity, 2)})
            continue
        z = _zcross(scores)
        ranked = sorted(z.items(), key=lambda kv: kv[1], reverse=True)
        longs = [c for c, _ in ranked[:top_n]]
        shorts = [c for c, _ in ranked[-top_n:]]
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
    return {
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
        "summary": (
            f"proxy {name} ret={ret_pct:.2f}% ann≈{ann:.2f}% "
            f"dd={dd:.2f}% sharpe={sharpe}"
        ),
    }


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
