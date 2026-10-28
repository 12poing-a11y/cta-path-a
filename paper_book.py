# -*- coding: utf-8 -*-
"""Incremental Path-A paper book (simulated open lots + trade ledger).

Seeds from ``historical_backtest_latest.json`` → ``final_positions``, then
rolls with the latest ``l1_report.json`` so desk / Notion share one asof.
Persists ``trade_ledger`` (建仓/平仓明细) for Notion table sync.
Does not rewrite backtest KPIs. Paper only — no orders.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PAPER_PATH = ROOT / "paper_book_latest.json"
BT_PATH = ROOT / "historical_backtest_latest.json"
L1_PATH = ROOT / "l1_report.json"
UNI_PATH = ROOT / "universe.json"

LEDGER_MAX = 500

STRATEGY_ZH = {
    "composite_trend": "Path-A 复合趋势（回测期末种子）",
    "daily_selected": "Path-A 日信号组合入选",
    "daily_selected_observe": "Path-A 日信号组合入选（观察袖套）",
    "path_a": "Path-A",
}


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _ymd(asof: str | None) -> str:
    s = str(asof or "").replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(asof or "")


def _norm_asof(asof: str | None) -> str:
    return str(asof or "").replace("-", "")


def _exec_params() -> dict[str, float]:
    cfg = _load(UNI_PATH) or {}
    sel = cfg.get("selection") if isinstance(cfg.get("selection"), dict) else {}
    return {
        "stop_atr_mult": float(sel.get("stop_atr_mult") or cfg.get("stop_atr_mult") or 1.2),
        "reward_rr": float(sel.get("reward_rr") or cfg.get("reward_rr") or 1.5),
    }


def strategy_label(reason: str | None) -> str:
    r = str(reason or "").strip()
    return STRATEGY_ZH.get(r, r or "Path-A")


def tp_sl_scheme(
    *,
    stop: Any = None,
    target: Any = None,
    atr: Any = None,
    stop_atr_mult: float | None = None,
    reward_rr: float | None = None,
) -> str:
    """Human-readable 止盈止损方案 for Notion / desk."""
    bits: list[str] = []
    sm = stop_atr_mult if stop_atr_mult is not None else 1.2
    rr = reward_rr if reward_rr is not None else 1.5
    bits.append(f"止损={sm:g}×ATR")
    bits.append(f"止盈=RR×{rr:g}（止损距）")
    if atr not in (None, ""):
        try:
            bits.append(f"ATR={float(atr):.4g}")
        except (TypeError, ValueError):
            pass
    if stop not in (None, ""):
        try:
            bits.append(f"止损价={float(stop):.4g}")
        except (TypeError, ValueError):
            pass
    if target not in (None, ""):
        try:
            bits.append(f"止盈价={float(target):.4g}")
        except (TypeError, ValueError):
            pass
    return "；".join(bits)


def _realized_r(pos: dict, exit_px: Any) -> float | None:
    try:
        entry = float(pos.get("entry") or 0)
        stop = float(pos.get("stop") or 0)
        exit_f = float(exit_px or 0)
    except (TypeError, ValueError):
        return None
    risk = abs(entry - stop)
    if entry <= 0 or risk <= 0 or exit_f <= 0:
        return None
    direction = str(pos.get("direction") or "")
    if direction == "多":
        return (exit_f - entry) / risk
    if direction == "空":
        return (entry - exit_f) / risk
    return None


def _mult_map(root: Path | None = None) -> dict[str, float]:
    cfg = _load(Path(root or ROOT) / "universe.json") or {}
    out: dict[str, float] = {}
    for row in cfg.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        try:
            mult = float(row.get("mult") or 0)
        except (TypeError, ValueError):
            continue
        if code and mult > 0:
            out[code] = mult
    return out


def pnl_yuan(
    *,
    direction: str | None,
    entry: Any,
    mark: Any,
    lots: Any,
    mult: Any,
) -> float | None:
    """Futures paper PnL in CNY: (price diff) × mult × lots."""
    try:
        entry_f = float(entry or 0)
        mark_f = float(mark or 0)
        lots_f = float(lots or 0)
        mult_f = float(mult or 0)
    except (TypeError, ValueError):
        return None
    if entry_f <= 0 or mark_f <= 0 or lots_f == 0 or mult_f <= 0:
        return None
    d = str(direction or "")
    if d == "多":
        return (mark_f - entry_f) * mult_f * lots_f
    if d == "空":
        return (entry_f - mark_f) * mult_f * lots_f
    return None


def _trade_id(event: str, code: str, date: str, entry_date: str | None = None) -> str:
    return f"{event}|{str(code).upper()}|{date}|{entry_date or ''}"


def _ledger_keys(ledger: list[dict]) -> set[str]:
    keys: set[str] = set()
    for row in ledger:
        tid = str(row.get("trade_id") or "")
        if tid:
            keys.add(tid)
            continue
        keys.add(
            _trade_id(
                str(row.get("event") or ""),
                str(row.get("code") or ""),
                str(row.get("date") or ""),
                str(row.get("entry_date") or "") or None,
            )
        )
    return keys


def _append_ledger(ledger: list[dict], row: dict, *, max_n: int = LEDGER_MAX) -> None:
    tid = str(row.get("trade_id") or "")
    if tid and tid in _ledger_keys(ledger):
        return
    ledger.append(row)
    if len(ledger) > max_n:
        del ledger[: len(ledger) - max_n]


def _detail_row(
    *,
    event: str,
    code: str,
    date: str,
    pos: dict,
    params: dict[str, float],
    exit_px: Any = None,
    exit_reason: str | None = None,
    mark_px: Any = None,
    equity_before: float | None = None,
    mults: dict[str, float] | None = None,
) -> dict[str, Any]:
    entry_reason = str(pos.get("reason") or "path_a")
    entry_date = str(pos.get("entry_date") or "") or None
    stop = pos.get("stop")
    target = pos.get("target")
    atr = pos.get("atr")
    mult = (mults or {}).get(str(code).upper()) or pos.get("mult")
    r_mult = _realized_r(pos, exit_px) if event == "平仓" else None
    if event == "平仓":
        equity_delta = pnl_yuan(
            direction=str(pos.get("direction") or ""),
            entry=pos.get("entry"),
            mark=exit_px,
            lots=pos.get("lots"),
            mult=mult,
        )
    elif event == "持仓中":
        equity_delta = pnl_yuan(
            direction=str(pos.get("direction") or ""),
            entry=pos.get("entry"),
            mark=mark_px if mark_px is not None else exit_px,
            lots=pos.get("lots"),
            mult=mult,
        )
    else:
        equity_delta = 0.0
    equity_after = None
    if equity_before is not None and equity_delta is not None and event == "平仓":
        equity_after = float(equity_before) + float(equity_delta)
    elif equity_before is not None and event in ("建仓", "持仓中"):
        # Open book: 余额仍用账面权益；持仓中的增减是浮动盈亏，不改余额。
        equity_after = float(equity_before)
    tid = _trade_id(event, code, date, entry_date if event == "建仓" else entry_date)
    return {
        "trade_id": tid,
        "event": event,
        "code": code,
        "date": date,
        "entry_date": entry_date or date,
        "exit_date": date if event == "平仓" else None,
        "direction": pos.get("direction"),
        "lots": pos.get("lots"),
        "entry": pos.get("entry"),
        "exit": exit_px if event == "平仓" else None,
        "mark": mark_px if event == "持仓中" else (exit_px if event == "平仓" else None),
        "mult": mult,
        "stop": stop,
        "target": target,
        "atr": atr,
        "stop_atr_mult": params.get("stop_atr_mult"),
        "reward_rr": params.get("reward_rr"),
        "entry_reason": entry_reason,
        "strategy": strategy_label(entry_reason),
        "tp_sl_scheme": tp_sl_scheme(
            stop=stop,
            target=target,
            atr=atr,
            stop_atr_mult=params.get("stop_atr_mult"),
            reward_rr=params.get("reward_rr"),
        ),
        "reason": exit_reason if event == "平仓" else None,
        "R": r_mult,
        "equity_delta": None if equity_delta is None else round(float(equity_delta), 2),
        "equity_after": None if equity_after is None else round(float(equity_after), 2),
        "r20": pos.get("r20"),
        "r60": pos.get("r60"),
        "bucket": pos.get("bucket"),
    }


def _seed_positions() -> tuple[dict[str, dict], dict[str, Any], list[dict]]:
    """Prefer existing paper book; else backtest final_positions."""
    paper = _load(PAPER_PATH)
    ledger: list[dict] = []
    if paper and isinstance(paper.get("positions"), dict) and paper.get("ok"):
        pos = {
            str(k).upper(): dict(v)
            for k, v in paper["positions"].items()
            if isinstance(v, dict)
        }
        raw_ledger = paper.get("trade_ledger")
        if isinstance(raw_ledger, list):
            ledger = [dict(x) for x in raw_ledger if isinstance(x, dict)]
        meta = {
            "parent_backtest_end": str(paper.get("parent_backtest_end") or ""),
            "batch": str(paper.get("batch") or "pathA"),
            "seed": "paper_book_latest",
        }
        return pos, meta, ledger

    bt = _load(BT_PATH) or {}
    raw = bt.get("final_positions") if isinstance(bt.get("final_positions"), dict) else {}
    pos = {}
    for k, v in raw.items():
        if not isinstance(v, dict):
            continue
        code = str(k or v.get("code") or "").upper()
        if code:
            pos[code] = dict(v)
            pos[code]["code"] = code
    meta = {
        "parent_backtest_end": str(bt.get("end") or ""),
        "batch": str(bt.get("batch") or "pathA"),
        "seed": "historical_backtest_latest",
    }
    return pos, meta, ledger


def _signal_map(report: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in report.get("signals") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        if code:
            out[code] = row
    return out


def _should_exit(pos: dict, sig: dict | None) -> str | None:
    """Return exit reason or None to keep. Paper heuristic — not a live fill."""
    if not sig:
        return None
    held = str(pos.get("direction") or "").strip()
    raw = str(sig.get("direction") or "").strip()
    if held not in ("多", "空"):
        return "signal"
    if raw in ("多", "空") and raw != held:
        return "signal"
    if raw in ("空仓", "观望", "") and str(sig.get("align") or "") in (
        "冲突",
        "冲突/不足",
        "不足",
    ):
        return "signal"
    if raw == "空仓" and not sig.get("selected") and held:
        # Daily book flat on this name while we still hold → trend/filter exit.
        return "signal"
    return None


def _open_from_signal(sig: dict, *, stop_atr_mult: float, reward_rr: float) -> dict | None:
    direction = str(sig.get("direction") or "").strip()
    lots = int(sig.get("lots_l1") or 0)
    if direction not in ("多", "空") or lots <= 0:
        return None
    if not (sig.get("selected") or False):
        # Only open names that cleared portfolio caps today.
        return None
    close = float(sig.get("close") or 0)
    atr = float(sig.get("atr") or 0)
    if close <= 0 or atr <= 0 or atr >= close * 0.25:
        # Unusable ATR (seen when sina cache is bad) — skip new opens.
        return None
    stop_dist = stop_atr_mult * atr
    if direction == "多":
        stop = close - stop_dist
        target = close + reward_rr * stop_dist
    else:
        stop = close + stop_dist
        target = close - reward_rr * stop_dist
    sleeve = str(sig.get("sleeve") or "").strip() or None
    reason = "daily_selected_observe" if sleeve == "observe" else "daily_selected"
    return {
        "code": str(sig.get("code") or "").upper(),
        "direction": direction,
        "lots": lots,
        "entry": close,
        "stop": stop,
        "target": target,
        "atr": atr,
        "r20": sig.get("r20"),
        "r60": sig.get("r60"),
        "bucket": sig.get("bucket"),
        "sleeve": sleeve,
        "reason": reason,
        "entry_date": _ymd(sig.get("bar_date") or ""),
    }


def refresh_paper_book(
    root: Path | None = None,
    *,
    report: dict | None = None,
) -> dict[str, Any]:
    """Roll open book to l1 asof; append trade ledger; write ``paper_book_latest.json``."""
    root = Path(root or ROOT)
    paper_path = root / "paper_book_latest.json"
    bt_path = root / "historical_backtest_latest.json"
    l1_path = root / "l1_report.json"
    uni_path = root / "universe.json"

    global PAPER_PATH, BT_PATH, L1_PATH, UNI_PATH
    PAPER_PATH, BT_PATH, L1_PATH, UNI_PATH = paper_path, bt_path, l1_path, uni_path

    report = report or _load(l1_path)
    if not report or report.get("skipped"):
        return {
            "ok": False,
            "error": "missing or skipped l1_report",
            "path": str(paper_path),
        }

    asof = _norm_asof(report.get("asof"))
    asof_iso = _ymd(asof)
    params = _exec_params()
    positions, meta, ledger = _seed_positions()
    sigs = _signal_map(report)
    mults = _mult_map(root)
    prev_paper = _load(paper_path) or {}
    uni = _load(uni_path) or {}
    try:
        equity = float(
            prev_paper.get("equity")
            or report.get("equity")
            or uni.get("equity")
            or 200_000
        )
    except (TypeError, ValueError):
        equity = 200_000.0
    closed_today: list[dict] = []
    opened_today: list[dict] = []
    kept: dict[str, dict] = {}

    # Seed 建仓 rows once for inherited opens that have no ledger yet.
    if not ledger and positions:
        seed_day = str(meta.get("parent_backtest_end") or asof_iso)
        for code, pos in positions.items():
            if not pos.get("entry_date"):
                pos["entry_date"] = seed_day
            if not pos.get("mult"):
                pos["mult"] = mults.get(code)
            row = _detail_row(
                event="建仓",
                code=code,
                date=str(pos.get("entry_date") or seed_day),
                pos=pos,
                params=params,
                equity_before=equity,
                mults=mults,
            )
            _append_ledger(ledger, row)

    for code, pos in positions.items():
        pos = deepcopy(pos)
        pos["code"] = code
        if not pos.get("mult"):
            pos["mult"] = mults.get(code)
        sig = sigs.get(code)
        reason = _should_exit(pos, sig)
        if reason:
            exit_px = (sig or {}).get("close")
            detail = _detail_row(
                event="平仓",
                code=code,
                date=asof_iso,
                pos=pos,
                params=params,
                exit_px=exit_px,
                exit_reason=reason,
                equity_before=equity,
                mults=mults,
            )
            if detail.get("equity_delta") is not None:
                equity = float(equity) + float(detail["equity_delta"])
                detail["equity_after"] = round(equity, 2)
            closed_today.append(detail)
            _append_ledger(ledger, detail)
            continue
        if sig:
            # Refresh momentum labels only; keep stop/target unless ATR is sane.
            pos["r20"] = sig.get("r20", pos.get("r20"))
            pos["r60"] = sig.get("r60", pos.get("r60"))
            atr = float(sig.get("atr") or 0)
            close = float(sig.get("close") or 0)
            if atr > 0 and close > 0 and atr < close * 0.25:
                pos["atr"] = atr
            pos["mark"] = close if close > 0 else pos.get("mark")
            pos["equity_delta"] = pnl_yuan(
                direction=str(pos.get("direction") or ""),
                entry=pos.get("entry"),
                mark=pos.get("mark"),
                lots=pos.get("lots"),
                mult=pos.get("mult") or mults.get(code),
            )
            if pos.get("equity_delta") is not None:
                pos["equity_delta"] = round(float(pos["equity_delta"]), 2)
        kept[code] = pos

    opened = 0
    for code, sig in sigs.items():
        if code in kept:
            continue
        fresh = _open_from_signal(
            sig,
            stop_atr_mult=params["stop_atr_mult"],
            reward_rr=params["reward_rr"],
        )
        if fresh:
            if not fresh.get("entry_date"):
                fresh["entry_date"] = asof_iso
            fresh["mult"] = mults.get(code) or sig.get("mult")
            fresh["mark"] = fresh.get("entry")
            fresh["equity_delta"] = 0.0
            kept[code] = fresh
            opened += 1
            detail = _detail_row(
                event="建仓",
                code=code,
                date=str(fresh.get("entry_date") or asof_iso),
                pos=fresh,
                params=params,
                equity_before=equity,
                mults=mults,
            )
            opened_today.append(detail)
            _append_ledger(ledger, detail)

    floating = 0.0
    for pos in kept.values():
        if isinstance(pos, dict) and pos.get("equity_delta") is not None:
            floating += float(pos["equity_delta"])
    out = {
        "ok": True,
        "asof": asof_iso,
        "asof_ymd": asof,
        "source": "paper_book",
        "seed": meta.get("seed"),
        "parent_backtest_end": meta.get("parent_backtest_end"),
        "batch": meta.get("batch") or "pathA",
        "stop_atr_mult": params["stop_atr_mult"],
        "reward_rr": params["reward_rr"],
        "equity": round(equity, 2),
        "equity_floating": round(floating, 2),
        "equity_mark": round(equity + floating, 2),
        "positions": kept,
        "closed_today": closed_today,
        "opened_today": opened_today,
        "trade_ledger": ledger,
        "opened_n": opened,
        "closed_n": len(closed_today),
        "held_n": len(kept),
        "ledger_n": len(ledger),
        "notes": (
            "纸面模拟仓：以回测期末持仓为种子，按最新 l1_report 做信号平仓/组合入选开仓；"
            "trade_ledger 含入场/出场/止盈止损/策略/权益增减（平仓为已实现，持仓中为浮动）；"
            "equity 为平仓累计后账面，equity_floating 为未平仓浮动盈亏。"
            "不改写 historical_backtest KPI。与 Notion 持仓中、决策页账面同源。"
        ),
        "l1_asof": asof,
        "updated_from_l1": True,
    }
    paper_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


def load_paper_positions(root: Path | None = None) -> dict[str, Any]:
    """Desk/Notion helper: paper_book_latest first, else backtest final_positions."""
    root = Path(root or ROOT)
    paper = _load(root / "paper_book_latest.json")
    if paper and paper.get("ok") and isinstance(paper.get("positions"), dict):
        positions = {
            str(k).upper(): dict(v)
            for k, v in paper["positions"].items()
            if isinstance(v, dict)
        }
        ledger = [
            dict(x) for x in (paper.get("trade_ledger") or []) if isinstance(x, dict)
        ]
        return {
            "ok": True,
            "missing": False,
            "end": str(paper.get("asof") or ""),
            "start": str(paper.get("parent_backtest_end") or ""),
            "positions": positions,
            "source": "paper_book_latest",
            "batch": str(paper.get("batch") or "pathA"),
            "stop_atr_mult": paper.get("stop_atr_mult"),
            "reward_rr": paper.get("reward_rr"),
            "closed_today": list(paper.get("closed_today") or []),
            "opened_today": list(paper.get("opened_today") or []),
            "trade_ledger": ledger,
        }

    bt = _load(root / "historical_backtest_latest.json")
    if not bt:
        return {
            "ok": False,
            "missing": True,
            "end": "",
            "start": "",
            "positions": {},
            "source": "none",
            "trade_ledger": [],
        }
    raw = bt.get("final_positions") if isinstance(bt.get("final_positions"), dict) else {}
    positions = {}
    for k, v in raw.items():
        if not isinstance(v, dict):
            continue
        code = str(k or v.get("code") or "").upper()
        if code:
            positions[code] = dict(v)
    return {
        "ok": bool(bt.get("ok")),
        "missing": False,
        "end": str(bt.get("end") or ""),
        "start": str(bt.get("start") or ""),
        "positions": positions,
        "source": "historical_backtest_latest",
        "batch": str(bt.get("batch") or "pathA"),
        "stop_atr_mult": bt.get("stop_atr_mult"),
        "reward_rr": bt.get("reward_rr"),
        "closed_today": [],
        "opened_today": [],
        "trade_ledger": [],
    }


def main() -> int:
    out = refresh_paper_book(ROOT)
    if not out.get("ok"):
        print("[paper] fail:", out.get("error"))
        return 1
    print(
        f"[paper] asof={out.get('asof')} held={out.get('held_n')} "
        f"opened={out.get('opened_n')} closed={out.get('closed_n')} "
        f"ledger={out.get('ledger_n')} → {PAPER_PATH.name}"
    )
    for code, pos in sorted((out.get("positions") or {}).items()):
        print(f"  {code} {pos.get('direction')} {pos.get('lots')}手")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
