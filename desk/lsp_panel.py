# -*- coding: utf-8 -*-
"""LSP sweep research panel (multi-symbol; not a formal Path-A signal)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from desk.variety_labels import variety_label

_OUTCOME_ZH = {
    "fake_break_reversal": "假突破反转",
    "true_break_continuation": "真突破延续",
    "invalid_sweep": "无效扫荡",
}
_DIR_ZH = {"up": "向上刺穿", "down": "向下刺穿"}
_LEVEL_ZH = {
    "swing_high": "摆动高点",
    "swing_low": "摆动低点",
    "vwap": "VWAP",
    "vwap_high": "VWAP上沿",
    "vwap_low": "VWAP下沿",
}


def _lsp_dir(root: Path) -> Path:
    return root / "lab" / "research" / "lsp"


def _discover_symbols(root: Path) -> list[str]:
    found: set[str] = set()
    d = _lsp_dir(root)
    if not d.is_dir():
        return []
    for p in d.glob("lsp_*_*_latest.json"):
        m = re.match(r"lsp_([A-Z0-9]+)_(15m|60m)_latest\.json$", p.name, re.I)
        if m:
            found.add(m.group(1).upper())
    return sorted(found)


def _load(root: Path, symbol: str, timeframe: str = "15m") -> dict[str, Any]:
    path = _lsp_dir(root) / f"lsp_{symbol.upper()}_{timeframe}_latest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _peek_contract(root: Path, symbol: str) -> str | None:
    for tf in ("15m", "60m"):
        payload = _load(root, symbol, tf)
        c = str(payload.get("contract") or "").upper()
        if c:
            return c
    return None


def _direction_rows(payload: dict[str, Any], variety: str) -> list[dict[str, Any]]:
    stats = payload.get("stats") or {}
    detail = stats.get("by_direction_detail") or {}
    plain = stats.get("by_direction") or {}
    keys = sorted(set(detail) | set(plain), key=lambda x: {"up": 0, "down": 1}.get(x, 9))
    rows: list[dict[str, Any]] = []
    for key in keys:
        block = detail.get(key) or {}
        probs = block.get("probs") if block else plain.get(key) or {}
        counts = block.get("counts") or {}
        n = block.get("n")
        if n is None:
            tail = payload.get("events_tail") or []
            n_tail = sum(1 for e in tail if str(e.get("break_direction")) == key)
            n = f"~{n_tail}(尾部)" if n_tail else "—"
        rows.append(
            {
                "品种": variety,
                "刺穿方向": _DIR_ZH.get(key, key),
                "事件数": n,
                "假突破反转": probs.get("fake_break_reversal"),
                "真突破延续": probs.get("true_break_continuation"),
                "无效扫荡": probs.get("invalid_sweep"),
                "假突破次数": counts.get("fake_break_reversal"),
                "真突破次数": counts.get("true_break_continuation"),
                "无效次数": counts.get("invalid_sweep"),
            }
        )
    return rows


def render_lsp_panel(st, root: Path) -> None:
    st.caption(
        "流动性扫荡（LSP）为 **Research**：统计真假突破条件概率，"
        "**不会**改 Path-A 入场。品种标注=期号+中文名+板块。"
    )
    symbols = _discover_symbols(root)
    if not symbols:
        st.info(
            "尚无 LSP 产物。运行：\n"
            "`python lab/scripts/run_lsp_cf.py --symbols CF,P,RB,MA,TA --period both`"
        )
        return

    # Stable code→label map so selectbox shows clear variety text.
    choices: list[tuple[str, str]] = []
    for code in symbols:
        contract = _peek_contract(root, code)
        choices.append(
            (
                code,
                variety_label(root, code, contract=contract, with_bucket=True),
            )
        )
    label_by_code = {c: lab for c, lab in choices}
    pick_label = st.selectbox("品种", [lab for _, lab in choices], index=0)
    symbol = next(c for c, lab in choices if lab == pick_label)
    tf = st.selectbox("周期", ["15m", "60m"], index=0)
    payload = _load(root, symbol, tf)
    if not payload:
        st.info(
            f"尚无 `{label_by_code.get(symbol, symbol)} / {tf}` 产物。运行：\n"
            f"`python lab/scripts/run_lsp_cf.py --symbol {symbol} --period {tf[:-1]}`"
        )
        return

    code = str(payload.get("symbol") or symbol).upper()
    contract = str(payload.get("contract") or "") or None
    variety = variety_label(root, code, contract=contract, with_bucket=True)
    stats = payload.get("stats") or {}

    st.markdown(f"**当前品种：{variety}** · 周期 {tf} · 仅研究")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("事件数", payload.get("n_events") or stats.get("n_events"))
    c2.metric("假突破概率", (stats.get("outcome_probs") or {}).get("fake_break_reversal"))
    c3.metric("真突破概率", (stats.get("outcome_probs") or {}).get("true_break_continuation"))
    c4.metric("无效扫荡", (stats.get("outcome_probs") or {}).get("invalid_sweep"))
    st.caption(
        f"合约代码={contract or '—'} · 品种代码={code} · "
        f"均 MFE={stats.get('avg_mfe_atr')} ATR · 均 MAE={stats.get('avg_mae_atr')} ATR · "
        f"K线数={payload.get('n_bars')}"
    )

    dir_rows = _direction_rows(payload, variety)
    st.subheader("按刺穿方向")
    if dir_rows:
        st.dataframe(dir_rows, width="stretch", hide_index=True)
        st.caption("概率=该方向内条件频率；次数为全样本。")
    else:
        st.warning("方向分层为空：事件缺少 break_direction。")

    res = stats.get("resonance") or {}
    if res:
        st.subheader("15m↔60m 共振")
        st.dataframe(
            [
                {
                    "品种": variety,
                    "分层": "共振",
                    "事件数": res.get("n_resonant"),
                    "假突破反转": (res.get("resonant_outcome_probs") or {}).get(
                        "fake_break_reversal"
                    ),
                    "真突破延续": (res.get("resonant_outcome_probs") or {}).get(
                        "true_break_continuation"
                    ),
                    "无效扫荡": (res.get("resonant_outcome_probs") or {}).get("invalid_sweep"),
                },
                {
                    "品种": variety,
                    "分层": "非共振",
                    "事件数": res.get("n_non_resonant"),
                    "假突破反转": (res.get("non_resonant_outcome_probs") or {}).get(
                        "fake_break_reversal"
                    ),
                    "真突破延续": (res.get("non_resonant_outcome_probs") or {}).get(
                        "true_break_continuation"
                    ),
                    "无效扫荡": (res.get("non_resonant_outcome_probs") or {}).get(
                        "invalid_sweep"
                    ),
                },
            ],
            width="stretch",
            hide_index=True,
        )

    vol_rows = [
        {
            "品种": variety,
            "分层": "高量≥1.2",
            "事件数": (stats.get("high_volume_ge_1_2") or {}).get("n"),
            "假突破反转": ((stats.get("high_volume_ge_1_2") or {}).get("probs") or {}).get(
                "fake_break_reversal"
            ),
            "真突破延续": ((stats.get("high_volume_ge_1_2") or {}).get("probs") or {}).get(
                "true_break_continuation"
            ),
            "无效扫荡": ((stats.get("high_volume_ge_1_2") or {}).get("probs") or {}).get(
                "invalid_sweep"
            ),
        },
        {
            "品种": variety,
            "分层": "低量<1.2",
            "事件数": (stats.get("low_volume_lt_1_2") or {}).get("n"),
            "假突破反转": ((stats.get("low_volume_lt_1_2") or {}).get("probs") or {}).get(
                "fake_break_reversal"
            ),
            "真突破延续": ((stats.get("low_volume_lt_1_2") or {}).get("probs") or {}).get(
                "true_break_continuation"
            ),
            "无效扫荡": ((stats.get("low_volume_lt_1_2") or {}).get("probs") or {}).get(
                "invalid_sweep"
            ),
        },
    ]
    st.subheader("成交量分层")
    st.dataframe(vol_rows, width="stretch", hide_index=True)

    tail = payload.get("events_tail") or []
    if tail:
        st.subheader("最近事件")
        rows = []
        for e in reversed(tail[-30:]):
            ec = str(e.get("symbol") or code).upper()
            econtract = str(e.get("contract") or contract or "") or None
            rows.append(
                {
                    "品种": variety_label(root, ec, contract=econtract, with_bucket=True),
                    "时间": e.get("timestamp"),
                    "刺穿方向": _DIR_ZH.get(
                        str(e.get("break_direction") or ""), e.get("break_direction")
                    ),
                    "结果": _OUTCOME_ZH.get(str(e.get("outcome") or ""), e.get("outcome")),
                    "位型": _LEVEL_ZH.get(str(e.get("level_type") or ""), e.get("level_type")),
                    "突破ATR": e.get("break_size_atr"),
                    "量比": e.get("volume_ratio"),
                    "MFE": e.get("mfe"),
                    "MAE": e.get("mae"),
                    "收回根数": e.get("reclaim_bars"),
                    "HTF共振": "是" if e.get("htf_resonance") else "否",
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
