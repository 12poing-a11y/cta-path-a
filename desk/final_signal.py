# -*- coding: utf-8 -*-
"""Final paper-action board: merge L1 + sentiment + decision + paper book + regime.

Research suggestions only — never places live orders (``live_trading=false``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import format_variety_label, load_json, load_l1_report, load_universe
from desk.sentiment_panel import load_sentiment_snapshot, sentiment_verdict

FOOTER = "研究建议，非交易指令。"
DETAIL_CAPTION = "明细页；最终行动见「最终信号」"
_ACTION_RANK = {
    "止盈预警": 0,
    "止损预警": 1,
    "建议平": 2,
    "建议开": 3,
    "持有": 4,
    "观望": 5,
}
_NEAR_TARGET_ATR = 0.1


def _side(label: str | None) -> str | None:
    text = str(label or "").strip()
    if text in ("多", "偏多"):
        return "多"
    if text in ("空", "偏空"):
        return "空"
    if text in ("震荡", "观望", "零"):
        return "震荡"
    return None


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_execution_rules(root: Path) -> dict[str, Any]:
    return load_json(root / "execution_rules.json") or {}


def path_a_enabled(regime_key: str | None, *, root: Path | None = None) -> bool:
    from regime_enable import enabled_sleeves, load_regime_enable

    cfg = load_regime_enable(root)
    # Missing/empty rules → do not block Path-A (paper research default).
    if not (cfg.get("rules") or []):
        return True
    sleeves = {r["sleeve"] for r in enabled_sleeves(regime_key, root=root, cfg=cfg)}
    return "path_a" in sleeves


def infer_desk_regime_key(
    *,
    root: Path | None = None,
    report: dict[str, Any] | None = None,
    decisions: dict[str, dict] | None = None,
    sentiment: dict[str, Any] | None = None,
) -> str:
    """Infer Path-A regime from desk crumbs — not ``default_regime`` alone.

    Prefer decision conclusions / 领先方向, then L1 selected direction/bucket,
    then sentiment. Falls back to ``mixed`` (no HMM / full-universe scan).
    """
    from regime_enable import infer_regime_from_pack, load_regime_enable, normalize_regime

    cfg = load_regime_enable(root)
    stance: str | None = None
    trend_n = 0
    chop_n = 0

    for dec in (decisions or {}).values():
        if not isinstance(dec, dict) or dec.get("_unavailable"):
            continue
        pack_guess = infer_regime_from_pack(
            {
                "regime_label": dec.get("regime_label") or dec.get("regime"),
                "state": dec.get("state"),
                "bucket": dec.get("bucket"),
                "dir_name": dec.get("领先方向") or dec.get("dir_name"),
                "综合方向": dec.get("综合方向"),
                "decision": {
                    "stance": dec.get("stance"),
                    "dir": dec.get("dir"),
                    "方向": dec.get("方向"),
                    "label": dec.get("label"),
                },
            }
        )
        conclusion = str(dec.get("结论") or "").strip()
        if conclusion in ("偏多", "偏空"):
            trend_n += 1
            stance = stance or conclusion
        elif conclusion in ("观望", "震荡"):
            chop_n += 1
        for key in ("领先方向", "stance", "dir", "方向"):
            val = dec.get(key)
            if not val or str(val).strip() in ("", "无", "—", "样本不足"):
                continue
            if not stance and _side(str(val)) in ("多", "空"):
                stance = str(val)
                if conclusion not in ("偏多", "偏空"):
                    trend_n += 1
            break
        if not stance and pack_guess in ("strong_trend", "trend", "chop", "chop_strong"):
            stance = pack_guess

    if trend_n > chop_n and trend_n > 0:
        stance = stance or "偏多"
    elif chop_n > trend_n and chop_n > 0:
        stance = "震荡"
    elif trend_n and chop_n and trend_n == chop_n:
        stance = stance or "mixed"

    if not stance:
        selected_dirs: list[str] = []
        buckets: list[str] = []
        for sig in (report or {}).get("signals") or []:
            if not isinstance(sig, dict):
                continue
            if sig.get("selected"):
                side = _side(sig.get("direction"))
                if side in ("多", "空"):
                    selected_dirs.append(side)
            b = str(sig.get("bucket") or "").strip()
            if b:
                buckets.append(b)
        if selected_dirs:
            stance = "偏多"  # directed day-picks → trend sleeve space
        elif buckets:
            stance = buckets[0]

    if not stance and sentiment:
        sent_side = _side(sentiment.get("direction"))
        if sent_side in ("多", "空"):
            stance = "偏多" if sent_side == "多" else "偏空"
        elif sent_side == "震荡":
            stance = "震荡"

    # Explicit mixed fallback — do not read regime_enable default_regime here.
    return normalize_regime(str(stance) if stance else "mixed", cfg)


def sentiment_hard_veto(
    sentiment: dict[str, Any] | None,
    variety_side: str | None,
) -> bool:
    """Portfolio stance opposite variety side with conviction_pct ≥ 60."""
    if not sentiment or variety_side not in ("多", "空"):
        return False
    sent_side = _side(sentiment.get("direction"))
    if sent_side not in ("多", "空") or sent_side == variety_side:
        return False
    try:
        conv = float(sentiment.get("conviction_pct") or 0)
    except (TypeError, ValueError):
        conv = 0.0
    return conv >= 60.0


def _hit_target(
    *,
    direction: str,
    mark: float | None,
    target: float | None,
    atr: float | None,
) -> bool:
    if mark is None or target is None:
        return False
    near = (_NEAR_TARGET_ATR * float(atr)) if atr and atr > 0 else 0.0
    if direction == "多":
        return mark >= target or (target - mark) <= near
    if direction == "空":
        return mark <= target or (mark - target) <= near
    return False


def _hit_stop(*, direction: str, mark: float | None, stop: float | None) -> bool:
    if mark is None or stop is None:
        return False
    if direction == "多":
        return mark <= stop
    if direction == "空":
        return mark >= stop
    return False


def project_stop_target(
    sig: dict[str, Any] | None,
    *,
    root: Path | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, float | None]:
    """Same stop/target math as ``paper_book._open_from_signal`` (display only)."""
    if not sig:
        return {"stop": None, "target": None, "entry": None, "lots": None}
    rules = rules if rules is not None else (load_execution_rules(root) if root else {})
    stop_atr_mult = float(rules.get("stop_atr_mult") or 1.2)
    reward_rr = float(rules.get("reward_rr") or 1.5)
    from paper_book import _open_from_signal

    opened = _open_from_signal(sig, stop_atr_mult=stop_atr_mult, reward_rr=reward_rr)
    if not opened:
        # Fall back to raw projection even when not selected / lots=0 for display.
        direction = str(sig.get("direction") or "").strip()
        close = _num(sig.get("close"))
        atr = _num(sig.get("atr"))
        if direction not in ("多", "空") or not close or not atr or atr >= close * 0.25:
            return {
                "stop": None,
                "target": None,
                "entry": close,
                "lots": _num(sig.get("lots_l1")),
            }
        stop_dist = stop_atr_mult * atr
        if direction == "多":
            stop = close - stop_dist
            target = close + reward_rr * stop_dist
        else:
            stop = close + stop_dist
            target = close - reward_rr * stop_dist
        return {
            "stop": round(stop, 6),
            "target": round(target, 6),
            "entry": close,
            "lots": _num(sig.get("lots_l1")),
        }
    return {
        "stop": opened.get("stop"),
        "target": opened.get("target"),
        "entry": opened.get("entry"),
        "lots": opened.get("lots"),
    }


def _l1_conflict(held_side: str, sig: dict[str, Any] | None) -> bool:
    """Held direction conflicts with today's L1 selected / directed signal."""
    if not sig:
        return False
    sig_side = _side(sig.get("direction"))
    if sig_side not in ("多", "空"):
        return False
    if sig.get("selected") and sig_side != held_side:
        return True
    # Directed opposite with non-zero lots also counts as conflict.
    lots = _num(sig.get("lots_l1")) or 0.0
    if lots > 0 and sig_side != held_side:
        return True
    return False


def resolve_final_action(
    *,
    held: bool,
    held_side: str | None,
    mark: float | None,
    stop: float | None,
    target: float | None,
    atr: float | None,
    decision_conclusion: str | None,
    l1_selected: bool,
    l1_conflict: bool,
    sentiment: dict[str, Any] | None,
    path_a_ok: bool,
    l1_side: str | None = None,
    decision_available: bool = True,
) -> tuple[str, str]:
    """Return (动作, 预警/理由片段). Priority matches the locked plan table."""
    dec_side = _side(decision_conclusion)
    l1_dir = _side(l1_side) if l1_side is not None else None
    veto_side = held_side if held else dec_side
    hard_veto = sentiment_hard_veto(sentiment, veto_side)

    if held and held_side in ("多", "空"):
        if _hit_target(direction=held_side, mark=mark, target=target, atr=atr):
            return "止盈预警", "盯市触及/接近止盈"
        if _hit_stop(direction=held_side, mark=mark, stop=stop):
            return "止损预警", "盯市触及/越过止损"
        if hard_veto:
            return "建议平", "情绪硬否决"
        if l1_conflict:
            return "建议平", "与L1日选冲突"
        # Missing/failed decision must not silently map to 建议平 via 观望.
        if not decision_available:
            return "观望", "决策不可用"
        if dec_side in ("多", "空") and dec_side == held_side and path_a_ok and not hard_veto:
            return "持有", "仓向与决策同向"
        # Real 观望 / reverse decision, or path_a disabled
        if dec_side is None or dec_side == "震荡" or (
            dec_side in ("多", "空") and dec_side != held_side
        ):
            return "建议平", "决策观望或反向"
        if not path_a_ok:
            return "建议平", "Path-A/regime禁用"
        return "建议平", "持仓不宜续持"

    # Flat book
    if not decision_available:
        return "观望", "决策不可用"
    if hard_veto and dec_side in ("多", "空"):
        return "观望", "情绪硬否决"
    if (
        not held
        and l1_selected
        and dec_side in ("多", "空")
        and l1_dir in ("多", "空")
        and l1_dir == dec_side
        and not hard_veto
        and path_a_ok
    ):
        return "建议开", "日选与决策同向"
    if (
        not held
        and l1_selected
        and dec_side in ("多", "空")
        and l1_dir in ("多", "空")
        and l1_dir != dec_side
    ):
        return "观望", "日选与决策方向不一致"
    return "观望", "未达开仓条件"


def _reason_text(
    *,
    action: str,
    tip: str,
    decision_conclusion: str | None,
    sentiment: dict[str, Any] | None,
    book_label: str,
    max_len: int = 40,
) -> str:
    sent_bit = "—"
    if sentiment:
        d = sentiment.get("direction") or "—"
        try:
            pct = float(sentiment.get("conviction_pct") or 0)
            sent_bit = f"{d}{pct:.0f}%"
        except (TypeError, ValueError):
            sent_bit = str(d)
    parts = [
        str(decision_conclusion or "观望"),
        f"情绪{sent_bit}",
        book_label,
    ]
    if tip:
        parts.append(tip)
    text = "·".join(parts)
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def build_final_signal_row(
    root: Path,
    code: str,
    *,
    report: dict[str, Any] | None = None,
    sentiment: dict[str, Any] | None = None,
    book: dict[str, Any] | None = None,
    decision_or_none: dict[str, Any] | None = None,
    regime_key: str | None = None,
    sig: dict[str, Any] | None = None,
    name: str = "",
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One variety → final paper action row."""
    code = str(code or "").upper()
    report = report or {}
    book = book or {}
    positions = book.get("positions") or {}
    pos = positions.get(code) if isinstance(positions.get(code), dict) else None

    if sig is None:
        for row in report.get("signals") or []:
            if isinstance(row, dict) and str(row.get("code") or "").upper() == code:
                sig = row
                break
    sig = sig or {}
    name = name or str(sig.get("name") or "")

    held_side = _side((pos or {}).get("direction")) if pos else None
    lots = _num((pos or {}).get("lots")) if pos else None
    held = bool(pos) and held_side in ("多", "空") and (lots or 0) > 0

    mark = _num((pos or {}).get("mark")) if pos else None
    if mark is None:
        mark = _num(sig.get("close"))
    stop = _num((pos or {}).get("stop")) if pos else None
    target = _num((pos or {}).get("target")) if pos else None
    atr = _num((pos or {}).get("atr")) if pos else _num(sig.get("atr"))
    entry = _num((pos or {}).get("entry")) if pos else None
    floating = _num((pos or {}).get("equity_delta")) if pos else None

    decision = decision_or_none or {}
    # Failed builds must not become held→建议平 via fake 观望. Missing cards on
    # flat names keep the historical default-观望 path (still cannot 建议开).
    if decision.get("_unavailable"):
        decision_available = False
        conclusion = "决策不可用"
        conviction = str(decision.get("把握") or "低")
    elif decision_or_none is None:
        decision_available = not held
        conclusion = "观望"
        conviction = "—"
    else:
        decision_available = True
        conclusion = str(decision.get("结论") or "观望")
        conviction = str(decision.get("把握") or "—")
    l1_selected = bool(sig.get("selected"))
    l1_dir = _side(sig.get("direction"))
    l1_label = (
        f"{'日选' if l1_selected else '信号'}{l1_dir}"
        if l1_dir in ("多", "空")
        else ("未选" if sig else "无信号")
    )
    conflict = _l1_conflict(held_side, sig) if held and held_side else False
    path_a_ok = path_a_enabled(regime_key, root=root)

    action, tip = resolve_final_action(
        held=held,
        held_side=held_side,
        mark=mark,
        stop=stop,
        target=target,
        atr=atr,
        decision_conclusion=None if not decision_available else conclusion,
        l1_selected=l1_selected,
        l1_conflict=conflict,
        sentiment=sentiment,
        path_a_ok=path_a_ok,
        l1_side=l1_dir,
        decision_available=decision_available,
    )

    # Project stop/target for 建议开 when flat.
    if action == "建议开" and (stop is None or target is None):
        proj = project_stop_target(sig, root=root, rules=rules)
        stop = stop if stop is not None else proj.get("stop")
        target = target if target is not None else proj.get("target")
        entry = entry if entry is not None else proj.get("entry")
        if lots is None:
            lots = proj.get("lots")

    direction = held_side or _side(conclusion) or l1_dir or "—"
    book_label = (
        f"{held_side}{int(lots) if lots is not None and abs(lots - round(lots)) < 1e-9 else lots}手"
        if held
        else "空仓"
    )
    sent_label = "—"
    if sentiment:
        sent_label = str(sentiment.get("label") or sentiment.get("direction") or "—")

    variety = format_variety_label(code, name, root=root)
    return {
        "代码": code,
        "品种": variety,
        "最终动作": action,
        "方向": direction if direction else "—",
        "把握": conviction,
        "手数": lots,
        "入场": entry,
        "止损": stop,
        "止盈": target,
        "浮动盈亏": floating,
        "L1日选": l1_label,
        "决策": conclusion,
        "情绪": sent_label,
        "模拟仓": book_label,
        "理由": _reason_text(
            action=action,
            tip=tip,
            decision_conclusion=conclusion,
            sentiment=sentiment,
            book_label=book_label,
        ),
        "_primary_tip": tip,
        "_held": held,
        "_l1_selected": l1_selected,
        "_l1_directed": l1_dir in ("多", "空"),
    }


def _signal_map(report: dict[str, Any] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (report or {}).get("signals") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        if code:
            out[code] = row
    return out


def _name_map(root: Path, report: dict | None = None) -> dict[str, str]:
    names: dict[str, str] = {}
    uni = load_universe(root) or {}
    for row in uni.get("symbols") or []:
        if isinstance(row, dict):
            code = str(row.get("code") or "").upper()
            if code:
                names[code] = str(row.get("name") or "")
    for sig in (report or {}).get("signals") or []:
        if isinstance(sig, dict):
            code = str(sig.get("code") or "").upper()
            if code and code not in names:
                names[code] = str(sig.get("name") or "")
    return names


def _primary_codes(
    *,
    positions: dict[str, Any],
    sig_map: dict[str, dict],
) -> set[str]:
    held = {
        str(c).upper()
        for c, pos in positions.items()
        if isinstance(pos, dict)
        and _side(pos.get("direction")) in ("多", "空")
        and (_num(pos.get("lots")) or 0) > 0
    }
    selected = {
        c for c, sig in sig_map.items() if sig.get("selected")
    }
    directed = {
        c for c, sig in sig_map.items() if _side(sig.get("direction")) in ("多", "空")
    }
    return held | selected | directed


def build_final_signal_board(
    root: Path,
    *,
    report: dict[str, Any] | None = None,
    book: dict[str, Any] | None = None,
    sentiment_snap: dict[str, Any] | None = None,
    regime_key: str | None = None,
    decisions: dict[str, dict] | None = None,
    compute_decisions: bool = True,
) -> dict[str, Any]:
    """Full final-signal board. Primary = held ∪ L1 selected ∪ L1 directed."""
    root = Path(root)
    report = report if report is not None else (load_l1_report(root) or {})
    if book is None:
        from desk.decision import load_paper_book

        book = load_paper_book(root)
    snap = (
        sentiment_snap
        if sentiment_snap is not None
        else load_sentiment_snapshot(root)
    )
    sentiment = sentiment_verdict(snap)
    rules = load_execution_rules(root)

    sig_map = _signal_map(report)
    positions = book.get("positions") or {}
    names = _name_map(root, report)
    primary = _primary_codes(positions=positions, sig_map=sig_map)

    # Universe ∪ held ∪ signals
    codes: set[str] = set(primary)
    for row in (load_universe(root) or {}).get("symbols") or []:
        if isinstance(row, dict):
            c = str(row.get("code") or "").upper()
            if c:
                codes.add(c)
    for c in sig_map:
        codes.add(c)
    for c in positions:
        codes.add(str(c).upper())

    decisions = dict(decisions or {})
    if compute_decisions:
        for code in sorted(primary):
            if code in decisions:
                continue
            try:
                from desk.decision import build_decision
                from desk.regime_board import _cached_pack

                try:
                    pack = _cached_pack(str(root), code)
                except Exception:
                    pack = None
                decisions[code] = build_decision(
                    root,
                    code,
                    pack=pack,
                    report=report,
                    paper=book,
                )
            except Exception as exc:  # noqa: BLE001
                # Mark unavailable — must not become held→建议平 via fake 观望.
                decisions[code] = {
                    "结论": "观望",
                    "把握": "低",
                    "理由": f"决策不可用：{exc}",
                    "_unavailable": True,
                }

    if regime_key is None:
        regime_key = infer_desk_regime_key(
            root=root,
            report=report,
            decisions=decisions,
            sentiment=sentiment,
        )

    primary_rows: list[dict] = []
    other_rows: list[dict] = []
    for code in sorted(codes):
        row = build_final_signal_row(
            root,
            code,
            report=report,
            sentiment=sentiment,
            book=book,
            decision_or_none=decisions.get(code),
            regime_key=regime_key,
            sig=sig_map.get(code),
            name=names.get(code, ""),
            rules=rules,
        )
        if code in primary:
            primary_rows.append(row)
        else:
            # Fold non-primary into expander; force 观望 summary unless already held
            # (held always primary). Keep action as resolved (usually 观望).
            other_rows.append(row)

    def _sort_key(r: dict) -> tuple:
        return (
            _ACTION_RANK.get(str(r.get("最终动作")), 9),
            0 if r.get("把握") == "高" else (1 if r.get("把握") == "中" else 2),
            str(r.get("代码") or ""),
        )

    primary_rows.sort(key=_sort_key)
    other_rows.sort(key=_sort_key)

    alerts = sum(
        1 for r in primary_rows if r.get("最终动作") in ("止盈预警", "止损预警")
    )
    opens = sum(1 for r in primary_rows if r.get("最终动作") == "建议开")
    held_n = sum(1 for r in primary_rows if r.get("_held"))

    composite = None
    try:
        from desk.composite_eval import desk_composite_score

        composite = desk_composite_score(root, write=False)
    except Exception:
        composite = None

    return {
        "ok": True,
        "live_trading": False,
        "regime": regime_key,
        "sentiment": sentiment,
        "composite": composite,
        "primary": primary_rows,
        "other": other_rows,
        "metrics": {
            "held_n": held_n,
            "alert_n": alerts,
            "open_n": opens,
            "desk_score": (composite or {}).get("desk_score"),
        },
        "asof": book.get("end") or book.get("asof") or report.get("asof"),
    }


def _display_frame(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "品种",
        "最终动作",
        "方向",
        "把握",
        "手数",
        "入场",
        "止损",
        "止盈",
        "浮动盈亏",
        "L1日选",
        "决策",
        "情绪",
        "模拟仓",
        "理由",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    clean = [{k: r.get(k) for k in cols} for r in rows]
    return pd.DataFrame(clean)


def render_final_signal_tab(root: Path) -> None:
    st.subheader("最终信号")
    st.caption(FOOTER + " · 纸面行动总表；日信号/情绪/状态/决策为明细。")

    with st.spinner("合并日信号、情绪、决策与模拟仓…"):
        board = build_final_signal_board(root)

    metrics = board.get("metrics") or {}
    c1, c2, c3, c4 = st.columns(4)
    score = metrics.get("desk_score")
    c1.metric("综合分", f"{score:.1f}" if isinstance(score, (int, float)) else "—")
    c2.metric("持仓数", metrics.get("held_n") if metrics.get("held_n") is not None else "—")
    c3.metric("预警数", metrics.get("alert_n") if metrics.get("alert_n") is not None else "—")
    c4.metric("建议开", metrics.get("open_n") if metrics.get("open_n") is not None else "—")

    sent = board.get("sentiment") or {}
    st.caption(
        f"asof={board.get('asof') or '—'} · regime={board.get('regime') or '—'} · "
        f"情绪 {sent.get('label') or '—'} · live_trading=否"
    )

    primary = board.get("primary") or []
    if not primary:
        st.info("暂无持仓、日选或有方向的 L1 信号可汇总。")
    else:
        st.markdown("**主表**（持仓 ∪ 日选 ∪ 有方向信号；预警置顶）")
        st.dataframe(_display_frame(primary), width="stretch", hide_index=True)

    other = board.get("other") or []
    with st.expander(f"其它品种（{len(other)}）· 观望摘要", expanded=False):
        if not other:
            st.caption("无其它品种。")
        else:
            st.dataframe(_display_frame(other), width="stretch", hide_index=True)

    st.caption(FOOTER)
