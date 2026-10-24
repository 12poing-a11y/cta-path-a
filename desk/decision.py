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

from desk.loaders import format_variety_label, load_json
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
    ensure_dce_latest,
    member_dates,
)

FOOTER = "研究结论，不是交易指令。"
DECISION_RULE = (
    "结论：综合方向为震荡或样本不足，或前两名方向权重相对差距不超过15%，"
    "或动量与机构净持仓一多一空，则观望；"
    "只有综合方向为多或空，且动量与机构不相反，才记偏多或偏空。"
    "相对差距=(领先-次名)/领先。机构净持仓缺失时写明缺失，不把它当成同向。"
    "升贴水极端旁路开启时：若近次月 |gap|≥阈值且与结论方向逆向，结论降为观望（不替代席位入场）。"
    "多维波动旁路开启时：短窗/长窗已实现波动比≥扩张阈值（默认1.6）则降为观望（高波慎追趋势）。"
    "实验室边旁路开启时：IS冻结合成截面分位与拟开仓方向严重逆向（默认最低/最高20%）则降为观望；缺数放行。"
    "模型投票以趋势R2为主轴、HMM降权（见 desk/model_vote_weights.json）；HMM不作硬否决。"
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
    if exchange == "DCE" and not member_dates(root, "DCE"):
        # One-shot warm-up: daily job used to skip DCE fetch entirely.
        ensure_dce_latest(root)
    skip = joint_skip_reason(root, code, report)
    if skip:
        if exchange == "DCE":
            cause = "大商所本地无 dce-*.json 缓存，机构净持仓缺失"
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


def load_paper_book(root: Path) -> dict[str, Any]:
    """Open paper positions — same source Notion ``sync_trades`` prefers.

    Prefer ``paper_book_latest.json`` (daily roll); fall back to backtest
    ``final_positions``. Daily ``l1_report.lots_l1`` is not the simulated book.
    """
    try:
        from paper_book import load_paper_positions

        return load_paper_positions(root)
    except Exception:
        pass
    bt = load_json(root / "historical_backtest_latest.json")
    if not bt:
        return {
            "ok": False,
            "missing": True,
            "end": "",
            "start": "",
            "positions": {},
            "source": "none",
        }
    raw = bt.get("final_positions") if isinstance(bt.get("final_positions"), dict) else {}
    positions: dict[str, dict] = {}
    for key, pos in raw.items():
        if not isinstance(pos, dict):
            continue
        code = str(key or pos.get("code") or "").upper()
        if not code:
            continue
        positions[code] = pos
    return {
        "ok": bool(bt.get("ok")),
        "missing": False,
        "end": str(bt.get("end") or ""),
        "start": str(bt.get("start") or ""),
        "positions": positions,
        "source": "historical_backtest_latest",
    }


def path_a_book(
    code: str,
    *,
    paper: dict[str, Any] | None = None,
    root: Path | None = None,
    report: dict | None = None,
) -> dict[str, Any]:
    """Simulated open book for one variety (Notion 持仓中 source).

    ``report`` is accepted for call-site compatibility and ignored: open lots
    come from backtest ``final_positions``, not ``l1_report.lots_l1``.
    """
    del report  # explicit: do not use daily signal lots as the paper book
    code = str(code or "").upper()
    if paper is None:
        if root is None:
            return {
                "present": False,
                "direction": None,
                "lots": None,
                "raw_direction": "",
                "source": "final_positions",
                "asof": "",
            }
        paper = load_paper_book(root)
    pos = (paper.get("positions") or {}).get(code)
    asof = str(paper.get("end") or "")
    if not pos:
        return {
            "present": True,
            "direction": None,
            "lots": 0.0,
            "raw_direction": "空仓",
            "source": "final_positions",
            "asof": asof,
            "entry": None,
            "reason": "",
        }
    raw = str(pos.get("direction") or "").strip()
    lots = _num(pos.get("lots"))
    direction = raw if raw in ("多", "空") else None
    return {
        "present": True,
        "direction": direction,
        "lots": lots,
        "raw_direction": raw or "无方向",
        "source": "final_positions",
        "asof": asof,
        "entry": pos.get("entry"),
        "reason": str(pos.get("reason") or ""),
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
    asof = str(book.get("asof") or "").strip()
    asof_bit = f"（模拟仓 asof {asof}）" if asof else "（模拟仓=回测期末持仓，与 Notion 同源）"
    if not book.get("present"):
        matches = conclusion == "观望"
        if matches:
            text = f"纸面动作：观察。模拟仓没有这个品种{asof_bit}，与观望一致，没有可维持的手数。"
        else:
            text = f"纸面动作：观察。模拟仓没有这个品种{asof_bit}，与结论不一致。"
        return {"action": "观察", "matches": matches, "text": text, "label": label}
    if open_book and side == direction:
        return {
            "action": "维持",
            "matches": True,
            "text": f"纸面动作：维持。与模拟仓一致{asof_bit}，方向{direction}，手数{_fmt_lots(lots)}。",
            "label": label,
        }
    if open_book:
        return {
            "action": "观察",
            "matches": False,
            "text": (
                f"纸面动作：观察。与模拟仓不一致{asof_bit}，账面方向{direction}，手数{_fmt_lots(lots)}。"
            ),
            "label": label,
        }
    matches = conclusion == "观望"
    raw = book.get("direction") or book.get("raw_direction") or "无方向"
    lots_txt = _fmt_lots(lots)
    if matches:
        text = f"纸面动作：观察。模拟仓没有持仓{asof_bit}（方向{raw}，手数{lots_txt}），与观望一致。"
    else:
        text = f"纸面动作：观察。模拟仓没有持仓{asof_bit}（方向{raw}，手数{lots_txt}），与结论不一致。"
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
    carry: dict | None = None,
    vol: dict | None = None,
    lab: dict | None = None,
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
    if kind == "carry":
        label = str((carry or {}).get("label") or "升贴水极端")
        return f"决定性证据：升贴水旁路触发（{label}），原综合方向降为观望。"
    if kind == "vol":
        label = str((vol or {}).get("label") or "高波扩张")
        return f"决定性证据：多维波动旁路触发（{label}），高波扩张时不追趋势，降为观望。"
    if kind == "lab":
        label = str((lab or {}).get("label") or "实验室边逆向")
        return f"决定性证据：实验室边旁路触发（{label}），因子截面与方向严重逆向，降为观望。"
    net = _fmt_net(inst.get("net"))
    extra = f"（{net}）" if net else ""
    return (
        f"决定性证据：综合投票为{ensemble}（{vote}），"
        f"动量为{momentum}，机构净持仓为{inst.get('direction')}{extra}。"
    )


def _carry_bypass_status(
    root: Path,
    code: str,
    *,
    report: dict | None,
    direction: str | None,
) -> dict[str, Any]:
    """Latest front/next gap vs carry_bypass cfg. Missing data → pass."""
    from path_a_filters import carry_bypass_cfg, carry_bypass_decision

    uni = load_json(root / "universe.json") or {}
    cfg = carry_bypass_cfg(uni.get("carry_bypass"))
    out: dict[str, Any] = {
        "enabled": bool(cfg.get("enabled")),
        "label": "旁路关闭",
        "gap_pct": None,
        "block": None,
        "scale": float(cfg.get("scale") or 0.5),
        "thr": float(cfg.get("extreme_gap_pct") or 1.0),
        "action": str(cfg.get("action") or "block"),
    }
    if not cfg.get("enabled"):
        return out
    code = str(code or "").upper()
    sig = _signal_row(report, code) if report else {}
    gap = _num(sig.get("carry_gap_pct"))
    pair = None
    if gap is not None:
        pair = (100.0, 100.0 * (1.0 + float(gap) / 100.0))
    else:
        try:
            from public_curve import load_curves

            curves = load_curves([code])
            carry_map = (curves.get(code) or {}).get("carry") or {}
            day = str(sig.get("bar_date") or "")
            if not day:
                asof = str((report or {}).get("asof") or "")
                if len(asof) == 8 and asof.isdigit():
                    day = f"{asof[:4]}-{asof[4:6]}-{asof[6:8]}"
            if not day or day not in carry_map:
                days = sorted(carry_map.keys())
                day = days[-1] if days else ""
            pair = carry_map.get(day) if day else None
        except Exception:
            pair = None
    want = direction if direction in ("多", "空") else "多"
    block, scale, label, gap2 = carry_bypass_decision(
        want,
        pair,
        extreme_gap_pct=float(cfg["extreme_gap_pct"]),
        action=str(cfg["action"]),
        scale=float(cfg["scale"]),
    )
    if sig.get("carry_bypass") and gap is None and gap2 is None:
        label = str(sig.get("carry_bypass"))
    out.update(
        {
            "label": label,
            "gap_pct": gap2 if gap2 is not None else gap,
            "block": block,
            "scale": scale,
        }
    )
    return out


def _disagreements(
    hmm_label: str,
    momentum: str,
    seat: str,
    *,
    r2_label: str | None = None,
) -> tuple[list[str], list[str]]:
    # Primary axis: 趋势R2 + 动量 + 席位. HMM kept as soft note only (OOS A-gate weak).
    named = (("趋势R2", r2_label or ""), ("动量", momentum), ("席位", seat))
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
    hmm_side = _side(hmm_label)
    if hmm_side and present:
        # Soft annotate only — does not enter hard conflict list for conviction.
        opp = [f"{n}为{lab}" for n, lab, side in present if side != hmm_side]
        if opp:
            notes.append(f"HMM为{hmm_label}（降权软提示，与{'、'.join(opp)}不一致）。")
    return conflicts, notes


def assemble_decision(
    *,
    code: str,
    pack: dict,
    inst: dict,
    book: dict,
    event: dict | None,
    carry: dict | None = None,
    vol: dict | None = None,
    lab: dict | None = None,
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

    carry = carry or {"enabled": False, "label": "旁路关闭", "gap_pct": None, "block": None}
    vol = vol or {"enabled": False, "label": "旁路关闭", "force_observe": False}
    lab = lab or {"enabled": False, "label": "旁路关闭", "force_observe": False}
    # Soft veto when action=block: extreme carry against conclusion → 观望.
    # action=scale only annotates; lot scaling is done in daily_update / backtest.
    if conclusion in ("偏多", "偏空") and carry.get("enabled"):
        want = "多" if conclusion == "偏多" else "空"
        block, mult, label, gap = _reeval_carry_block(want, carry)
        carry = {**carry, "label": label, "gap_pct": gap, "scale": mult}
        if block:
            kind = "carry"
            conclusion = "观望"
            carry["block"] = block
        elif mult is not None and mult < 1.0:
            carry["block"] = None
            carry["label"] = label
    # Multi-scale vol: high expansion → 观望 (does not replace seats entry).
    if conclusion in ("偏多", "偏空") and vol.get("enabled") and vol.get("force_observe"):
        kind = "vol"
        conclusion = "观望"
    # Lab IS-frozen edge: strong cross-section disagree → 观望.
    if conclusion in ("偏多", "偏空") and lab.get("enabled") and lab.get("force_observe"):
        kind = "lab"
        conclusion = "观望"

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
        carry=carry,
        vol=vol,
        lab=lab,
    )
    hmm = pack.get("hmm") or {}
    if hmm.get("ok"):
        hmm_label = str(hmm.get("latest") or "震荡")
    else:
        hmm_label = "无足够日线"
    r2_label = _model_direction(models, "趋势R2")
    seat = _model_direction(models, "席位资金")
    conflicts, missing_notes = _disagreements(
        hmm_label, momentum, seat, r2_label=r2_label
    )
    present = sum(1 for label in (r2_label, momentum, seat) if _side(label))
    paper = _paper(conclusion, book)

    carry_dir = str(carry.get("label") or "—")
    evidence = [
        {"信号": "趋势R2", "方向": r2_label, "支持结论": _supports(r2_label, conclusion)},
        {"信号": "动量", "方向": momentum, "支持结论": _supports(momentum, conclusion)},
        {"信号": "机构净持仓", "方向": inst_dir, "支持结论": _supports(inst_dir, conclusion)},
        {
            "信号": "HMM状态(降权)",
            "方向": hmm_label,
            "支持结论": _supports(hmm_label, conclusion),
        },
        {"信号": "综合投票", "方向": ens, "支持结论": _supports(ens, conclusion)},
        {
            "信号": "升贴水旁路",
            "方向": carry_dir,
            "支持结论": "否" if kind == "carry" else ("是" if carry.get("enabled") else "无"),
        },
        {
            "信号": "多维波动",
            "方向": str(vol.get("label") or "—"),
            "支持结论": "否" if kind == "vol" else ("是" if vol.get("enabled") else "无"),
        },
        {
            "信号": "实验室边",
            "方向": str(lab.get("label") or "—"),
            "支持结论": "否" if kind == "lab" else ("是" if lab.get("enabled") else "无"),
        },
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
        "升贴水旁路": carry,
        "多维波动": vol,
        "实验室边": lab,
    }


def _reeval_carry_block(direction: str, carry: dict) -> tuple[str | None, float, str, float | None]:
    """Re-check block/scale for a direction using stored gap when possible."""
    from path_a_filters import carry_bypass_decision

    gap = carry.get("gap_pct")
    action = str(carry.get("action") or "block")
    thr = float(carry.get("thr") or 1.0)
    scale = float(carry.get("scale") if carry.get("scale") is not None else 0.5)
    if gap is not None:
        # gap% = (next-front)/front*100 → next/front = 1 + gap/100
        front, nxt = 100.0, 100.0 * (1.0 + float(gap) / 100.0)
        return carry_bypass_decision(
            direction,
            (front, nxt),
            extreme_gap_pct=thr,
            action=action,
            scale=scale,
        )
    block = carry.get("block")
    if block and action == "block":
        return str(block), 0.0, str(carry.get("label") or block), gap
    return None, 1.0, str(carry.get("label") or "—"), gap


def build_decision(
    root: Path,
    code: str,
    *,
    pack: dict | None = None,
    report: dict | None = None,
    events: list[dict] | None = None,
    paper: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = str(code or "").upper()
    if report is None:
        report = load_json(root / "l1_report.json")
    if pack is None:
        pack = build_symbol_pack(root, code)
    if events is None:
        events = events_for_codes(root, report, [code])
    if paper is None:
        paper = load_paper_book(root)
    inst = institution_status(root, code, report)
    book = path_a_book(code, paper=paper, root=root)
    event = latest_trigger_event(events, code)
    ens_dir = str(((pack or {}).get("ensemble") or {}).get("direction") or "")
    carry = _carry_bypass_status(root, code, report=report, direction=ens_dir)
    vol = _vol_bypass_status(root, code)
    want = ens_dir if ens_dir in ("多", "空") else None
    # Prefer momentum direction for lab veto when ensemble is choppy.
    if want is None:
        mom = _model_direction(list((pack or {}).get("models") or []), "动量20/60")
        want = mom if mom in ("多", "空") else "多"
    lab = _lab_edge_status(root, code, direction=want)
    return assemble_decision(
        code=code,
        pack=pack,
        inst=inst,
        book=book,
        event=event,
        carry=carry,
        vol=vol,
        lab=lab,
    )


def _lab_edge_status(root: Path, code: str, *, direction: str) -> dict[str, Any]:
    from lab_signal import lab_edge_bypass_cfg, lab_edge_decision, load_latest_pack

    uni = load_json(root / "universe.json") or {}
    cfg = lab_edge_bypass_cfg(uni.get("lab_edge_bypass"))
    pack = load_latest_pack(root)
    return lab_edge_decision(direction, code, pack, cfg)


def _vol_bypass_status(root: Path, code: str) -> dict[str, Any]:
    from vol_factor_combo import load_vol_for_code, vol_bypass_cfg

    uni = load_json(root / "universe.json") or {}
    cfg = vol_bypass_cfg(uni.get("vol_bypass"))
    try:
        return load_vol_for_code(root, code, cfg)
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": bool(cfg.get("enabled")),
            "ok": False,
            "label": f"波动旁路不可用:{exc}"[:80],
            "force_observe": False,
            "regime": "unknown",
        }


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
    eq_brief = str(decision.get("股指简要") or "").strip()
    if eq_brief:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("结论", decision.get("结论") or "观望")
        c2.metric("把握", decision.get("把握") or "低")
        c3.metric("纸面", decision.get("动作") or "观察")
        c4.metric("股指", decision.get("股指标签") or "—")
    else:
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
    if eq_brief:
        bits.append(eq_brief)
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
    try:
        from desk.composite_eval import _equity_brief, equity_timing_snapshot

        eq = equity_timing_snapshot(root)
        brief_pair = _equity_brief(eq)
        if brief_pair:
            label, brief = brief_pair
            decision = dict(decision)
            decision["股指标签"] = label
            decision["股指简要"] = brief
    except Exception:
        pass
    render_decision_card(decision, compact=True)


def _ranked_rows(root: Path, report: dict | None, symbols: list[dict]) -> list[dict]:
    rows = []
    root_s = str(root)
    paper = load_paper_book(root)
    for meta in symbols:
        code = meta["code"]
        pack = _cached_pack(root_s, code)
        decision = build_decision(
            root, code, pack=pack, report=report, events=[], paper=paper
        )
        rows.append(
            {
                "代码": code,
                "名称": meta.get("name") or code,
                "结论": decision["结论"],
                "把握": decision["把握"],
                "与模拟仓一致": decision["一致文本"],
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
                "与模拟仓一致": row["与模拟仓一致"],
                "账面": row["账面"],
            }
        )
    return ranked


def _paper_holdings_frame(root: Path, symbols: list[dict], paper: dict[str, Any]) -> pd.DataFrame:
    name_by = {str(s.get("code") or "").upper(): s.get("name") for s in symbols}
    rows = []
    for code, pos in sorted((paper.get("positions") or {}).items()):
        if not isinstance(pos, dict):
            continue
        code_u = str(code).upper()
        rows.append(
            {
                "品种": format_variety_label(
                    code_u, str(name_by.get(code_u) or ""), root=root
                ),
                "方向": pos.get("direction") or "—",
                "手数": pos.get("lots"),
                "入场价": pos.get("entry"),
                "建仓因": pos.get("reason") or "—",
                "止损": pos.get("stop"),
                "止盈": pos.get("target"),
            }
        )
    return pd.DataFrame(rows)


def _signal_row(report: dict | None, code: str) -> dict:
    code = str(code or "").upper()
    for row in (report or {}).get("signals") or []:
        if str(row.get("code") or "").upper() == code:
            return row
    return {}


def _cross_model_row(
    *,
    code: str,
    name: str,
    root: Path,
    report: dict | None,
    paper: dict,
    decision: dict,
    pack: dict,
) -> dict[str, Any]:
    """One asof checker row: paper / daily signal / decision / ensemble / HMM."""
    pos = (paper.get("positions") or {}).get(code) or {}
    sig = _signal_row(report, code)
    ensemble = (pack or {}).get("ensemble") or {}
    hmm = (pack or {}).get("hmm") or {}
    paper_dir = pos.get("direction") if pos else None
    paper_lots = pos.get("lots") if pos else None
    if paper_dir in ("多", "空") and paper_lots is not None and float(paper_lots) > 0:
        paper_txt = f"{paper_dir} { _fmt_lots(float(paper_lots)) }手"
    else:
        paper_txt = "空仓"
    sig_dir = str(sig.get("direction") or "—")
    sig_lots = sig.get("lots_l1")
    sig_txt = f"{sig_dir} / lots={_fmt_lots(_num(sig_lots))}"
    hmm_label = str(hmm.get("latest") or "—") if hmm.get("ok") else "无足够日线"
    ens_dir = str(ensemble.get("direction") or "样本不足")
    conclusion = str(decision.get("结论") or "观望")
    drift = []
    if paper_dir in ("多", "空") and sig_dir in ("多", "空") and paper_dir != sig_dir:
        drift.append("模拟仓≠日信号")
    if conclusion in ("偏多", "偏空"):
        want = "多" if conclusion == "偏多" else "空"
        if paper_dir in ("多", "空") and paper_dir != want:
            drift.append("决策≠模拟仓")
        if not paper_dir or not (paper_lots and float(paper_lots) > 0):
            if conclusion != "观望":
                drift.append("决策有方向但模拟仓无持仓")
    carry = decision.get("升贴水旁路") or {}
    carry_txt = str(carry.get("label") or "—")
    if carry.get("gap_pct") is not None and "极端" not in carry_txt and "放行" not in carry_txt:
        carry_txt = f"{carry_txt} ({carry['gap_pct']:+.2f}%)"
    if carry.get("block"):
        drift.append("升贴水旁路禁开")
    vol = decision.get("多维波动") or {}
    vol_txt = str(vol.get("label") or "—")
    if vol.get("force_observe"):
        drift.append("多维波动·高波观望")
    return {
        "品种": format_variety_label(code, name, root=root),
        "模拟仓": paper_txt,
        "日信号": sig_txt,
        "决策": conclusion,
        "把握": decision.get("把握") or "—",
        "模型投票": ens_dir,
        "HMM": hmm_label,
        "升贴水旁路": carry_txt,
        "多维波动": vol_txt,
        "分歧": "；".join(drift) if drift else "—",
    }


def render_decision_tab(root: Path) -> None:
    st.subheader("决策")
    st.caption(DECISION_RULE)
    st.caption("研究用结论。纸面动作只有维持或观察，不写委托。")
    report = load_json(root / "l1_report.json")
    paper = load_paper_book(root)
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

    st.markdown("**模拟仓持仓**")
    asof = paper.get("end") or "—"
    src = paper.get("source") or "—"
    if paper.get("missing"):
        st.warning(
            "缺少 paper_book_latest.json / historical_backtest_latest.json，"
            "无法显示与 Notion 同源的模拟仓。"
        )
    else:
        st.caption(
            f"与 Notion「持仓中」同源：优先 paper_book_latest（源={src}，asof {asof}）。"
            "不是当日 l1_report 的 lots_l1。侧栏可「仅刷新模拟仓」。"
        )
        holdings = _paper_holdings_frame(root, symbols, paper)
        if holdings.empty:
            st.info(f"模拟仓当前空仓（asof {asof}）。")
        else:
            st.dataframe(holdings, width="stretch", hide_index=True)

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
        decision = build_decision(
            root, code, pack=pack, report=report, events=events, paper=paper
        )
    render_decision_card(decision, compact=False)

    from desk.lab_panel import render_lab_gate_panel

    render_lab_gate_panel(root, compact=False, widget_ns="decision")

    st.markdown("**跨模型对照（Checker）**")
    st.caption(
        "同品种对照：模拟仓手数、日信号、决策结论、模型投票、HMM。"
        "只标分歧，不合成假 KPI；不自动改仓。"
    )
    cross = _cross_model_row(
        code=code,
        name=str(meta.get("name") or code),
        root=root,
        report=report,
        paper=paper,
        decision=decision,
        pack=pack,
    )
    st.dataframe(pd.DataFrame([cross]), width="stretch", hide_index=True)

    st.markdown("**全市场**")
    st.caption(
        "按把握从高到低；同样把握时，偏多和偏空排在观望前面，再按权重差距从大到小。"
        "与模拟仓一致：偏多只对账面多且手数大于0，偏空只对账面空且手数大于0，"
        "观望只对没有持仓。账面来自 paper_book_latest / final_positions（与 Notion 同源）。"
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

    st.markdown("**全市场跨模型分歧**")
    cross_rows = []
    root_s = str(root)
    for meta_row in symbols:
        c = meta_row["code"]
        pk = _cached_pack(root_s, c)
        dec = build_decision(root, c, pack=pk, report=report, events=[], paper=paper)
        row = _cross_model_row(
            code=c,
            name=str(meta_row.get("name") or c),
            root=root,
            report=report,
            paper=paper,
            decision=dec,
            pack=pk,
        )
        if row.get("分歧") and row["分歧"] != "—":
            cross_rows.append(row)
    if cross_rows:
        st.dataframe(pd.DataFrame(cross_rows), width="stretch", hide_index=True)
    else:
        st.caption("当前没有标出模拟仓/日信号/决策之间的方向分歧。")
    st.caption(FOOTER)
