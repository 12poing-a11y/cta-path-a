# -*- coding: utf-8 -*-
"""Unified strategy scoreboard for Path-A + external/proxy tracks.

Score is a 0–100 research index from reported/backtested risk metrics.
It is not a live trading signal and does not invent missing returns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from desk.loaders import load_json, strategy_availability, strategy_kpis
from desk.strategies.registry import REPO_ROOT, all_strategies

# Weights for the composite desk score (sum = 1).
_W_SHARPE = 0.35
_W_CALMAR = 0.25
_W_RET = 0.25
_W_DD = 0.15


def _num(value: Any) -> float | None:
    if value is None or value is False:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def composite_score(
    *,
    sharpe: float | None = None,
    calmar: float | None = None,
    ret_ann_pct: float | None = None,
    max_dd_pct: float | None = None,
) -> float | None:
    """Map risk metrics → 0–100. Missing inputs dilute their weight."""
    parts: list[tuple[float, float]] = []
    if sharpe is not None:
        parts.append((_W_SHARPE, _clip(sharpe / 2.5 * 100.0)))
    if calmar is not None:
        parts.append((_W_CALMAR, _clip(calmar / 2.5 * 100.0)))
    if ret_ann_pct is not None:
        parts.append((_W_RET, _clip(ret_ann_pct / 20.0 * 100.0)))
    if max_dd_pct is not None and max_dd_pct > 0:
        # Smaller drawdown → higher score; 5% dd ≈ 80, 20% dd ≈ 20.
        parts.append((_W_DD, _clip(100.0 - max_dd_pct * 4.0)))
    if not parts:
        return None
    wsum = sum(w for w, _ in parts)
    if wsum <= 0:
        return None
    return round(sum(w * v for w, v in parts) / wsum, 1)


def _kpis_enriched(spec_id: str, kpis: dict[str, Any], payload: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(kpis)
    raw = payload or {}
    for key in (
        "sharpe",
        "calmar",
        "ret_ann_pct",
        "week_ret_pct",
        "ytd_ret_pct",
        "family",
        "track_source",
        "proxy_of",
    ):
        if key in raw and raw[key] is not None and key not in out:
            out[key] = raw[key]
    for key in ("trade_win_rate", "win_rate", "breakeven_win_rate", "expectancy_r", "closed_trades"):
        if key in raw and raw[key] is not None and key not in out:
            out[key] = raw[key]
    # Path-A style: annualize roughly from window ret if no ret_ann_pct.
    if out.get("ret_ann_pct") is None and out.get("ret_pct") is not None:
        out["ret_ann_pct"] = out.get("ret_pct")
    if out.get("calmar") is None:
        ret = _num(out.get("ret_ann_pct") or out.get("ret_pct"))
        dd = _num(out.get("max_dd_pct"))
        if ret is not None and dd and dd > 0:
            out["calmar"] = round(ret / dd, 3)
    if out.get("sharpe") is None and raw.get("sharpe") is not None:
        out["sharpe"] = raw.get("sharpe")
    return out


def _kind_label(spec_id: str, tags: list[str], avail: str) -> str:
    tagset = set(tags or [])
    if "proxy" in tagset or spec_id.startswith("proxy_"):
        return "本地代理"
    if "external" in tagset or spec_id.startswith("dzqh_"):
        return "外部跟踪"
    if avail == "ready":
        return "本地曲线"
    if avail == "kpi_only":
        return "KPI跟踪"
    if avail == "placeholder":
        return "占位"
    return "其他"


def _status_zh(avail: str) -> str:
    return {
        "ready": "有曲线",
        "kpi_only": "KPI跟踪",
        "placeholder": "占位待填",
        "missing": "缺文件",
    }.get(avail, avail)


def _up_day_pct(payload: dict[str, Any] | None) -> float | None:
    """Share of sessions where equity rose. From the curve only; not a trade win rate."""
    curve = (payload or {}).get("equity_curve") or []
    eqs: list[float] = []
    for row in curve:
        if not isinstance(row, dict):
            continue
        v = _num(row.get("equity"))
        if v is not None:
            eqs.append(v)
    if len(eqs) < 5:
        return None
    ups = sum(1 for a, b in zip(eqs, eqs[1:]) if b > a)
    return round(ups / (len(eqs) - 1) * 100.0, 1)


def conviction_label(
    score: float | None,
    sharpe: float | None,
    trade_wr: float | None,
    calmar: float | None,
) -> str | None:
    """高/中/低 from score plus risk and historical win rate. No invented rates."""
    if score is None:
        return None
    votes = 0
    if score >= 65:
        votes += 1
    if sharpe is not None and sharpe >= 1.4:
        votes += 1
    if trade_wr is not None and trade_wr >= 45:
        votes += 1
    if calmar is not None and calmar >= 1.2:
        votes += 1
    if votes >= 3:
        return "高"
    if votes >= 1 or score >= 50:
        return "中"
    return "低"


def scoreboard_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Strategies that actually have a numeric score. Placeholders are omitted.

    Paste-only / unstable tracks (e.g. 东证周报) are excluded from the desk;
    their files remain under ``external/archive`` for later validation.
    """
    root = root or REPO_ROOT
    rows: list[dict[str, Any]] = []
    for spec in all_strategies(root):
        if spec.placeholder:
            continue
        tags = set(spec.tags or [])
        if "validation_archive" in tags or "unstable_source" in tags:
            continue
        if str(spec.id).startswith("dzqh_"):
            continue
        avail = strategy_availability(spec, root)
        if avail in ("missing", "placeholder"):
            continue
        from desk.loaders import load_strategy_payload

        payload = load_strategy_payload(spec, root) or {}
        if payload.get("_desk_missing") or payload.get("placeholder"):
            continue
        kpis = _kpis_enriched(spec.id, strategy_kpis(spec, root), payload)
        sharpe = _num(kpis.get("sharpe"))
        calmar = _num(kpis.get("calmar"))
        ret_ann = _num(kpis.get("ret_ann_pct") if kpis.get("ret_ann_pct") is not None else kpis.get("ret_pct"))
        dd = _num(kpis.get("max_dd_pct"))
        trade_wr = _num(kpis.get("trade_win_rate"))
        dir_wr = _num(kpis.get("win_rate"))
        be_wr = _num(kpis.get("breakeven_win_rate"))
        up_pct = _up_day_pct(payload)
        score = composite_score(
            sharpe=sharpe,
            calmar=calmar,
            ret_ann_pct=ret_ann,
            max_dd_pct=dd,
        )
        if score is None:
            continue
        grasp = conviction_label(score, sharpe, trade_wr, calmar)
        rows.append(
            {
                "策略": spec.name,
                "id": spec.id,
                "类型": _kind_label(spec.id, spec.tags, avail),
                "状态": _status_zh(avail),
                "评分": score,
                "把握": grasp,
                "交易胜率%": trade_wr,
                "方向胜率%": dir_wr,
                "盈亏平衡胜率%": be_wr,
                "上涨日占比%": up_pct,
                "年化%": ret_ann,
                "夏普": sharpe,
                "Calmar": calmar,
                "最大回撤%": dd,
                "近一周%": _num(kpis.get("week_ret_pct")),
                "今年以来%": _num(kpis.get("ytd_ret_pct")),
                "平仓笔数": _num(kpis.get("closed_trades")),
                "来源": kpis.get("track_source") or kpis.get("source") or "",
            }
        )
    rows.sort(
        key=lambda r: (
            {"高": 0, "中": 1, "低": 2}.get(str(r.get("把握") or ""), 3),
            -(float(r["评分"]) if isinstance(r.get("评分"), (int, float)) else 0.0),
        )
    )
    return rows


def load_dzqh_catalog(root: Path | None = None) -> dict[str, Any] | None:
    root = root or REPO_ROOT
    return load_json(root / "external" / "dzqh_weekly_latest.json")
