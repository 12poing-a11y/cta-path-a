# -*- coding: utf-8 -*-
"""Blended holdings reference from A capital weights × sleeve books (paper only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from desk.loaders import format_variety_label, load_universe
from desk.proxy_positions import _num

BLEND_REL = Path("data") / "ablation" / "strategy_blend_latest.json"


def _code_name_map(root: Path | None) -> dict[str, str]:
    if root is None:
        return {}
    uni = load_universe(root) or {}
    out: dict[str, str] = {}
    for s in uni.get("symbols") or []:
        if isinstance(s, dict) and s.get("code"):
            out[str(s["code"]).upper()] = str(s.get("name") or "")
    return out


def _variety_label(
    code: Any,
    name: Any = "",
    *,
    root: Path | None = None,
    names: dict[str, str] | None = None,
) -> str:
    c = str(code or "").upper()
    n = str(name or "").strip() or (names or {}).get(c, "")
    return format_variety_label(c, n, root=root)
OBSERVE_ID = "proxy_observe_f_short_mom"
OBSERVE_CAP = 0.10

DISCLAIMER = (
    "持仓参考 · 纸面拼表：按最优 Calmar 组合的资金权重缩放各袖套账面手数/名义；"
    "参考手数不足 1 手按 1 手取值；非实盘、不改 paper_book；代理手数为理论 lots_equiv。"
)


def floor_lots_one(lots: float) -> float:
    """Positive fractional lots below 1 lot → 1 (desk参考手数)."""
    try:
        x = float(lots)
    except (TypeError, ValueError):
        return lots  # type: ignore[return-value]
    if x <= 0:
        return x
    if x < 1.0:
        return 1.0
    return round(x, 4)

_DIR_ZH = {
    "long": "多",
    "short": "空",
    "多": "多",
    "空": "空",
}

_SLEEVE_NAME = {
    "path_a": "路径A",
    "proxy_cwft": "本地代理·CWFT",
    "proxy_long_short_cwft": "本地代理·Long/Short CWFT",
    "proxy_frontnext_st": "本地代理·C_frontnext&ShortTrend",
    OBSERVE_ID: "观察袖套·F+短动量",
}


def _dir_zh(raw: Any) -> str | None:
    s = str(raw or "").strip()
    return _DIR_ZH.get(s) or _DIR_ZH.get(s.lower())


def load_best_blend_weights(root: Path) -> dict[str, Any] | None:
    """Return ``{blend_id, label, weights, calmar, ...}`` from blend artifact."""
    path = Path(root) / BLEND_REL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    best = (data.get("best_by_calmar") or data.get("best_by_ret") or [])
    if not best:
        # fall back to first ok row
        for r in data.get("rows") or []:
            if r.get("ok") and isinstance(r.get("weights"), dict):
                return {
                    "blend_id": r.get("blend_id"),
                    "label": r.get("label"),
                    "weights": {str(k): float(v) for k, v in r["weights"].items()},
                    "weights_zh": r.get("weights_zh"),
                    "ret_pct": r.get("ret_pct"),
                    "max_dd_pct": r.get("max_dd_pct"),
                    "calmar": r.get("calmar"),
                    "source": "rows",
                }
        return None
    top = best[0]
    # weights live on full rows
    weights = None
    for r in data.get("rows") or []:
        if r.get("blend_id") == top.get("blend_id") and isinstance(r.get("weights"), dict):
            weights = {str(k): float(v) for k, v in r["weights"].items()}
            break
    if not weights:
        return None
    obs = float(weights.get(OBSERVE_ID) or 0.0)
    if obs > OBSERVE_CAP + 1e-12:
        return None
    return {
        "blend_id": top.get("blend_id"),
        "label": top.get("label") or top.get("weights_zh"),
        "weights": weights,
        "weights_zh": top.get("weights_zh"),
        "ret_pct": top.get("ret_pct"),
        "max_dd_pct": top.get("max_dd_pct"),
        "calmar": top.get("calmar"),
        "source": "best_by_calmar",
        "blend_asof": data.get("asof"),
    }


def _path_a_legs(root: Path) -> tuple[list[dict[str, Any]], str, str]:
    """Legs from paper book (prefer) / backtest final_positions."""
    from desk.decision import load_paper_book

    paper = load_paper_book(root)
    asof = str(paper.get("asof") or paper.get("end") or paper.get("asof_ymd") or "")
    source = str(paper.get("source") or "paper_book")
    legs: list[dict[str, Any]] = []
    positions = paper.get("positions") or {}
    if not isinstance(positions, dict):
        return legs, asof, source
    for code, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        d = _dir_zh(pos.get("direction"))
        lots = _num(pos.get("lots"), 4)
        if not d or lots is None or float(lots) <= 0:
            continue
        c = str(pos.get("code") or code or "").upper()
        mark = pos.get("mark") or pos.get("entry")
        mult = pos.get("mult")
        notional = None
        try:
            if mark is not None and mult is not None and lots is not None:
                notional = float(lots) * float(mark) * float(mult)
        except (TypeError, ValueError):
            notional = None
        legs.append(
            {
                "code": c,
                "name": pos.get("name") or "",
                "direction": d,
                "lots": float(lots),
                "notional_yuan": notional,
                "entry_date": pos.get("entry_date"),
                "entry_price": pos.get("entry") or pos.get("entry_price"),
                "last_price": mark,
            }
        )
    return legs, asof, source


def _proxy_legs(root: Path, sid: str) -> tuple[list[dict[str, Any]], str]:
    path = Path(root) / "external" / "strategies" / f"{sid}.json"
    if not path.is_file():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], ""
    asof = str(data.get("positions_asof") or data.get("end") or "")
    raw = data.get("final_positions")
    if not isinstance(raw, list):
        return [], asof
    legs: list[dict[str, Any]] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        d = _dir_zh(p.get("direction"))
        lots = _num(p.get("lots_equiv"), 4)
        if lots is None:
            lots = _num(p.get("lots"), 4)
        if not d or lots is None or float(lots) <= 0:
            continue
        legs.append(
            {
                "code": str(p.get("code") or "").upper(),
                "name": p.get("name") or "",
                "direction": d,
                "lots": float(lots),
                "notional_yuan": _num(p.get("notional_yuan"), 0),
                "entry_date": p.get("entry_date"),
                "entry_price": p.get("entry_price"),
                "last_price": p.get("last_price"),
            }
        )
    return legs, asof


def build_blend_holdings(
    root: Path,
    *,
    weights: dict[str, float] | None = None,
    blend_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scale each sleeve book by capital weight; aggregate by 品种+方向."""
    meta = blend_meta
    if weights is None:
        meta = load_best_blend_weights(root)
        if not meta:
            return {
                "ok": False,
                "note": f"缺少可用组合权重，请先跑 python scripts/strategy_blend_grid.py → {BLEND_REL.as_posix()}",
                "legs": [],
                "rows": [],
            }
        weights = meta["weights"]
    assert weights is not None
    names = _code_name_map(root)
    scaled: list[dict[str, Any]] = []
    sleeve_asof: dict[str, str] = {}
    for sid, w in weights.items():
        w = float(w)
        if w <= 0:
            continue
        if sid == "path_a":
            legs, asof, src = _path_a_legs(root)
            sleeve_asof[sid] = asof
            sleeve_label = _SLEEVE_NAME.get(sid, sid)
            book_src = src
        else:
            legs, asof = _proxy_legs(root, sid)
            sleeve_asof[sid] = asof
            sleeve_label = _SLEEVE_NAME.get(sid, sid)
            book_src = f"external/strategies/{sid}.json"
        for leg in legs:
            code = leg["code"]
            if not code:
                continue
            lots = float(leg["lots"]) * w
            notion = leg.get("notional_yuan")
            notion_s = float(notion) * w if notion is not None else None
            scaled.append(
                {
                    "code": code,
                    "name": leg.get("name") or names.get(code, ""),
                    "direction": leg["direction"],
                    "lots_ref": round(lots, 4),
                    "notional_ref": round(notion_s, 0) if notion_s is not None else None,
                    "sleeve_id": sid,
                    "sleeve": sleeve_label,
                    "sleeve_weight": w,
                    "raw_lots": leg["lots"],
                    "entry_date": leg.get("entry_date"),
                    "entry_price": leg.get("entry_price"),
                    "last_price": leg.get("last_price"),
                    "book_source": book_src,
                }
            )

    # Aggregate same code+direction across sleeves
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for row in scaled:
        key = (row["code"], row["direction"])
        cur = agg.get(key)
        if cur is None:
            agg[key] = {
                "code": row["code"],
                "name": row["name"],
                "direction": row["direction"],
                "lots_ref": row["lots_ref"],
                "notional_ref": row["notional_ref"] or 0.0,
                "sleeves": [row["sleeve"]],
                "sleeve_ids": [row["sleeve_id"]],
                "detail": [row],
            }
        else:
            cur["lots_ref"] = round(float(cur["lots_ref"]) + float(row["lots_ref"]), 4)
            if row["notional_ref"] is not None:
                cur["notional_ref"] = round(float(cur["notional_ref"] or 0) + float(row["notional_ref"]), 0)
            if row["sleeve"] not in cur["sleeves"]:
                cur["sleeves"].append(row["sleeve"])
                cur["sleeve_ids"].append(row["sleeve_id"])
            cur["detail"].append(row)

    rows = []
    for r in agg.values():
        raw_lots = float(r["lots_ref"])
        lots = floor_lots_one(raw_lots)
        notion = r.get("notional_ref")
        if lots != raw_lots and notion is not None and raw_lots > 1e-12:
            try:
                notion = round(float(notion) * (lots / raw_lots), 0)
            except (TypeError, ValueError):
                pass
        r = dict(r)
        r["lots_raw"] = round(raw_lots, 4)
        r["lots_ref"] = lots
        r["notional_ref"] = notion
        r["lots_floored"] = lots > raw_lots + 1e-12
        rows.append(r)
    rows = sorted(rows, key=lambda r: (-abs(float(r["lots_ref"])), r["code"]))

    # Display legs also use ≥1 手 on 参考手数
    for leg in scaled:
        raw = float(leg["lots_ref"])
        floored = floor_lots_one(raw)
        leg["lots_raw"] = round(raw, 4)
        if floored != raw:
            notion = leg.get("notional_ref")
            if notion is not None and raw > 1e-12:
                leg["notional_ref"] = round(float(notion) * (floored / raw), 0)
            leg["lots_ref"] = floored
            leg["lots_floored"] = True
        else:
            leg["lots_floored"] = False

    return {
        "ok": True,
        "disclaimer": DISCLAIMER,
        "blend": meta,
        "weights": weights,
        "sleeve_asof": sleeve_asof,
        "legs": scaled,
        "rows": rows,
        "n_rows": len(rows),
        "n_legs": len(scaled),
    }


def holdings_df(pack: dict[str, Any], *, root: Path | None = None) -> pd.DataFrame:
    names = _code_name_map(root) if root is not None else {}
    out = []
    for r in pack.get("rows") or []:
        out.append(
            {
                "品种": _variety_label(r.get("code"), r.get("name"), root=root, names=names),
                "方向": r.get("direction"),
                "参考手数": _num(r.get("lots_ref"), 3),
                "缩放手数": _num(r.get("lots_raw"), 3),
                "参考名义(元)": _num(r.get("notional_ref"), 0),
                "来源袖套": "、".join(r.get("sleeves") or []),
            }
        )
    return pd.DataFrame(out)


def legs_df(pack: dict[str, Any], *, root: Path | None = None) -> pd.DataFrame:
    names = _code_name_map(root) if root is not None else {}
    out = []
    for r in pack.get("legs") or []:
        out.append(
            {
                "品种": _variety_label(r.get("code"), r.get("name"), root=root, names=names),
                "方向": r.get("direction"),
                "参考手数": _num(r.get("lots_ref"), 3),
                "原始手数": _num(r.get("raw_lots"), 3),
                "袖套权重%": _num(float(r.get("sleeve_weight") or 0) * 100.0, 1),
                "袖套": r.get("sleeve"),
                "入场日": r.get("entry_date"),
            }
        )
    return pd.DataFrame(out)


def render_blend_holdings(st, root: Path) -> None:
    """Streamlit block under A+B blend section."""
    pack = build_blend_holdings(root)
    st.markdown("**最优组合·持仓参考**")
    st.caption(DISCLAIMER)
    if not pack.get("ok"):
        st.info(pack.get("note") or "无持仓参考")
        return
    meta = pack.get("blend") or {}
    st.caption(
        f"组合 {meta.get('label') or meta.get('weights_zh') or '—'} · "
        f"Calmar {meta.get('calmar') if meta.get('calmar') is not None else '—'} · "
        f"blend快照 {meta.get('blend_asof') or '—'}"
    )
    asof_bits = [f"{_SLEEVE_NAME.get(k, k)}@{v or '—'}" for k, v in (pack.get("sleeve_asof") or {}).items()]
    if asof_bits:
        st.caption("袖套持仓截止：" + " · ".join(asof_bits))
    df = holdings_df(pack, root=root)
    if df.empty:
        st.caption("当前各袖套空仓，或权重未覆盖有持仓的策略。")
        return
    st.dataframe(df, width="stretch", hide_index=True)
    with st.expander("分袖套明细（缩放前手数）", expanded=False):
        st.dataframe(legs_df(pack, root=root), width="stretch", hide_index=True)
