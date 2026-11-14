# -*- coding: utf-8 -*-
"""Shared variety / task / strategy display labels for desk research panels."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from desk.loaders import format_variety_label, load_universe

EX_ZH = {
    "CZCE": "郑商所",
    "DCE": "大商所",
    "SHFE": "上期所",
    "INE": "上期能源",
    "GFEX": "广期所",
    "CFFEX": "中金所",
}

P4_TASK_ZH = {
    "lsp_reversal": "LSP假突破反转",
    "trend_fail": "趋势失效",
    "breakout_continue": "突破延续",
}

STRATEGY_ZH = {
    "path_a": "路径A seats",
    "cwft": "本地代理·CWFT",
    "fn": "本地代理·前后月ST",
    "ls": "本地代理·多空CWFT",
    "st": "本地代理·SuperTrend",
}

FEATURE_ZH = {
    "atr": "ATR",
    "atr_pct": "ATR占比",
    "break_size_atr": "突破幅度(ATR)",
    "break_up": "向上突破",
    "distance_to_level": "距关键位",
    "hour": "小时",
    "htf_resonance": "高周期共振",
    "level_is_high": "是否高点位",
    "volume_ratio": "量比",
    "r20": "R20",
    "r60": "R60",
    "abs_r20": "|R20|",
    "abs_r60": "|R60|",
    "close": "收盘价",
    "ret_1d": "日收益",
}

BACKEND_ZH = {
    "lightgbm": "LightGBM",
    "histgbm": "HistGBM(sklearn)",
    "sklearn": "sklearn",
}

ERROR_ZH = {
    "insufficient_samples": "样本不足",
    "bad_split": "时序切分无效",
}

STRESS_ZH = {
    "uniform_-2pct": "等权全跌2%",
    "uniform_-5pct": "等权全跌5%",
    "first_leg_-8pct": "首腿跌8%",
}

GAMMA_LABEL_ZH = {
    "unchanged": "未迁移",
    "up": "上移",
    "down": "下移",
    "call": "看涨墙",
    "put": "看跌墙",
    "stay": "停留墙内",
    "pierce": "刺穿墙位",
    "bounce": "触及反弹",
    "iv_up_oi_up": "IV升·OI升",
    "iv_up_oi_down": "IV升·OI降",
    "iv_down_oi_up": "IV降·OI升",
    "iv_down_oi_down": "IV降·OI降",
}

QUALITY_BLOCK_ZH = {
    "data_invalid": "数据无效",
    "not_tradable": "不可交易",
    "limit_lock": "涨跌停锁",
    "thin_liquidity": "流动性不足",
    "near_delivery": "临近交割",
    "missing_contract": "缺合约价",
    "cost_stress_block": "压力成本拦截",
}


def _map_label(table: dict[str, str], key: Any) -> str:
    s = str(key or "")
    return table.get(s, table.get(s.lower(), s))


def universe_rows(root: Path) -> dict[str, dict[str, Any]]:
    uni = load_universe(root) or {}
    out: dict[str, dict[str, Any]] = {}
    for row in uni.get("symbols") or []:
        if isinstance(row, dict) and row.get("code"):
            out[str(row["code"]).upper()] = row
    return out


def variety_label(
    root: Path,
    code: str,
    *,
    name: str = "",
    contract: str | None = None,
    with_bucket: bool = True,
    with_exchange: bool = False,
) -> str:
    """``P2701 棕榈油 · 农产品`` — period + Chinese name + optional bucket/exchange."""
    code_u = str(code or "").upper()
    meta = universe_rows(root).get(code_u) or {}
    nm = str(name or meta.get("name") or "").strip()
    bucket = str(meta.get("bucket") or "").strip()
    exchange = str(meta.get("exchange") or "").strip()
    ex_zh = EX_ZH.get(exchange, exchange) if with_exchange else ""
    label = format_variety_label(
        code_u,
        nm,
        contract=contract,
        exchange_zh=ex_zh,
        root=root,
    )
    if with_bucket and bucket and bucket not in label:
        label = f"{label} · {bucket}"
    return label


def p4_task_label(task: str) -> str:
    return _map_label(P4_TASK_ZH, task)


def strategy_label(name: str) -> str:
    return _map_label(STRATEGY_ZH, name)


def feature_label(name: str) -> str:
    return _map_label(FEATURE_ZH, name)


def backend_label(name: str) -> str:
    return _map_label(BACKEND_ZH, name)


def error_label(name: str) -> str:
    return _map_label(ERROR_ZH, name)


def stress_label(name: str) -> str:
    return _map_label(STRESS_ZH, name)


def gamma_term_label(name: str) -> str:
    return _map_label(GAMMA_LABEL_ZH, name)


def quality_block_label(name: str) -> str:
    return _map_label(QUALITY_BLOCK_ZH, name)


def counts_zh(raw: dict[str, Any] | None, mapper) -> list[dict[str, Any]]:
    """Turn ``{en_key: n}`` into table rows with Chinese labels."""
    out = []
    for k, v in (raw or {}).items():
        out.append({"说明": mapper(k), "次数/概率": v, "原键": k})
    return out
