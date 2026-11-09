# -*- coding: utf-8 -*-
"""Technical analysis scoreboard: MA / momentum / pattern / overlap / pivot / basis / HV → 1–5."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.hv_panel import hv_stats
from desk.loaders import load_l1_report, load_universe
from desk.regime_board import load_carry_gaps, load_local_bars


OUT_REL = Path("data") / "tech_score_latest.json"


def _ohlc_frame(bars: list[dict]) -> pd.DataFrame:
    rows = []
    for b in bars or []:
        d = str(b.get("date") or "")[:10]
        if len(d) != 10:
            continue
        try:
            o = float(b.get("open") if b.get("open") is not None else b["close"])
            h = float(b.get("high") if b.get("high") is not None else b["close"])
            l = float(b.get("low") if b.get("low") is not None else b["close"])
            c = float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if c <= 0 or l <= 0 or h < l:
            continue
        rows.append({"date": d, "open": o, "high": h, "low": l, "close": c})
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    return pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)


def _kline_pattern(df: pd.DataFrame, lookback: int = 20) -> str:
    """Classify mid-term structure: 上升 / 下降 / 箱体震荡 (not single-bar candles)."""
    n = int(lookback)
    if len(df) < max(n, 10):
        return "样本不足"
    win = df.tail(n)
    closes = win["close"].astype(float)
    highs = win["high"].astype(float)
    lows = win["low"].astype(float)
    mid = n // 2
    first_h, second_h = float(highs.iloc[:mid].max()), float(highs.iloc[mid:].max())
    first_l, second_l = float(lows.iloc[:mid].min()), float(lows.iloc[mid:].min())
    # Higher-high + higher-low vs lower-high + lower-low
    hh = second_h > first_h * 1.002
    hl = second_l > first_l * 1.002
    lh = second_h < first_h * 0.998
    ll = second_l < first_l * 0.998
    # Daily slope of close, normalized by mean price
    y = closes.to_numpy(dtype=float)
    x = pd.Series(range(len(y)), dtype=float).to_numpy()
    denom = float(len(y) * (x * x).sum() - x.sum() ** 2) or 1e-12
    slope = float(len(y) * (x * y).sum() - x.sum() * y.sum()) / denom
    mean_px = float(y.mean()) or 1.0
    slope_pct = slope / mean_px
    # Box width: tight range relative to price → favour 箱体
    box = (float(highs.max()) - float(lows.min())) / mean_px

    if hh and hl and slope_pct > 0.0004:
        return "上升"
    if lh and ll and slope_pct < -0.0004:
        return "下降"
    if slope_pct > 0.0012 and closes.iloc[-1] > closes.iloc[0]:
        return "上升"
    if slope_pct < -0.0012 and closes.iloc[-1] < closes.iloc[0]:
        return "下降"
    if box <= 0.06:
        return "箱体震荡"
    # Ambiguous swings with mild slope → box
    if abs(slope_pct) <= 0.0008:
        return "箱体震荡"
    return "上升" if slope_pct > 0 else "下降"


def _basis_txt(root: Path, code: str, sig: dict[str, Any]) -> str:
    basis = sig.get("basis_pct")
    if basis is None:
        basis = sig.get("carry_pct")
    if basis is None:
        basis = sig.get("gap")
    if basis is not None:
        try:
            return f"{float(basis):+.2f}%"
        except (TypeError, ValueError):
            pass
    gaps = load_carry_gaps(root, code)
    if not gaps:
        return "缺近远月"
    last = gaps[-1]
    try:
        g = float(last.get("gap"))
    except (TypeError, ValueError):
        return "缺近远月"
    src = str(last.get("source") or "")
    tag = f" ·{src}" if src else ""
    return f"近次月{g*100:+.2f}%{tag}"


def _vol_txt(closes: pd.Series, sig: dict[str, Any]) -> str:
    hv = sig.get("hv20") or sig.get("hv_pct") or sig.get("HV20%")
    if hv is not None:
        try:
            return f"HV20={float(hv):.1f}%"
        except (TypeError, ValueError):
            pass
    st = hv_stats(closes)
    if not st:
        return "样本不足"
    hv20 = st.get("HV20%")
    pct = st.get("HV20分位")
    if hv20 is None:
        return "样本不足"
    if pct is None:
        return f"HV20={hv20:.1f}%"
    return f"HV20={hv20:.1f}% ·分位{pct:.0f}"


def _score_row(
    root: Path,
    code: str,
    name: str,
    bars: list[dict],
    sig: dict[str, Any] | None,
) -> dict[str, Any]:
    """Explainable 1–5 score; 3 = 震荡. Local OHLC + carry + realized HV."""
    sig = sig or {}
    df = _ohlc_frame(bars)
    closes = df.set_index("date")["close"] if not df.empty else pd.Series(dtype=float)

    if len(closes) < 60:
        return {
            "品种": f"{code} {name}".strip(),
            "移动平均": "样本不足",
            "动量指标": "—",
            "K线形态": "样本不足" if len(df) < 20 else _kline_pattern(df),
            "重叠研究": "—",
            "枢轴点": "—",
            "基差": _basis_txt(root, code, sig),
            "波动率": _vol_txt(closes, sig) if len(closes) >= 61 else "样本不足",
            "合并信号": "震荡",
            "评分": 3,
        }

    px = float(closes.iloc[-1])
    ma20 = float(closes.tail(20).mean())
    ma60 = float(closes.tail(60).mean())
    r20 = float(closes.iloc[-1] / closes.iloc[-21] - 1.0) if len(closes) > 21 else 0.0
    r60 = float(closes.iloc[-1] / closes.iloc[-61] - 1.0) if len(closes) > 61 else 0.0

    last = df.iloc[-1]
    pivot = (float(last["high"]) + float(last["low"]) + float(last["close"])) / 3.0
    pivot_bias = "上" if px >= pivot else "下"

    ma_txt = f"价{'上' if px >= ma20 else '下'}MA20 / {'上' if px >= ma60 else '下'}MA60"
    mom_txt = f"r20={r20*100:+.1f}% r60={r60*100:+.1f}%"
    overlap = "多头重叠" if px >= ma20 >= ma60 else ("空头重叠" if px <= ma20 <= ma60 else "交叉/混杂")
    pattern = _kline_pattern(df)
    basis_txt = _basis_txt(root, code, sig)
    vol_txt = _vol_txt(closes, sig)

    lean = 0.0
    lean += 1.0 if px >= ma20 else -1.0
    lean += 1.0 if px >= ma60 else -1.0
    lean += 1.0 if r20 >= 0.03 else (-1.0 if r20 <= -0.03 else 0.0)
    lean += 1.0 if r60 >= 0.05 else (-1.0 if r60 <= -0.05 else 0.0)
    lean += 0.5 if overlap.startswith("多") else (-0.5 if overlap.startswith("空") else 0.0)
    lean += 0.5 if pivot_bias == "上" else -0.5
    if pattern == "上升":
        lean += 0.6
    elif pattern == "下降":
        lean -= 0.6
    # 箱体震荡: no lean

    score = int(round(max(1, min(5, 3 + lean / 2.0))))
    merge = {
        1: "强烈看跌",
        2: "看跌",
        3: "震荡",
        4: "看涨",
        5: "强烈看涨",
    }[score]

    return {
        "品种": f"{code} {name}".strip(),
        "移动平均": ma_txt,
        "动量指标": mom_txt,
        "K线形态": pattern,
        "重叠研究": overlap,
        "枢轴点": f"P={pivot:.0f} 价在{pivot_bias}",
        "基差": basis_txt,
        "波动率": vol_txt,
        "合并信号": merge,
        "评分": score,
    }


def write_tech_score_snapshot(root: Path) -> dict[str, Any]:
    """Rebuild and persist data/tech_score_latest.json. Used by desk + daily job."""
    df = build_tech_score_table(root)
    out = root / OUT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof": pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d %H:%M"),
        "rows": df.to_dict(orient="records"),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "n": len(df), "path": OUT_REL.as_posix(), "asof": payload["asof"]}


def build_tech_score_table(root: Path) -> pd.DataFrame:
    uni = load_universe(root) or {}
    report = load_l1_report(root) or {}
    sig_by = {
        str(s.get("code") or "").upper(): s
        for s in (report.get("signals") or [])
        if isinstance(s, dict)
    }
    rows = []
    for s in uni.get("symbols") or []:
        if not isinstance(s, dict):
            continue
        code = str(s.get("code") or "").upper()
        if not code:
            continue
        name = str(s.get("name") or "")
        bars, _ = load_local_bars(root, code)
        if not bars:
            # Fallback free sina continuous
            from market_data import load_free_bars

            bars, _ = load_free_bars(code)
        rows.append(_score_row(root, code, name, bars or [], sig_by.get(code)))
    return pd.DataFrame(rows)


def render_tech_score_panel(root: Path) -> None:
    st.subheader("技术分析打分表")
    st.caption(
        "表头：品种 / 移动平均 / 动量 / K线形态 / 重叠研究 / 枢轴点 / 基差 / 波动率 → 合并信号；"
        "五档：强烈看涨、看涨、震荡、看跌、强烈看跌（5/4/3/2/1）。"
        "K线形态=近20日结构（上升 / 下降 / 箱体震荡）；基差=近次月升贴水；波动率=HV20及分位。"
    )
    if st.button("重算技术评分", type="primary"):
        with st.spinner("读取本地日线/升贴水并打分…"):
            meta = write_tech_score_snapshot(root)
            st.success(f"已写入 {meta.get('path')} · {meta.get('n')} 品种")
            st.rerun()

    path = root / OUT_REL
    if not path.is_file():
        st.info("尚无评分快照。点「重算技术评分」生成。")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        st.error("tech_score_latest.json 无法解析")
        return
    st.caption(f"快照 {payload.get('asof')}")
    df = pd.DataFrame(payload.get("rows") or [])
    if df.empty:
        st.warning("快照为空")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        "合并信号五档：强烈看涨 / 看涨 / 震荡 / 看跌 / 强烈看跌。"
        "K线形态仅三档：上升、下降、箱体震荡（近20日高低点+斜率）；均线与动量为主。"
    )
