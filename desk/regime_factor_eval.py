# -*- coding: utf-8 -*-
"""HMM-regime multi-factor / portfolio / event-factor evaluation for the desk.

Foundation: 3-state Gaussian HMM labels mapped to 多 / 空 / 震荡.
On top of that we score price factors, seat/carry, score-weighted factor combos,
Path-A / benchmark portfolio equity slices, and event factors (with a concrete
「动量机构同向」stub plus an ``external/event_factors_latest.json`` extension point).

Paper research only — no invented KPIs; thin samples stay 「样本不足」.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from desk.loaders import (
    equity_curve_df,
    load_json,
    load_strategy_payload,
    load_universe,
    strategy_availability,
)
from desk.regime_board import (
    SMALL_MOVE,
    WINDOW,
    _attach_next,
    _carry_calls,
    _dir_name,
    _hmm_view,
    _num,
    _price_calls,
    _score_calls,
    events_for_codes,
    load_local_bars,
    seat_series,
)
from desk.scoreboard import scoreboard_rows
from desk.strategies.registry import REPO_ROOT, all_strategies

# HMM emission labels → research buckets used across the desk.
HMM_TO_BUCKET = {"偏多": "多", "偏空": "空", "震荡": "震荡", "多": "多", "空": "空"}
BUCKETS = ("多", "空", "震荡")
REGIME_MIN_N = 8  # per-bucket floor (samples split three ways)

# Event-factor registry: id → builder(root, code, bars, report) -> calls | None
EventFactorBuilder = Callable[[Path, str, list[dict], dict | None], list[dict] | None]
EVENT_FACTOR_BUILDERS: dict[str, EventFactorBuilder] = {}


def normalize_regime(label: Any) -> str | None:
    """Map HMM / desk labels to 多 / 空 / 震荡. Unknown → None."""
    text = str(label or "").strip()
    return HMM_TO_BUCKET.get(text)


def register_event_factor(factor_id: str, builder: EventFactorBuilder) -> None:
    """Extension point: plug additional event→signal builders into the eval."""
    EVENT_FACTOR_BUILDERS[str(factor_id)] = builder


def _signal_to_bucket(signal: int) -> str:
    return _dir_name(int(signal))


def _regime_map_from_hmm_calls(hmm_calls: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in hmm_calls:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        out[day] = _signal_to_bucket(int(row.get("signal") or 0))
    return out


def _score_window(window: list[dict], *, chop_hits: bool) -> dict[str, Any] | None:
    if len(window) < REGIME_MIN_N:
        return None
    hits = 0
    signed: list[float] = []
    for row in window:
        signal = int(row["signal"])
        nxt = float(row["next_ret"])
        if signal == 0:
            if chop_hits and abs(nxt) < SMALL_MOVE:
                hits += 1
            elif nxt == 0:
                hits += 1
        elif nxt != 0 and signal * nxt > 0:
            hits += 1
        if signal != 0 and nxt != 0:
            signed.append(signal * nxt * 100.0)
    hit = hits / len(window) * 100.0
    avg = sum(signed) / len(signed) if signed else 0.0
    score = hit + 5.0 * max(-2.0, min(2.0, avg))
    score = max(0.0, min(100.0, score))
    return {
        "命中率": round(hit, 1),
        "均收益": round(avg, 3),
        "评分": round(score, 1),
        "样本天数": len(window),
        "非平信号日": len(signed),
    }


def score_under_regimes(
    name: str,
    calls: list[dict],
    regime_by_date: dict[str, str],
    *,
    chop_hits: bool = False,
    active_only: bool = False,
) -> dict[str, Any]:
    """Overall + per-HMM-bucket scores. Thin buckets stay 样本不足.

    ``active_only`` (event factors): score only non-flat signal days so sparse
    events are not diluted by long stretches of 0.
    """
    latest = _dir_name(int(calls[-1]["signal"])) if calls else "样本不足"
    usable = [
        row
        for row in calls
        if row.get("next_ret") is not None and str(row.get("date") or "")[:10] in regime_by_date
    ]
    if active_only:
        usable = [row for row in usable if int(row.get("signal") or 0) != 0]
    overall_window = usable[-WINDOW:]
    overall = _score_window(overall_window, chop_hits=chop_hits)
    by_bucket: dict[str, Any] = {}
    for bucket in BUCKETS:
        subset = [
            row
            for row in usable
            if regime_by_date.get(str(row.get("date") or "")[:10]) == bucket
        ]
        window = subset[-WINDOW:]
        packed = _score_window(window, chop_hits=chop_hits)
        if packed is None:
            by_bucket[bucket] = {
                "命中率": "样本不足",
                "均收益": "样本不足",
                "评分": "样本不足",
                "样本天数": len(window),
                "非平信号日": 0,
            }
        else:
            by_bucket[bucket] = packed
    best_bucket = None
    best_score = None
    for bucket, pack in by_bucket.items():
        sc = pack.get("评分")
        if isinstance(sc, (int, float)):
            if best_score is None or float(sc) > best_score:
                best_score = float(sc)
                best_bucket = bucket
    blank = {
        "命中率": "样本不足",
        "均收益": "样本不足",
        "评分": "样本不足",
        "样本天数": len(overall_window),
        "非平信号日": 0,
    }
    return {
        "因子": name,
        "最新方向": latest,
        "总体": overall if overall is not None else blank,
        "分态": by_bucket,
        "优势状态": best_bucket or "样本不足",
        "计分口径": "仅非平信号日" if active_only else "全窗口",
    }


def _align_combo(
    factor_series: list[tuple[str, list[dict], float]],
) -> list[dict]:
    """Score-weighted sign vote across factors that share a date."""
    by_date: dict[str, list[tuple[int, float]]] = {}
    next_ret: dict[str, float | None] = {}
    for _name, calls, weight in factor_series:
        w = float(weight)
        if w <= 0:
            continue
        for row in calls:
            day = str(row.get("date") or "")[:10]
            if not day:
                continue
            by_date.setdefault(day, []).append((int(row.get("signal") or 0), w))
            if day not in next_ret:
                nxt = row.get("next_ret")
                next_ret[day] = float(nxt) if nxt is not None else None
    out: list[dict] = []
    for day in sorted(by_date):
        votes = {"多": 0.0, "空": 0.0, "震荡": 0.0}
        for signal, w in by_date[day]:
            votes[_signal_to_bucket(signal)] += w
        top = max(votes.values())
        winners = [k for k, v in votes.items() if abs(v - top) < 1e-9]
        if len(winners) != 1 or winners[0] == "震荡":
            sig = 0
        elif winners[0] == "多":
            sig = 1
        else:
            sig = -1
        out.append({"date": day, "signal": sig, "next_ret": next_ret.get(day)})
    return out


def _event_support_to_signal(support: Any) -> int | None:
    text = str(support or "").strip()
    mapped = normalize_regime(text) or (
        "多" if text in ("偏多",) else "空" if text in ("偏空",) else text if text in BUCKETS else None
    )
    if mapped == "多":
        return 1
    if mapped == "空":
        return -1
    if mapped == "震荡":
        return 0
    return None


def build_joint_momentum_event_factor(
    root: Path, code: str, bars: list[dict], report: dict | None
) -> list[dict] | None:
    """Concrete event-factor stub: 动量机构同向 → sparse signed series.

    Days without the event stay flat (0). Soft-fails to None when no events.
    """
    code = str(code or "").upper()
    events = events_for_codes(root, report, [code])
    joint = [ev for ev in events if ev.get("类型") == "动量机构同向" and str(ev.get("代码") or "").upper() == code]
    if not joint or not bars:
        return None
    by_day: dict[str, int] = {}
    for ev in joint:
        day = str(ev.get("日期") or "")[:10]
        sig = _event_support_to_signal(ev.get("支持"))
        if not day or sig is None:
            continue
        # Same-day conflicts cancel to flat rather than inventing a winner.
        if day in by_day and by_day[day] != sig:
            by_day[day] = 0
        else:
            by_day[day] = sig
    if not by_day:
        return None
    calls = []
    for bar in bars:
        day = bar["date"]
        calls.append({"date": day, "signal": int(by_day.get(day, 0)), "next_ret": None})
    return _attach_next(calls, bars)


def build_external_event_factors(
    root: Path, code: str, bars: list[dict], report: dict | None
) -> list[tuple[str, list[dict]]]:
    """Extension point: optional ``external/event_factors_latest.json``.

    Schema (any missing piece soft-fails silently)::

        {
          "asof": "YYYYMMDD",
          "factors": [
            {
              "id": "custom_roll",
              "name": "自定义展期事件",
              "code": "RB",          # optional filter; omit = all codes
              "series": [{"date": "2026-01-02", "signal": 1}]
            }
          ]
        }

    ``signal`` ∈ {-1,0,1}. Unknown codes / empty series are skipped.
    """
    _ = report
    payload = load_json(root / "external" / "event_factors_latest.json") or {}
    factors = payload.get("factors")
    if not isinstance(factors, list) or not bars:
        return []
    code_u = str(code or "").upper()
    out: list[tuple[str, list[dict]]] = []
    for item in factors:
        if not isinstance(item, dict):
            continue
        want = str(item.get("code") or "").upper()
        if want and want != code_u:
            continue
        series = item.get("series")
        if not isinstance(series, list) or not series:
            continue
        by_day: dict[str, int] = {}
        for row in series:
            if not isinstance(row, dict):
                continue
            day = str(row.get("date") or "")[:10]
            try:
                sig = int(row.get("signal"))
            except (TypeError, ValueError):
                continue
            if not day or sig not in (-1, 0, 1):
                continue
            by_day[day] = sig
        if not by_day:
            continue
        name = str(item.get("name") or item.get("id") or "外部事件因子")
        calls = [{"date": bar["date"], "signal": int(by_day.get(bar["date"], 0)), "next_ret": None} for bar in bars]
        out.append((f"事件·{name}", _attach_next(calls, bars)))
    return out


register_event_factor("joint_momentum", build_joint_momentum_event_factor)


def _collect_price_factors(
    root: Path,
    code: str,
    bars: list[dict],
    hmm_calls: list[dict],
    *,
    r20_min: float,
    r60_min: float,
    report: dict | None,
) -> list[tuple[str, list[dict], bool, bool]]:
    """Return (name, calls, chop_hits, active_only) for core + event factors."""
    rows: list[tuple[str, list[dict], bool, bool]] = []
    if len(bars) >= 80:
        momentum, revert, breakout = _price_calls(bars, r20_min=r20_min, r60_min=r60_min)
        rows.append(("动量20/60", momentum, False, False))
        rows.append(("震荡均值回归", revert, True, False))
        if hmm_calls:
            rows.append(("HMM三状态", hmm_calls, False, False))
        rows.append(("波动突破", breakout, False, False))
    seats = seat_series(root, code, report)
    if seats:
        rows.append(("席位资金", _attach_next(seats, bars), False, False))
    carry = _carry_calls(root, code, bars)
    if carry is not None:
        rows.append(("升贴水", carry, False, False))

    # Registered event-factor builders (soft-fail individually).
    for fid, builder in list(EVENT_FACTOR_BUILDERS.items()):
        try:
            calls = builder(root, code, bars, report)
        except Exception:
            calls = None
        if calls:
            label = "事件·动量机构同向" if fid == "joint_momentum" else f"事件·{fid}"
            rows.append((label, calls, False, True))
    for name, calls in build_external_event_factors(root, code, bars, report):
        rows.append((name, calls, False, True))
    return rows


def _portfolio_regime_kpis(
    root: Path,
    code: str,
    regime_by_date: dict[str, str],
) -> list[dict[str, Any]]:
    """Slice Path-A / registered strategy equity by primary-symbol HMM regime.

    A day counts only when the equity point lists ``code`` in ``codes``/held.
    Metrics are computed from observed daily equity changes — never fabricated.
    """
    code = str(code or "").upper()
    out: list[dict[str, Any]] = []
    for spec in all_strategies(root):
        avail = strategy_availability(spec, root)
        if avail not in ("ready", "kpi_only"):
            continue
        payload = load_strategy_payload(spec, root) or {}
        if payload.get("_desk_missing"):
            continue
        df = equity_curve_df(payload)
        if df.empty or "equity" not in df.columns:
            # KPI-only: cannot regime-slice without a curve.
            continue
        df = df.dropna(subset=["equity"]).copy()
        if len(df) < 5:
            continue
        # Optional per-day held codes from curve points.
        raw_curve = payload.get("equity_curve") or []
        held_by_day: dict[str, set[str]] = {}
        for row in raw_curve:
            if not isinstance(row, dict):
                continue
            day = str(row.get("date") or "")[:10]
            codes = row.get("codes")
            if day and isinstance(codes, list):
                held_by_day[day] = {str(c).upper() for c in codes if c}

        df["day"] = df["date"].dt.strftime("%Y-%m-%d")
        df["ret"] = df["equity"].pct_change()
        bucket_rets: dict[str, list[float]] = {b: [] for b in BUCKETS}
        used = 0
        for _, row in df.iterrows():
            day = str(row["day"])
            ret = row["ret"]
            if ret != ret:  # NaN
                continue
            regime = regime_by_date.get(day)
            if regime not in bucket_rets:
                continue
            held = held_by_day.get(day)
            if held is not None and code not in held:
                continue
            # If curve has no codes field, attribute whole portfolio day to symbol regime
            # only for Path-A primary track; still honest about sample meaning in UI.
            bucket_rets[regime].append(float(ret))
            used += 1
        if used < REGIME_MIN_N:
            out.append(
                {
                    "策略": spec.name,
                    "id": spec.id,
                    "状态": "样本不足",
                    "计入日": used,
                    "多均收益%": None,
                    "空均收益%": None,
                    "震荡均收益%": None,
                    "多天数": len(bucket_rets["多"]),
                    "空天数": len(bucket_rets["空"]),
                    "震荡天数": len(bucket_rets["震荡"]),
                }
            )
            continue

        def _mean_pct(vals: list[float]) -> float | None:
            if len(vals) < REGIME_MIN_N:
                return None
            return round(sum(vals) / len(vals) * 100.0, 3)

        out.append(
            {
                "策略": spec.name,
                "id": spec.id,
                "状态": "已切片",
                "计入日": used,
                "多均收益%": _mean_pct(bucket_rets["多"]),
                "空均收益%": _mean_pct(bucket_rets["空"]),
                "震荡均收益%": _mean_pct(bucket_rets["震荡"]),
                "多天数": len(bucket_rets["多"]),
                "空天数": len(bucket_rets["空"]),
                "震荡天数": len(bucket_rets["震荡"]),
            }
        )
    return out


def _build_regime_factor_assessment_uncached(
    root: Path,
    code: str,
    report: dict | None,
) -> dict[str, Any]:
    """Full HMM-conditional multi-factor + combo + portfolio + event pack."""
    root = root or REPO_ROOT
    code = str(code or "").upper()
    report = report if report is not None else load_json(root / "l1_report.json")
    uni = load_universe(root) or {}
    r20_min = _num(uni.get("min_r20_pct")) or _num((report or {}).get("min_r20_pct")) or 3.0
    r60_min = _num(uni.get("min_r60_pct")) or _num((report or {}).get("min_r60_pct")) or 5.0

    bars, source = load_local_bars(root, code)
    hmm, hmm_calls = _hmm_view(bars)
    regime_by_date = _regime_map_from_hmm_calls(hmm_calls)

    notes: list[str] = []
    if not hmm.get("ok"):
        notes.append(f"HMM 未拟合：{hmm.get('reason') or '无足够日线'}。分态评估不可用。")
        return {
            "code": code,
            "ok": False,
            "hmm": hmm,
            "source": source,
            "bars": len(bars),
            "factors": [],
            "combos": [],
            "portfolio": [],
            "regime_counts": {},
            "notes": notes,
            "event_factor_ids": list(EVENT_FACTOR_BUILDERS),
        }

    factors_raw = _collect_price_factors(
        root,
        code,
        bars,
        hmm_calls,
        r20_min=float(r20_min),
        r60_min=float(r60_min),
        report=report,
    )
    factor_rows = [
        score_under_regimes(
            name, calls, regime_by_date, chop_hits=chop, active_only=active
        )
        for name, calls, chop, active in factors_raw
    ]

    # Combo strategies on factor votes.
    weight_pairs: list[tuple[str, list[dict], float]] = []
    equal_pairs: list[tuple[str, list[dict], float]] = []
    for name, calls, _chop, active in factors_raw:
        if name.startswith("事件·"):
            # Event factors stay in the multi-factor table; combo uses core factors
            # plus event stubs as equal members when they have enough active days.
            n_active = sum(1 for r in calls if int(r.get("signal") or 0) != 0)
            if n_active < REGIME_MIN_N:
                continue
        overall = _score_calls(name, calls, chop_hits=False)
        sc = overall.get("评分")
        w = float(sc) if isinstance(sc, (int, float)) else 1.0
        weight_pairs.append((name, calls, w))
        equal_pairs.append((name, calls, 1.0))
        _ = active

    combos: list[dict[str, Any]] = []
    if equal_pairs:
        eq_calls = _align_combo(equal_pairs)
        combos.append(
            score_under_regimes("组合·等权因子投票", eq_calls, regime_by_date, chop_hits=False)
        )
    if weight_pairs:
        wt_calls = _align_combo(weight_pairs)
        combos.append(
            score_under_regimes("组合·评分加权投票", wt_calls, regime_by_date, chop_hits=False)
        )

    # Desk strategy library mean score as a soft portfolio context (no fake returns).
    lib = scoreboard_rows(root)
    lib_scored = [r for r in lib if isinstance(r.get("评分"), (int, float))]
    port_slices = _portfolio_regime_kpis(root, code, regime_by_date)

    counts = {b: 0 for b in BUCKETS}
    for label in regime_by_date.values():
        if label in counts:
            counts[label] += 1

    event_names = [r["因子"] for r in factor_rows if str(r.get("因子") or "").startswith("事件·")]
    if not event_names:
        notes.append(
            "事件因子：本地无「动量机构同向」可对齐序列，且未提供 "
            "external/event_factors_latest.json；分态表不含事件行。"
        )
    else:
        notes.append("事件因子已并入：" + "、".join(event_names) + "。")

    return {
        "code": code,
        "ok": True,
        "hmm": {
            "latest": normalize_regime(hmm.get("latest")) or hmm.get("latest"),
            "proba": hmm.get("proba") or {},
            "asof": hmm.get("asof"),
            "backend": hmm.get("backend"),
        },
        "source": source,
        "bars": len(bars),
        "factors": factor_rows,
        "combos": combos,
        "portfolio": port_slices,
        "library_n": len(lib_scored),
        "library_mean": (
            round(sum(float(r["评分"]) for r in lib_scored) / len(lib_scored), 1)
            if lib_scored
            else None
        ),
        "regime_counts": counts,
        "notes": notes,
        "event_factor_ids": list(EVENT_FACTOR_BUILDERS),
    }


@st.cache_data(show_spinner=False)
def _cached_regime_factor_assessment(root_s: str, code: str) -> dict[str, Any]:
    root = Path(root_s)
    report = load_json(root / "l1_report.json")
    return _build_regime_factor_assessment_uncached(root, code, report)


def build_regime_factor_assessment(
    root: Path,
    code: str,
    *,
    report: dict | None = None,
) -> dict[str, Any]:
    """Public entry; Streamlit-cached when report is the on-disk l1 (or omitted)."""
    root = Path(root)
    code = str(code or "").upper()
    if report is None:
        return _cached_regime_factor_assessment(str(root), code)
    # Caller supplied an in-memory report — do not use the disk cache key.
    return _build_regime_factor_assessment_uncached(root, code, report)


def _flatten_factor_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    out = []
    for row in rows:
        overall = row.get("总体") or {}
        item = {
            "因子": row.get("因子"),
            "最新": row.get("最新方向"),
            "优势状态": row.get("优势状态"),
            "计分口径": row.get("计分口径") or "全窗口",
            "总评分": overall.get("评分"),
            "总命中%": overall.get("命中率"),
            "总均收益": overall.get("均收益"),
            "总样本": overall.get("样本天数"),
        }
        for bucket in BUCKETS:
            pack = (row.get("分态") or {}).get(bucket) or {}
            item[f"{bucket}评分"] = pack.get("评分")
            item[f"{bucket}命中%"] = pack.get("命中率")
            item[f"{bucket}均收益"] = pack.get("均收益")
            item[f"{bucket}样本"] = pack.get("样本天数")
        out.append(item)
    return pd.DataFrame(out)


def render_regime_factor_panel(root: Path, code: str, *, report: dict | None = None) -> None:
    """Streamlit block: HMM → 多/空/震荡 multi-factor + combo + event eval."""
    st.markdown("**HMM 多因子 · 组合 · 事件评估**")
    st.caption(
        "以三状态 HMM（偏多/偏空/震荡 → 多/空/震荡）为底座，"
        "对动量、均值回归、突破、席位、升贴水及事件因子做分态命中评估；"
        "并给出等权/评分加权因子组合，以及对 Path-A 等策略净值按持仓日的分态切片。"
        "样本不足不补造。研究用，非下单指令。"
    )
    with st.spinner("按 HMM 状态评估多因子与组合..."):
        pack = build_regime_factor_assessment(root, code, report=report)

    if not pack.get("ok"):
        for note in pack.get("notes") or []:
            st.info(note)
        return

    hmm = pack.get("hmm") or {}
    counts = pack.get("regime_counts") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("HMM 映射", str(hmm.get("latest") or "—"))
    c2.metric("多日数", int(counts.get("多") or 0))
    c3.metric("空日数", int(counts.get("空") or 0))
    c4.metric("震荡日数", int(counts.get("震荡") or 0))
    st.caption(
        f"状态日 {hmm.get('asof') or '—'} · 日线 {pack.get('bars')} · "
        f"{pack.get('source') or '—'} · 分态最少 {REGIME_MIN_N} 日才出评分"
    )

    factors = pack.get("factors") or []
    if factors:
        st.markdown("**多因子分态表**")
        frame = _flatten_factor_table(factors)
        st.dataframe(frame, width="stretch", hide_index=True)
    else:
        st.info("没有可评估的因子序列。")

    combos = pack.get("combos") or []
    if combos:
        st.markdown("**因子组合策略**")
        st.dataframe(_flatten_factor_table(combos), width="stretch", hide_index=True)

    port = pack.get("portfolio") or []
    st.markdown("**组合/策略净值 · HMM 分态切片**")
    st.caption(
        "仅当权益曲线按日含 equity：有 codes 字段时只计当日持仓含当前品种的日子；"
        "无 codes 时按品种 HMM 日历对整条组合净值切片（代理曲线常见）。"
        "均收益% = 该状态下日权益变化均值×100；天数不足标为空。"
        f"策略库有评分 {pack.get('library_n') or 0} 条"
        + (
            f"，均分 {pack.get('library_mean')}"
            if pack.get("library_mean") is not None
            else ""
        )
        + "。"
    )
    if port:
        st.dataframe(pd.DataFrame(port), width="stretch", hide_index=True)
    else:
        st.info("没有可按日切片的策略权益曲线（或缺 codes 对齐）。")

    with st.expander("事件因子扩展点", expanded=False):
        st.markdown(
            "- **已接线 stub**：`事件·动量机构同向`（来自状态评分页同一套 `events_for_codes`）。\n"
            "- **注册表**：`desk.regime_factor_eval.register_event_factor(id, builder)`。\n"
            "- **外部 JSON**：`external/event_factors_latest.json`，"
            "字段 `factors[].id/name/code?/series[{date,signal}]`，`signal∈{-1,0,1}`。\n"
            f"- 当前已注册 builder：`{', '.join(pack.get('event_factor_ids') or []) or '无'}`。"
        )
        ext = root / "external" / "event_factors_latest.json"
        if ext.is_file():
            st.caption(f"已检测到 {ext.relative_to(root)}。")
        else:
            st.caption("尚未放置 external/event_factors_latest.json（可选）。")

    for note in pack.get("notes") or []:
        st.caption(note)
    st.caption("研究观察，不构成交易建议。")
