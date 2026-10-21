# -*- coding: utf-8 -*-
"""One-glance decision on top of the desk's real signals.

Uses the weighted ensemble, momentum row, and HMM state from
``desk.regime_board``, and institution net from the same member snapshot the
seat board already reads. Nothing here invents a hit rate, an event, or a price.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import load_json
from desk.regime_board import (
    _cached_events,
    _cached_pack,
    _exchange_for,
    _labels,
    _symbol_choices,
    build_symbol_pack,
    events_for_codes,
    joint_skip_reason,
)
from desk.seat_board import (
    GREEN,
    RED,
    _highlight_code,
    _iso,
    _num,
    cached_snapshot,
    member_dates,
)

FOOTER = "研究结论，不是交易指令。"
DECISION_RULE = (
    "结论：综合方向为震荡或样本不足，或前两名方向权重相对差距不超过15%，"
    "或动量与机构净持仓一多一空，则观望；"
    "只有综合方向为多或空，且动量与机构不相反，才记偏多或偏空。"
    "相对差距=(领先-次名)/领先。机构净持仓缺失时写明缺失，不把它当成同向。"
)
CONVICTION_RULE = (
    "把握：领先权重相对次名的差距超过30%，且与领先方向相同的模型不少于2个、评分均值不低于55，为高；"
    "差距超过15%，且不少于1个、均值不低于40，为中；其余为低。"
)
_DIRECTIONS = ("多", "空", "震荡")
_TRIGGER_TYPES = ("动量跨越", "动量机构同向")
_CONV_RANK = {"高": 0, "中": 1, "低": 2}


def _model_row(models: list[dict], name: str) -> dict | None:
    for row in models:
        if row.get("模型") == name:
            return row
    return None


def _model_direction(models: list[dict], name: str) -> str:
    row = _model_row(models, name)
    if not row:
        return "缺失"
    text = str(row.get("最新方向") or "").strip()
    return text or "缺失"


def _side(label: str | None) -> str | None:
    text = str(label or "").strip()
    if text in ("多", "偏多"):
        return "多"
    if text in ("空", "偏空"):
        return "空"
    if text in ("震荡", "零"):
        return "震荡"
    return None


def _supports(label: str, conclusion: str) -> str:
    side = _side(label)
    target = {"偏多": "多", "偏空": "空", "观望": "震荡"}.get(conclusion)
    if side is None or target is None:
        return "无"
    return "是" if side == target else "否"


def _weight_spread(weights: dict | None) -> dict[str, Any]:
    pairs: list[tuple[str, float]] = []
    raw = weights or {}
    for name in _DIRECTIONS:
        value = _num(raw.get(name))
        pairs.append((name, 0.0 if value is None else float(value)))
    pairs.sort(key=lambda item: item[1], reverse=True)
    top_name, top = pairs[0]
    second_name, second = pairs[1]
    if top <= 0:
        spread = 0.0
    else:
        spread = round((top - second) / top, 6)
    tied = [name for name, value in pairs if abs(value - top) <= 1e-9]
    return {
        "top_name": top_name,
        "top": top,
        "second_name": second_name,
        "second": second,
        "spread": spread,
        "close": spread <= 0.15,
        "tied": tied,
    }


def _agree_stats(models: list[dict], direction: str) -> tuple[float, int]:
    scores: list[float] = []
    for row in models:
        if row.get("最新方向") != direction:
            continue
        score = row.get("评分")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        return 0.0, 0
    return sum(scores) / len(scores), len(scores)


def _conviction(spread: float, mean_score: float, n_agree: int) -> str:
    if spread > 0.30 and n_agree >= 2 and mean_score >= 55.0:
        return "高"
    if spread > 0.15 and n_agree >= 1 and mean_score >= 40.0:
        return "中"
    return "低"


def institution_status(root: Path, code: str, report: dict | None) -> dict[str, Any]:
    """Latest institution-group net. Missing stays missing; zero stays zero."""
    code = str(code or "").upper()
    exchange = _exchange_for(root, code, report)
    skip = joint_skip_reason(root, code, report)
    if skip:
        if exchange == "DCE":
            cause = "该品种在大商所，没有机构净持仓"
        else:
            cause = "本地没有可用的会员排名，机构净持仓缺失"
        return {
            "missing": True,
            "direction": "缺失",
            "net": None,
            "date": "",
            "note": skip,
            "cause": cause,
        }
    dates = member_dates(root, exchange)
    ymd = dates[-1] if dates else ""
    snap = cached_snapshot(str(root), code, exchange, ymd) if ymd else {"ok": False}
    net = _num(snap.get("inst_net")) if snap.get("ok") else None
    day = _iso(ymd) if ymd else ""
    if net is None:
        return {
            "missing": True,
            "direction": "缺失",
            "net": None,
            "date": day,
            "note": f"{code} 在 {day or '最新'} 的会员排名里没有机构净持仓。",
            "cause": "最新会员排名没有这个品种的机构净持仓",
        }
    if net > 0:
        direction = "多"
    elif net < 0:
        direction = "空"
    else:
        direction = "零"
    return {
        "missing": False,
        "direction": direction,
        "net": float(net),
        "date": str(snap.get("date") or day),
        "note": "",
        "cause": "",
    }


def path_a_book(report: dict | None, code: str) -> dict[str, Any]:
    """Paper book from l1_report direction and lots_l1. No backtest fill-in."""
    code = str(code or "").upper()
    sig = None
    for row in (report or {}).get("signals") or []:
        if str(row.get("code") or "").upper() == code:
            sig = row
            break
    if not sig:
        return {"present": False, "direction": None, "lots": None, "raw_direction": ""}
    raw = str(sig.get("direction") or "").strip()
    lots = _num(sig.get("lots_l1"))
    direction = raw if raw in ("多", "空") else None
    return {
        "present": True,
        "direction": direction,
        "lots": lots,
        "raw_direction": raw,
    }


def _fmt_lots(value: float | None) -> str:
    if value is None:
        return "无"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}"


def _book_label(book: dict) -> str:
    if not book.get("present"):
        return "无此品种"
    lots = _fmt_lots(book.get("lots"))
    raw = book.get("direction") or book.get("raw_direction") or "无方向"
    return f"{raw} {lots}手"


def _paper(conclusion: str, book: dict) -> dict[str, Any]:
    direction = book.get("direction")
    lots = book.get("lots")
    open_book = direction in ("多", "空") and lots is not None and float(lots) > 0
    side = {"偏多": "多", "偏空": "空"}.get(conclusion)
    label = _book_label(book)
    if not book.get("present"):
        matches = conclusion == "观望"
        if matches:
            text = "纸面动作：观察。路径A账面没有这个品种，与观望一致，没有可维持的手数。"
        else:
            text = "纸面动作：观察。路径A账面没有这个品种，与结论不一致。"
        return {"action": "观察", "matches": matches, "text": text, "label": label}
    if open_book and side == direction:
        return {
            "action": "维持",
            "matches": True,
            "text": f"纸面动作：维持。与路径A账面一致，方向{direction}，手数{_fmt_lots(lots)}。",
            "label": label,
        }
    if open_book:
        return {
            "action": "观察",
            "matches": False,
            "text": (
                f"纸面动作：观察。与路径A账面不一致，账面方向{direction}，手数{_fmt_lots(lots)}。"
            ),
            "label": label,
        }
    matches = conclusion == "观望"
    raw = book.get("direction") or book.get("raw_direction") or "无方向"
    lots_txt = _fmt_lots(lots)
    if matches:
        text = f"纸面动作：观察。路径A没有持仓（方向{raw}，手数{lots_txt}），与观望一致。"
    else:
        text = f"纸面动作：观察。路径A没有持仓（方向{raw}，手数{lots_txt}），与结论不一致。"
    return {"action": "观察", "matches": matches, "text": text, "label": label}


def latest_trigger_event(events: list[dict] | None, code: str) -> dict | None:
    """Latest 动量跨越 or 动量机构同向. Same-day tie keeps the joint event."""
    code = str(code or "").upper()
    rows = []
    for row in events or []:
        if str(row.get("代码") or "").upper() != code:
            continue
        if row.get("类型") not in _TRIGGER_TYPES:
            continue
        rows.append(row)
    if not rows:
        return None

    def _key(row: dict) -> tuple[str, int]:
        kind = 1 if row.get("类型") == "动量机构同向" else 0
        return (str(row.get("日期") or ""), kind)

    return max(rows, key=_key)


def _fmt_net(net: float | None) -> str:
    if net is None:
        return ""
    return f"{net:+.0f}手"


def _reason(
    *,
    kind: str,
    ensemble: str,
    weights: dict,
    spread: dict,
    momentum: str,
    inst: dict,
) -> str:
    w_long = float((weights or {}).get("多") or 0.0)
    w_short = float((weights or {}).get("空") or 0.0)
    w_chop = float((weights or {}).get("震荡") or 0.0)
    vote = f"多 {w_long:.1f}、空 {w_short:.1f}、震荡 {w_chop:.1f}"
    if kind == "sample":
        return "决定性证据：没有可评分的模型，综合方向为样本不足。"
    if kind == "chop":
        tied = spread.get("tied") or []
        if len(tied) > 1:
            names = "、".join(str(name) for name in tied)
            return f"决定性证据：{names}权重同为最高，综合方向记为震荡。"
        return f"决定性证据：综合投票为震荡（{vote}）。"
    if kind == "close":
        pct = float(spread["spread"]) * 100.0
        return (
            f"决定性证据：{spread['top_name']}的权重{spread['top']:.1f}"
            f"与{spread['second_name']}的权重{spread['second']:.1f}"
            f"相对差距{pct:.1f}%，不超过15%。"
        )
    if kind == "missing":
        cause = str(inst.get("cause") or "机构净持仓缺失")
        return f"决定性证据：{cause}，不把缺失当成同向。"
    if kind == "disagree":
        net = _fmt_net(inst.get("net"))
        extra = f"（{net}）" if net else ""
        return (
            f"决定性证据：动量为{momentum}，机构净持仓为{inst.get('direction')}{extra}，符号相反。"
        )
    net = _fmt_net(inst.get("net"))
    extra = f"（{net}）" if net else ""
    return (
        f"决定性证据：综合投票为{ensemble}（{vote}），"
        f"动量为{momentum}，机构净持仓为{inst.get('direction')}{extra}。"
    )


def _disagreements(hmm_label: str, momentum: str, seat: str) -> tuple[list[str], list[str]]:
    named = (("HMM", hmm_label), ("动量", momentum), ("席位", seat))
    present = [(name, label, _side(label)) for name, label in named if _side(label)]
    missing = [name for name, label in named if _side(label) is None]
    conflicts: list[str] = []
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            left, right = present[i], present[j]
            if left[2] != right[2]:
                conflicts.append(f"{left[0]}为{left[1]}，{right[0]}为{right[1]}。")
    notes = []
    if missing:
        notes.append(f"{'、'.join(missing)}没有方向读数。")
    return conflicts, notes


def assemble_decision(
    *,
    code: str,
    pack: dict,
    inst: dict,
    book: dict,
    event: dict | None,
) -> dict[str, Any]:
    models = list(pack.get("models") or [])
    ensemble = pack.get("ensemble") or {}
    weights = dict(ensemble.get("weights") or {})
    ens = str(ensemble.get("direction") or "样本不足")
    spread = _weight_spread(weights)
    momentum = _model_direction(models, "动量20/60")
    mom_side = _side(momentum)
    inst_dir = str(inst.get("direction") or "缺失")
    inst_side = _side(inst_dir)
    disagree = (
        mom_side in ("多", "空")
        and inst_side in ("多", "空")
        and mom_side != inst_side
    )
    if ens not in ("多", "空", "震荡"):
        kind = "sample"
        conclusion = "观望"
    elif ens == "震荡":
        kind = "chop"
        conclusion = "观望"
    elif spread["close"]:
        kind = "close"
        conclusion = "观望"
    elif inst.get("missing"):
        kind = "missing"
        conclusion = "观望"
    elif disagree:
        kind = "disagree"
        conclusion = "观望"
    elif ens == "多":
        kind = "long"
        conclusion = "偏多"
    else:
        kind = "short"
        conclusion = "偏空"

    leader = ens if ens in _DIRECTIONS else ""
    mean_score, n_agree = _agree_stats(models, leader) if leader else (0.0, 0)
    conviction = _conviction(float(spread["spread"]), mean_score, n_agree)
    reason = _reason(
        kind=kind,
        ensemble=ens,
        weights=weights,
        spread=spread,
        momentum=momentum,
        inst=inst,
    )
    hmm = pack.get("hmm") or {}
    if hmm.get("ok"):
        hmm_label = str(hmm.get("latest") or "震荡")
    else:
        hmm_label = "无足够日线"
    seat = _model_direction(models, "席位资金")
    conflicts, missing_notes = _disagreements(hmm_label, momentum, seat)
    present = sum(1 for label in (hmm_label, momentum, seat) if _side(label))
    paper = _paper(conclusion, book)

    evidence = [
        {"信号": "动量", "方向": momentum, "支持结论": _supports(momentum, conclusion)},
        {"信号": "机构净持仓", "方向": inst_dir, "支持结论": _supports(inst_dir, conclusion)},
        {"信号": "HMM状态", "方向": hmm_label, "支持结论": _supports(hmm_label, conclusion)},
        {"信号": "综合投票", "方向": ens, "支持结论": _supports(ens, conclusion)},
    ]
    if event:
        kind_name = str(event.get("类型") or "")
        day = str(event.get("日期") or "")
        support = str(event.get("支持") or "")
        evidence.append(
            {
                "信号": f"{kind_name}（{day}）" if day else kind_name,
                "方向": support or "无",
                "支持结论": _supports(support, conclusion),
            }
        )

    return {
        "代码": code,
        "结论": conclusion,
        "把握": conviction,
        "理由": reason,
        "动作": paper["action"],
        "一致": bool(paper["matches"]),
        "一致文本": "是" if paper["matches"] else "否",
        "纸面": paper["text"],
        "账面": paper["label"],
        "证据": evidence,
        "分歧": conflicts,
        "可对照": present >= 2,
        "缺失说明": missing_notes,
        "事件": event,
        "机构说明": inst.get("note") or "",
        "机构日期": inst.get("date") or "",
        "机构净": inst.get("net"),
        "spread": float(spread["spread"]),
        "同向个数": n_agree,
        "同向均分": round(mean_score, 1) if n_agree else None,
        "领先方向": leader or "无",
    }


def build_decision(
    root: Path,
    code: str,
    *,
    pack: dict | None = None,
    report: dict | None = None,
    events: list[dict] | None = None,
) -> dict[str, Any]:
    code = str(code or "").upper()
    if report is None:
        report = load_json(root / "l1_report.json")
    if pack is None:
        pack = build_symbol_pack(root, code)
    if events is None:
        events = events_for_codes(root, report, [code])
    inst = institution_status(root, code, report)
    book = path_a_book(report, code)
    event = latest_trigger_event(events, code)
    return assemble_decision(code=code, pack=pack, inst=inst, book=book, event=event)


def _support_style(value: Any) -> str:
    text = str(value or "")
    if text == "是":
        return f"color: {GREEN}; font-weight: 600"
    if text == "否":
        return f"color: {RED}; font-weight: 600"
    return ""


def _conclusion_style(value: Any) -> str:
    text = str(value or "")
    if text == "偏多":
        return f"color: {GREEN}; font-weight: 600"
    if text == "偏空":
        return f"color: {RED}; font-weight: 600"
    if text == "观望":
        return "color: #8a8175; font-weight: 600"
    return ""


def render_decision_card(decision: dict, *, compact: bool = False) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("结论", decision.get("结论") or "观望")
    c2.metric("把握", decision.get("把握") or "低")
    c3.metric("纸面", decision.get("动作") or "观察")
    st.caption(CONVICTION_RULE)
    bits = []
    if decision.get("领先方向") and decision.get("领先方向") != "无":
        bits.append(f"领先方向{decision['领先方向']}")
    if decision.get("同向个数"):
        bits.append(f"同向模型{int(decision['同向个数'])}个")
    if decision.get("同向均分") is not None:
        bits.append(f"评分均值{float(decision['同向均分']):.1f}")
    bits.append(f"权重差距{float(decision.get('spread') or 0.0) * 100:.1f}%")
    st.caption("，".join(bits) + "。")
    st.write(decision.get("理由") or "")
    if compact:
        st.caption(FOOTER)
        return

    st.markdown("**证据**")
    frame = pd.DataFrame(decision.get("证据") or [])
    if frame.empty:
        st.info("没有可对照的信号。")
    else:
        styled = frame.style.map(_support_style, subset=["支持结论"])
        st.dataframe(styled, width="stretch", hide_index=True)
    notes = []
    if decision.get("机构日期") and decision.get("机构净") is not None:
        notes.append(
            f"机构净持仓取 {decision['机构日期']} 的机构组，净 {_fmt_net(decision.get('机构净'))}。"
        )
    elif decision.get("机构说明"):
        notes.append(str(decision["机构说明"]))
    event = decision.get("事件")
    if event:
        detail = str(event.get("细节") or "").strip()
        if detail:
            notes.append(f"{event.get('类型')} {event.get('日期')}：{detail}")
    else:
        notes.append("没有动量跨越或动量机构同向。")
    for note in notes:
        st.caption(note)

    st.markdown("**分歧**")
    conflicts = list(decision.get("分歧") or [])
    if conflicts:
        for line in conflicts:
            st.markdown(f"- {line}")
    elif decision.get("可对照"):
        st.write("主要模型一致。")
    else:
        st.write("可对照的方向不足两项，没有可列的分歧。")
    for line in decision.get("缺失说明") or []:
        st.caption(line)

    st.markdown("**纸面动作**")
    st.write(decision.get("纸面") or "")
    st.caption(FOOTER)


def render_decision_banner(root: Path, code: str, pack: dict, report: dict | None) -> None:
    decision = build_decision(root, code, pack=pack, report=report, events=[])
    render_decision_card(decision, compact=True)


def _ranked_rows(root: Path, report: dict | None, symbols: list[dict]) -> list[dict]:
    rows = []
    root_s = str(root)
    for meta in symbols:
        code = meta["code"]
        pack = _cached_pack(root_s, code)
        decision = build_decision(root, code, pack=pack, report=report, events=[])
        rows.append(
            {
                "代码": code,
                "名称": meta.get("name") or code,
                "结论": decision["结论"],
                "把握": decision["把握"],
                "与路径A一致": decision["一致文本"],
                "账面": decision["账面"],
                "spread": decision["spread"],
            }
        )
    rows.sort(
        key=lambda row: (
            _CONV_RANK.get(row["把握"], 9),
            0 if row["结论"] in ("偏多", "偏空") else 1,
            -float(row["spread"]),
            row["代码"],
        )
    )
    ranked = []
    for i, row in enumerate(rows, start=1):
        ranked.append(
            {
                "排名": i,
                "代码": row["代码"],
                "名称": row["名称"],
                "结论": row["结论"],
                "把握": row["把握"],
                "与路径A一致": row["与路径A一致"],
                "账面": row["账面"],
            }
        )
    return ranked


def render_decision_tab(root: Path) -> None:
    st.subheader("决策")
    st.caption(DECISION_RULE)
    st.caption("研究用结论。纸面动作只有维持或观察，不写委托。")
    report = load_json(root / "l1_report.json")
    symbols = _symbol_choices(root, report)
    if not symbols:
        st.error("universe.json 没有品种")
        return
    labels = _labels(symbols)
    seat_label = st.session_state.get("seat_sym")
    if isinstance(seat_label, str) and seat_label in labels:
        default_label = seat_label
    else:
        default_label = next(
            (lab for lab, row in zip(labels, symbols) if row["code"] == "MA"),
            labels[0],
        )
    if "decision_sym" not in st.session_state or st.session_state["decision_sym"] not in labels:
        st.session_state["decision_sym"] = default_label

    c_sym, c_btn = st.columns([3, 1])
    with c_sym:
        choice = st.selectbox("品种", labels, key="decision_sym")
    with c_btn:
        st.caption("")
        refresh = st.button("刷新", key="decision_refresh")
    if refresh:
        _cached_pack.clear()
        _cached_events.clear()
        cached_snapshot.clear()
        st.rerun()
    meta = symbols[labels.index(choice)]
    code = meta["code"]
    if isinstance(seat_label, str) and seat_label in labels:
        picked = "打开本页时沿用席位页已经选过的品种"
    else:
        picked = "席位页没有选过品种，默认 MA"
    st.caption(f"{picked}。当前 {code} {meta.get('name') or code}。")

    with st.spinner("读取本地日线并汇总决策..."):
        pack = _cached_pack(str(root), code)
        events = _cached_events(str(root), (code,))
        decision = build_decision(root, code, pack=pack, report=report, events=events)
    render_decision_card(decision, compact=False)

    st.markdown("**全市场**")
    st.caption(
        "按把握从高到低；同样把握时，偏多和偏空排在观望前面，再按权重差距从大到小。"
        "与路径A一致：偏多只对账面多且手数大于0，偏空只对账面空且手数大于0，"
        "观望只对没有持仓。账面是 l1_report 的 direction 与 lots_l1。"
    )
    with st.spinner("计算全市场决策..."):
        ranked = _ranked_rows(root, report, symbols)
    if not ranked:
        st.info("没有品种。")
        return
    frame = pd.DataFrame(ranked)
    styled = frame.style.apply(lambda row: _highlight_code(row, code), axis=1).map(
        _conclusion_style, subset=["结论"]
    )
    st.dataframe(styled, width="stretch", hide_index=True)
    st.caption(FOOTER)
