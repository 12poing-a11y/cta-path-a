# -*- coding: utf-8 -*-
"""Incremental Path-A paper book (simulated open lots + trade ledger).

Seeds from ``historical_backtest_latest.json`` → ``final_positions``, then
rolls with the latest ``l1_report.json`` so desk / Notion share one asof.
Persists ``trade_ledger`` (建仓/平仓明细) for Notion table sync.
Does not rewrite backtest KPIs. Paper only — no orders.
"""
from __future__ import annotations

import hashlib
import json
import os
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
        "stop_atr_mult": float(sel.get("stop_atr_mult") or cfg.get("stop_atr_mult") or 0.8),
        "reward_rr": float(sel.get("reward_rr") or cfg.get("reward_rr") or 2.0),
    }


def _cap_params() -> dict[str, float]:
    """Portfolio caps from universe.json (same keys / defaults as ``daily_update``)."""
    cfg = _load(UNI_PATH) or {}

    def _num(key: str, default: float) -> float:
        try:
            return float(cfg.get(key) if cfg.get(key) is not None else default)
        except (TypeError, ValueError):
            return float(default)

    return {
        "max_positions": int(_num("max_positions", 3)),
        "max_gross_pct": _num("max_gross_exposure_pct", 50.0),
        "max_port_risk_pct": _num("max_portfolio_risk_pct", 10.0),
        "max_per_bucket": int(_num("max_per_bucket", 1)),
    }


def caps_book_check(
    kept: dict[str, dict],
    fresh: dict,
    *,
    equity: float,
    caps: dict[str, float],
    mult: float | None,
) -> str | None:
    """R4: may ``fresh`` join ``kept``?  Returns None when allowed, else a short reason.

    Checks position count, sector bucket, gross notional and ATR risk of (book + new) at the
    signal close, against ``equity``.  Does not touch entry prices."""
    from position_rules import book_usage_from_positions

    if len(kept) >= int(caps["max_positions"]):
        return f"positions {len(kept)}>={int(caps['max_positions'])}"
    bucket = str(fresh.get("bucket") or "_")
    _g0, _r0, buckets = book_usage_from_positions(kept)
    if int(caps["max_per_bucket"]) > 0 and buckets.get(bucket, 0) >= int(caps["max_per_bucket"]):
        return f"bucket {bucket} full"
    if not equity or equity <= 0 or not mult:
        return "no equity/mult to size caps"
    lots = abs(int(fresh.get("lots") or 0))
    new_g = lots * float(fresh.get("entry") or 0) * float(mult)
    new_r = lots * float(fresh.get("atr") or 0) * float(mult)
    gross_pct = (_g0 + new_g) / float(equity) * 100.0
    risk_pct = (_r0 + new_r) / float(equity) * 100.0
    if gross_pct > float(caps["max_gross_pct"]) + 1e-9:
        return f"gross {gross_pct:.1f}%>{caps['max_gross_pct']:g}%"
    if risk_pct > float(caps["max_port_risk_pct"]) + 1e-9:
        return f"atr_risk {risk_pct:.1f}%>{caps['max_port_risk_pct']:g}%"
    return None


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
    sm = stop_atr_mult if stop_atr_mult is not None else 0.8
    rr = reward_rr if reward_rr is not None else 2.0
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


def exit_condition_text(
    pos: dict | None = None,
    *,
    stop_atr_mult: float | None = None,
    reward_rr: float | None = None,
) -> str:
    """Full 平仓条件 line for holdings tables."""
    pos = pos or {}
    scheme = tp_sl_scheme(
        stop=pos.get("stop"),
        target=pos.get("target"),
        atr=pos.get("atr"),
        stop_atr_mult=stop_atr_mult
        if stop_atr_mult is not None
        else pos.get("stop_atr_mult"),
        reward_rr=reward_rr if reward_rr is not None else pos.get("reward_rr"),
    )
    return (
        f"平仓条件：{scheme}；盘中15m触及即平；否则收盘信号/趋势失效平仓。"
    )


def _history_rows(root: Path, code: str) -> list[dict]:
    """Read ``.cache/history/{CODE}0.json`` rows (list[dict])."""
    code = str(code or "").upper()
    if not code:
        return []
    path = Path(root) / ".cache" / "history" / f"{code}0.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        rows = data.get("bars") or data.get("hist") or []
    else:
        rows = data if isinstance(data, list) else []
    return [b for b in rows if isinstance(b, dict)]


def _is_session_bar(bar: dict) -> bool:
    """True for a real session bar: weekday + non-empty open.

    ``.cache/history`` sometimes retains weekend placeholder rows (no open,
    H=L=C = prior close) from sparse iFinD merges; those must not enter the
    paper_book trading calendar.
    """
    from datetime import date as _date

    d = str(bar.get("date") or "")[:10]
    if len(d) != 10:
        return False
    try:
        if _date.fromisoformat(d).weekday() >= 5:
            return False
    except ValueError:
        return False
    o = bar.get("open")
    if o is None or o == "":
        return False
    try:
        if float(o) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _local_daily_bar(root: Path, code: str, asof_iso: str) -> dict | None:
    """Read ``.cache/history/{CODE}0.json`` for the bar with date == asof_iso."""
    day = _ymd(asof_iso)
    if not day:
        return None
    for b in _history_rows(root, code):
        if str(b.get("date") or "")[:10] == day and _is_session_bar(b):
            return b
    return None


def _session_dates(root: Path, code: str) -> list[str]:
    """Ascending trading-day dates from local continuous history (no weekends)."""
    out: list[str] = []
    for b in _history_rows(root, code):
        if not _is_session_bar(b):
            continue
        d = str(b.get("date") or "")[:10]
        if len(d) == 10:
            out.append(d)
    return out


def _tick_map(root: Path | None = None) -> dict[str, float]:
    cfg = _load(Path(root or ROOT) / "universe.json") or {}
    out: dict[str, float] = {}
    for row in cfg.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        try:
            tick = float(row.get("tick") or 0)
        except (TypeError, ValueError):
            continue
        if code:
            out[code] = tick
    return out


def _intraday_stop_exit(
    pos: dict, *, root: Path, asof_iso: str
) -> tuple[str | None, float | None]:
    """Check cached 15m bars for stop/target touch on asof trading day.

    Skip when ``entry_date == asof``: same-day opens must not be judged against
    pre-entry (or full-day) minute bars — that made double daily runs non-idempotent.
    R2: load by trading day (night session → next session); sina daily open is the
    night open so entry-day skip remains the only entry-day guard (no 09:00 cutoff).
    """
    entry_day = _ymd(str(pos.get("entry_date") or ""))
    if entry_day and entry_day == _ymd(asof_iso):
        return None, None
    try:
        from minute_data import load_minute_bars_on_trading_day
        from wyckoff_pullback import apply_stop_target_intraday
    except Exception:  # noqa: BLE001
        return None, None
    stop, target = pos.get("stop"), pos.get("target")
    entry = pos.get("entry")
    direction = str(pos.get("direction") or "")
    if stop is None or target is None or entry is None or direction not in ("多", "空"):
        return None, None
    code = str(pos.get("code") or "")
    sessions = _session_dates(root, code)
    if not sessions:
        return None, None
    try:
        bars = load_minute_bars_on_trading_day(
            root, code, asof_iso, period="15", sessions=sessions
        )
    except Exception:  # noqa: BLE001
        return None, None
    if not bars:
        return None, None
    day_bar = _local_daily_bar(root, code, asof_iso)
    tick = float((_tick_map(root).get(code.upper()) or 0))
    from wyckoff_pullback import minute_bars_aligned_with_entry, minute_bars_match_daily

    if day_bar is None or not minute_bars_match_daily(bars, day_bar, tick=tick):
        return None, None
    if not minute_bars_aligned_with_entry(float(entry), bars):
        return None, None
    reason, px = apply_stop_target_intraday(
        direction, float(entry), float(stop), float(target), bars
    )
    if reason in ("stop", "target") and px is not None:
        return reason, float(px)
    return None, None


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


def _append_ledger(ledger: list[dict], row: dict, *, max_n: int = LEDGER_MAX) -> bool:
    """Append if new. Returns True when a row was actually written."""
    tid = str(row.get("trade_id") or "")
    if tid and tid in _ledger_keys(ledger):
        return False
    ledger.append(row)
    if len(ledger) > max_n:
        del ledger[: len(ledger) - max_n]
    return True


def _report_fingerprint(report: dict[str, Any]) -> str:
    """Stable hash of the fields that drive paper rolls (not wall-clock noise)."""
    payload = {
        "asof": report.get("asof"),
        "equity": report.get("equity"),
        "signals": [
            {
                "code": s.get("code"),
                "selected": s.get("selected"),
                "direction": s.get("direction"),
                "close": s.get("close"),
                "atr": s.get("atr"),
                "stop": s.get("stop"),
                "target": s.get("target"),
                "lots_l1": s.get("lots_l1"),
            }
            for s in (report.get("signals") or [])
            if isinstance(s, dict)
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


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
        "exit_condition": exit_condition_text(
            pos,
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
    opened = {
        "code": str(sig.get("code") or "").upper(),
        "direction": direction,
        "lots": lots,
        "entry": close,
        "stop": stop,
        "target": target,
        "atr": atr,
        "stop_atr_mult": stop_atr_mult,
        "reward_rr": reward_rr,
        "r20": sig.get("r20"),
        "r60": sig.get("r60"),
        "bucket": sig.get("bucket"),
        "sleeve": sleeve,
        "reason": reason,
        "entry_date": _ymd(sig.get("bar_date") or ""),
    }
    opened["exit_condition"] = exit_condition_text(
        opened, stop_atr_mult=stop_atr_mult, reward_rr=reward_rr
    )
    return opened


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
    # Corrupt book must fail loudly (never silent reseed → wipe ledger).
    if paper_path.is_file():
        try:
            json.loads(paper_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "error": f"corrupt paper_book_latest.json: {exc}",
                "path": str(paper_path),
            }

    prev_paper = _load(paper_path) or {}
    if prev_paper.get("engine") == "R5b":
        return {
            "ok": False,
            "error": "R5b engine book: advanced by daily_update's engine path, not the legacy refresh",
            "path": str(paper_path),
        }
    prev_asof = _norm_asof(prev_paper.get("asof_ymd") or prev_paper.get("asof"))
    if prev_asof and asof and asof < prev_asof:
        return {
            "ok": False,
            "error": f"stale l1 asof {asof} < paper asof {prev_asof}",
            "path": str(paper_path),
            "asof": asof_iso,
        }

    fp = _report_fingerprint(report)
    if (
        prev_paper.get("ok")
        and prev_asof
        and asof
        and prev_asof == asof
        and prev_paper.get("l1_fingerprint") == fp
    ):
        # Idempotent: same day + same signal fingerprint → no-op.
        out = dict(prev_paper)
        out["ok"] = True
        out["noop"] = True
        out["l1_fingerprint"] = fp
        out["notes"] = (
            str(out.get("notes") or "")
            + " · refresh no-op（同 asof + 同 l1 指纹，防双跑改账）。"
        ).strip(" ·")
        return out

    params = _exec_params()
    positions, meta, ledger = _seed_positions()
    sigs = _signal_map(report)
    mults = _mult_map(root)
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
        pos["stop_atr_mult"] = pos.get("stop_atr_mult", params["stop_atr_mult"])
        pos["reward_rr"] = pos.get("reward_rr", params["reward_rr"])
        pos["exit_condition"] = exit_condition_text(
            pos,
            stop_atr_mult=params["stop_atr_mult"],
            reward_rr=params["reward_rr"],
        )
        sig = sigs.get(code)
        # 1) Intraday stop/target on asof 15m (before signal exit).
        reason, exit_px = _intraday_stop_exit(pos, root=root, asof_iso=asof_iso)
        if reason is None:
            reason = _should_exit(pos, sig)
            exit_px = (sig or {}).get("close") if reason else None
        if reason:
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
            appended = _append_ledger(ledger, detail)
            if appended and detail.get("equity_delta") is not None:
                equity = float(equity) + float(detail["equity_delta"])
                detail["equity_after"] = round(equity, 2)
            if appended:
                closed_today.append(detail)
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
            pos["exit_condition"] = exit_condition_text(
                pos,
                stop_atr_mult=params["stop_atr_mult"],
                reward_rr=params["reward_rr"],
            )
        kept[code] = pos

    opened = 0
    skipped_today: list[dict] = []
    cap_params = _cap_params()
    for code, sig in sigs.items():
        if code in kept:
            continue
        fresh = _open_from_signal(
            sig,
            stop_atr_mult=params["stop_atr_mult"],
            reward_rr=params["reward_rr"],
        )
        if fresh:
            # R4: re-check the caps against the book that survived today's exits.
            _mult = mults.get(code) or sig.get("mult")
            _why = caps_book_check(kept, fresh, equity=equity, caps=cap_params, mult=_mult)
            if _why:
                skipped_today.append(
                    {"code": code, "skip_reason": "caps_book", "detail": _why, "lots": fresh.get("lots")}
                )
                continue
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
        "skipped_today": skipped_today,
        "trade_ledger": ledger,
        "opened_n": opened,
        "closed_n": len(closed_today),
        "held_n": len(kept),
        "ledger_n": len(ledger),
        "notes": (
            "纸面模拟仓：以回测期末持仓为种子，按最新 l1_report 做信号平仓/组合入选开仓；"
            "持仓先按当日15m触及止盈止损平仓，否则按收盘信号/趋势失效平仓；"
            "每条持仓含 exit_condition（平仓条件）；"
            "trade_ledger 含入场/出场/止盈止损/策略/权益增减（平仓为已实现，持仓中为浮动）；"
            "equity 为平仓累计后账面，equity_floating 为未平仓浮动盈亏。"
            "不改写 historical_backtest KPI。与 Notion 持仓中、决策页账面同源。"
        ),
        "l1_asof": asof,
        "l1_fingerprint": fp,
        "updated_from_l1": True,
        "noop": False,
    }
    _atomic_write_json(paper_path, out)
    return out


# --------------------------------------------------------------------------- R5b engine book
#
# A book with ``"engine": "R5b"`` is run through ``book_core.PositionEngine`` — the same position
# management and T+1 fill code as ``historical_backtest.simulate``:
#   day T  : fill the pending orders of T-1 at T's open (next_open_fill), manage every open
#            position on T (incl. the ones just filled; 15m first touch, daily-OHLC fallback,
#            roll, signal exit, delivery / freeze), then caps on the remaining book → new pending.
#   equity : mark-to-market, net of every fill cost (= simulate's equity, except that the entry
#            costs of today's pending orders are charged when they fill tomorrow).
# Books without the tag (the legacy root book) keep using ``refresh_paper_book``.

ENGINE_TAG = "R5b"
BACKFILL_TAG = "backfill_R5"
STRATEGY_ZH.setdefault("path_a_rr2", "Path-A 日信号组合入选")


def is_engine_book(book: dict | None) -> bool:
    return isinstance(book, dict) and book.get("engine") == ENGINE_TAG


def engine_settings(p: dict | None = None) -> dict[str, Any]:
    """Engine / caps / sizing parameters exactly as ``historical_backtest._simulate_cfg`` passes them."""
    import historical_backtest as hb

    p = p or hb._load_cfg()
    cost_scenario = str(p.get("cost_scenario") or "base").strip().lower()
    slip = p.get("slippage_ticks")
    if slip is None:
        try:
            slip = hb.load_slippage_ticks(hb.ROOT, scenario=cost_scenario)
        except Exception:  # noqa: BLE001
            slip = hb.load_slippage_ticks(hb.ROOT)
    fee_mult = abs(float(p.get("fee_mult") if p.get("fee_mult") is not None else 1.0))
    if fee_mult == 1.0 and cost_scenario != "base":
        try:
            from research.execution.cost_model import load_cost_scenario as _lcs

            fee_mult = float(_lcs(cost_scenario, root=hb.ROOT).get("fee_mult") or 1.0)
        except Exception:  # noqa: BLE001
            pass
    freeze_fix = bool(p.get("freeze_fix", True))
    fill_price = str(p.get("fill_price") or hb.DEFAULT_FILL_PRICE)
    if fill_price != "next_open":
        raise ValueError(f"R5b paper book needs fill_price=next_open (got {fill_price})")
    mode = p["entry_filter"]
    return {
        "engine": {
            "mode": mode,
            "freeze_fix": freeze_fix,
            "delivery_guard": bool(p.get("delivery_guard", True)),
            "max_stale_days": p.get("max_stale_days", hb.MAX_STALE_DAYS),
            "fill_price": fill_price,
            "slippage_ticks": float(slip),
            "fee_mult": fee_mult,
            "enforce_tradability": bool(p.get("enforce_tradability", True)),
            "entry_delivery_buffer": p.get("entry_delivery_buffer", hb.ENTRY_DELIVERY_BUFFER),
            "entry_delivery_action": str(p.get("entry_delivery_action", hb.ENTRY_DELIVERY_ACTION)),
            "option_hedge": bool(p.get("option_hedge")),
            "premium_atr_mult": float(p.get("premium_atr_mult") or 0.0),
            "strike_atr_mult": float(p.get("strike_atr_mult") or 0.0),
            "max_positions": int(p["max_positions"]),
            "max_per_bucket": int(p["max_per_bucket"]),
        },
        "caps": {
            "mode": mode,
            "max_positions": int(p["max_positions"]),
            "max_gross_pct": float(p["max_gross_pct"]),
            "max_port_risk": float(p["max_port_risk"]),
            "max_per_bucket": int(p["max_per_bucket"]),
            "min_r20": float(p["min_r20"]),
            "min_r60": float(p["min_r60"]),
            "min_lots": int(p.get("min_lots") or 0),
            "use_book_caps": freeze_fix,
        },
        "sizing": {
            "equity0": float(p["equity0"]),
            "compound": bool(p["compound"]),
            "risk_pct": float(p["risk_pct"]),
            "l1_mult": float(p["l1_mult"]),
        },
        "stop_atr_mult": float(p["stop_atr_mult"]),
        "reward_rr": float(p["reward_rr"]),
    }


def build_engine(
    series: dict,
    settings: dict,
    *,
    main_map: Any = None,
    adj: dict | None = None,
    curves: dict | None = None,
    contract_root: Path | None = None,
    minute_root: Path | None = None,
):
    from book_core import PositionEngine

    return PositionEngine(
        series=series,
        main_map=main_map,
        adj=adj,
        curves=curves,
        contract_root=contract_root,
        minute_root=minute_root,
        **settings["engine"],
    )


def sizing_for(equity: float, settings: dict) -> tuple[float, float]:
    """(sizing equity, daily risk budget) like simulate: compound_equity → risk_budget_yuan."""
    from position_rules import compound_equity, risk_budget_yuan

    s = settings["sizing"]
    eq = compound_equity(equity, s["equity0"], s["compound"])
    return eq, risk_budget_yuan(eq, s["risk_pct"], s["l1_mult"])


def roll_book(
    state: dict,
    eng: Any,
    day: str,
    *,
    prev_day: str | None,
    next_day: str | None,
) -> dict[str, Any]:
    """One trading day of the engine book (fills of the pending orders, then management).

    ``state``: ``{"positions": {code: pos}, "pending": [cand], "equity": float}`` (not mutated).
    ``sizing_equity`` in the result = equity after today's fills, before today's PnL (what
    simulate sizes ``day``'s signals with)."""
    import historical_backtest as hb

    pos: dict[str, dict] = deepcopy(state.get("positions") or {})
    pending = [dict(c) for c in (state.get("pending") or [])]
    equity0 = float(state["equity"])
    fill_cost = 0.0
    filled: list[dict] = []
    rejected: list[dict] = []
    waiting: list[dict] = []
    groups: dict[str, list[dict]] = {}
    for c in pending:
        groups.setdefault(str(c.get("signal_date") or ""), []).append(c)
    for sd in sorted(groups):
        ready: list[dict] = []
        for c in groups[sd]:
            code = str(c.get("code") or "")
            ix = eng.idx.get(code) or {}
            if code not in eng.series or sd not in ix:
                rejected.append({"code": code, "signal_date": sd, "why": "signal_bar_missing"})
            elif ix[sd] + 1 >= len(eng.series[code]["hist"]):
                waiting.append(c)  # no bar after the signal day yet (code not traded / data late)
            else:
                ready.append(c)
        if not ready:
            continue
        why_by: dict[str, str] = {}
        acc = {"price_pnl": 0.0, "day_cost": 0.0}
        entered, _ = eng.fill_selected(
            ready, pos, sd, acc=acc, on_reject=lambda c_, why: why_by.__setitem__(c_["code"], why)
        )
        fill_cost += eng.last_fill_cost
        for c in ready:
            code = c["code"]
            if code in entered:
                p = pos[code]
                meta = eng.series[code]["meta"]
                cost = hb.fill_cost(
                    meta, p["entry"], p["lots"], slippage_ticks=eng.slippage_ticks, fee_mult=eng.fee_mult
                ) + float(p.get("opt_premium") or 0.0)
                p["signal_date"] = sd
                p["pnl_net"] = -cost
                filled.append({"code": code, "signal_date": sd, "entry_cost": cost, "pos": dict(p)})
            else:
                rejected.append(
                    {"code": code, "signal_date": sd, "why": why_by.get(code) or "not_filled(positions_full/no_open)"}
                )
    sizing_equity = equity0 - fill_cost
    acc = {"price_pnl": 0.0, "day_cost": 0.0}
    closed: list[dict] = []
    for code, p in list(pos.items()):
        pp, pc = acc["price_pnl"], acc["day_cost"]
        row = eng.manage(code, p, day, prev_d=prev_day, nxt=next_day, acc=acc)
        p["pnl_net"] = float(p.get("pnl_net") or 0.0) + (acc["price_pnl"] - pp) - (acc["day_cost"] - pc)
        if row is not None:
            closed.append({"row": dict(row), "pos": dict(p)})
            del pos[code]
        elif p.get("last_mark") is not None:
            p["mark"] = p["last_mark"]
    equity = sizing_equity + (acc["price_pnl"] - acc["day_cost"])
    return {
        "day": day,
        "positions": pos,
        "waiting": waiting,
        "filled": filled,
        "rejected": rejected,
        "closed": closed,
        "fill_cost": fill_cost,
        "mgmt_pnl": acc["price_pnl"],
        "mgmt_cost": acc["day_cost"],
        "sizing_equity": sizing_equity,
        "equity": equity,
    }


def plan_entries(
    core: dict[str, dict],
    *,
    eng: Any,
    pos: dict,
    day: str,
    sizing_equity: float,
    settings: dict,
    exclude: set[str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """New pending orders for ``day`` (simulate step 2): candidates from ``signal_core`` results
    (``core[code]`` = ``path_a_candidate`` output), caps on the book that survived today's exits.
    ``sizing_equity`` is already compounded (``sizing_for``)."""
    import historical_backtest as hb
    from position_rules import apply_portfolio_caps

    caps = settings["caps"]
    slots_left = max(0, int(caps["max_positions"]) - len(pos))
    meta: dict[str, Any] = {"slots_left": slots_left, "sizing_equity": sizing_equity, "candidates": []}
    if slots_left <= 0:
        return [], meta
    cands: list[dict] = []
    for code in eng.series:
        if code in pos or code in (exclude or set()):
            continue
        i = eng.idx[code].get(day)
        if i is None or i < hb.WARMUP:
            continue
        res = core.get(code)
        if not res or res.get("status") != "ok" or not res.get("candidate"):
            continue
        cands.append(res["candidate"])
    meta["candidates"] = [c["code"] for c in cands]
    used_g, used_r, held_buckets = eng.book_usage(pos, day)
    eq_ = sizing_equity if sizing_equity > 0 else 1.0
    kw = dict(
        equity=sizing_equity,
        max_positions=slots_left,
        max_per_bucket=int(caps["max_per_bucket"]),
        min_r20_pct=0.0 if caps["mode"] == "ctf" else float(caps["min_r20"]),
        min_r60_pct=0.0 if caps["mode"] == "ctf" else float(caps["min_r60"]),
        min_lots=int(caps["min_lots"]),
    )
    if caps["use_book_caps"]:
        selected, cmeta = apply_portfolio_caps(
            cands,
            max_gross_exposure_pct=max(0.0, float(caps["max_gross_pct"]) - used_g / eq_ * 100.0),
            max_portfolio_risk_pct=max(0.0, float(caps["max_port_risk"]) - used_r / eq_ * 100.0),
            existing_buckets=held_buckets,
            topup=True,
            **kw,
        )
    else:
        selected, cmeta = apply_portfolio_caps(
            cands,
            max_gross_exposure_pct=float(caps["max_gross_pct"]),
            max_portfolio_risk_pct=float(caps["max_port_risk"]),
            topup=False,
            **kw,
        )
    meta.update(cmeta)
    meta["held_book"] = {
        "held_n": len(pos),
        "used_gross_pct": round(used_g / eq_ * 100.0, 2),
        "used_atr_risk_pct": round(used_r / eq_ * 100.0, 2),
        "held_buckets": held_buckets,
        "note": "R5b：先平今天该平的仓，再用剩余持仓算组合上限（与回测同序）",
    }
    out = []
    for c in selected:
        row = dict(c)
        row["signal_date"] = day
        out.append(row)
    return out, meta


def _engine_pos_view(code: str, p: dict, params: dict, mults: dict | None = None) -> dict:
    """Engine position + the display fields older readers expect (mark, mult, equity_delta…)."""
    v = dict(p)
    v["code"] = code
    v["mult"] = v.get("mult") or (mults or {}).get(code)
    if v.get("mark") is None:
        v["mark"] = v.get("last_mark", v.get("entry"))
    v["equity_delta"] = round(float(v.get("pnl_net") or 0.0), 2)
    v["stop_atr_mult"] = v.get("stop_atr_mult", params.get("stop_atr_mult"))
    v["reward_rr"] = v.get("reward_rr", params.get("reward_rr"))
    v["exit_condition"] = (
        exit_condition_text(v, stop_atr_mult=v["stop_atr_mult"], reward_rr=v["reward_rr"])
        .replace("盘中15m触及即平；否则收盘信号/趋势失效平仓。", "")
        + "盘中15m首次触及即平（分钟缺失/与日线不符时按日线高低价判断）；否则收盘信号/趋势失效、交割/冻结平仓。"
    )
    return v


def _state_hash(state: dict) -> str:
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def seed_engine_book(
    *,
    asof: str,
    positions: dict,
    pending: list,
    equity: float,
    equity_realized: float | None = None,
    source: str,
    settings: dict | None = None,
    ledger: list | None = None,
) -> dict[str, Any]:
    """A fresh R5b book (``equity`` = mark-to-market equity incl. unfilled pending orders' costs)."""
    params = {
        "stop_atr_mult": (settings or {}).get("stop_atr_mult"),
        "reward_rr": (settings or {}).get("reward_rr"),
    }
    mults = _mult_map()
    pos = {}
    floating = 0.0
    for code, p in positions.items():
        q = dict(p)
        if q.get("pnl_net") is None:
            mark = q.get("last_mark", q.get("entry"))
            sign = 1 if q.get("direction") == "多" else -1
            q["pnl_net"] = (float(mark) - float(q["entry"])) * sign * float(q["lots"]) * float(mults.get(code) or 0)
        floating += float(q["pnl_net"])
        pos[code] = _engine_pos_view(code, q, params, mults)
    eq_real = float(equity) - floating if equity_realized is None else float(equity_realized)
    return {
        "ok": True,
        "engine": ENGINE_TAG,
        "asof": _ymd(asof),
        "asof_ymd": _norm_asof(asof),
        "source": "paper_book",
        "seed": source,
        "batch": "pathA",
        "stop_atr_mult": params["stop_atr_mult"],
        "reward_rr": params["reward_rr"],
        "equity": round(eq_real, 2),
        "equity_floating": round(floating, 2),
        "equity_mark": round(float(equity), 2),
        "equity_mtm": float(equity),
        "equity_realized": eq_real,
        "positions": pos,
        "pending": [dict(c) for c in pending],
        "closed_today": [],
        "opened_today": [],
        "skipped_today": [],
        "trade_ledger": list(ledger or []),
        "opened_n": 0,
        "closed_n": 0,
        "held_n": len(pos),
        "pending_n": len(pending),
        "ledger_n": len(ledger or []),
        "noop": False,
    }


def _book_state(book: dict) -> dict:
    return {
        "positions": deepcopy(book.get("positions") or {}),
        "pending": [dict(c) for c in (book.get("pending") or [])],
        "equity": float(book.get("equity_mtm", book.get("equity_mark", book.get("equity")))),
        "equity_realized": float(book.get("equity_realized", book.get("equity") or 0.0)),
    }


def advance_engine_book(
    book: dict,
    day: str,
    *,
    engine_for_day,
    plan_for_day,
    prev_day_fn,
    next_day_fn,
    days_between=None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Advance an R5b book to ``day`` and return the new book (pure; nothing written).

    * same ``day`` as the book → recomputed from ``book["base"]`` (the state before ``day``); if the
      result is unchanged the old book is returned with ``noop=True`` (double run never re-books);
    * missed sessions between the book and ``day`` (``days_between(book_asof, day)``) are managed
      day by day; new pending orders are generated for ``day`` only;
    * ``engine_for_day(d)`` → PositionEngine on the bars up to ``d``;
      ``plan_for_day(eng, pos, d, sizing_equity_raw)`` → (pending list, meta)."""
    rolled = roll_engine_book(
        book, day, engine_for_day=engine_for_day, prev_day_fn=prev_day_fn, next_day_fn=next_day_fn,
        days_between=days_between, tag=tag,
    )
    pending, meta = plan_for_day(rolled["_engine"], rolled["positions"], rolled["asof"], rolled["sizing_equity"])
    return attach_pending(book, rolled, pending, meta)


def roll_engine_book(
    book: dict,
    day: str,
    *,
    engine_for_day,
    prev_day_fn,
    next_day_fn,
    days_between=None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Fills + management up to ``day`` (no new pending yet); see ``advance_engine_book``.
    The result carries the transient ``_engine`` (dropped by ``attach_pending``)."""
    if not is_engine_book(book):
        raise ValueError("not an R5b engine book")
    params = {"stop_atr_mult": book.get("stop_atr_mult"), "reward_rr": book.get("reward_rr")}
    day = _ymd(day)
    asof = _ymd(book.get("asof"))
    if asof and day < asof:
        raise ValueError(f"day {day} < book asof {asof}")
    same_day = asof == day
    if same_day and not isinstance(book.get("base"), dict):
        # a seeded book is already at the close of ``day`` (managed + pending): nothing to redo
        out = dict(book)
        out["_engine"] = engine_for_day(day)
        out["noop"] = True
        out["sizing_equity"] = float(book.get("sizing_equity", out.get("equity_mtm")))
        return out
    if same_day:
        base = book.get("base")
        state = {
            "positions": deepcopy(base["positions"]),
            "pending": [dict(c) for c in base["pending"]],
            "equity": float(base["equity"]),
            "equity_realized": float(base["equity_realized"]),
        }
        base_asof = base.get("asof")
        today_ids = set(book.get("today_trade_ids") or [])
        ledger = [dict(r) for r in (book.get("trade_ledger") or []) if str(r.get("trade_id") or "") not in today_ids]
    else:
        state = _book_state(book)
        base_asof = asof
        ledger = [dict(r) for r in (book.get("trade_ledger") or [])]
    base_snapshot = {"asof": base_asof, **deepcopy(state)}
    seq = list(days_between(base_asof, day)) if days_between is not None else [day]
    if not seq or seq[-1] != day:
        seq.append(day)
    mults = _mult_map()
    realized = float(state["equity_realized"])
    closed_today: list[dict] = []
    opened_today: list[dict] = []
    skipped_today: list[dict] = []
    today_ids: list[str] = []
    roll = None
    eng = None
    for d in seq:
        eng = engine_for_day(d)
        roll = roll_book(state, eng, d, prev_day=prev_day_fn(d), next_day=next_day_fn(d))
        for f in roll["filled"]:
            p = f["pos"]
            v = _engine_pos_view(p["code"], p, params, mults)
            row = _detail_row(
                event="建仓", code=p["code"], date=str(p.get("entry_date") or d), pos=v, params=params,
                equity_before=realized, mults=mults,
            )
            row.update(
                {
                    "signal_date": f["signal_date"],
                    "fill_price_basis": p.get("fill_price_basis"),
                    "fill_contract": p.get("fill_contract"),
                    "held_contract": p.get("held_contract"),
                    "entry_cost": round(f["entry_cost"], 2),
                    "engine": ENGINE_TAG,
                }
            )
            if tag:
                row["tag"] = tag
            if _append_ledger(ledger, row):
                today_ids.append(row["trade_id"])
            opened_today.append(row)
        for c in roll["closed"]:
            r, p = c["row"], c["pos"]
            v = _engine_pos_view(r["code"], p, params, mults)
            v["entry"] = r["entry"]
            row = _detail_row(
                event="平仓", code=r["code"], date=d, pos=v, params=params, exit_px=r["exit"],
                exit_reason=r["reason"], equity_before=realized, mults=mults,
            )
            realized += float(p["pnl_net"])
            row.update(
                {
                    "equity_delta": round(float(p["pnl_net"]), 2),
                    "equity_after": round(realized, 2),
                    "fill_price_basis": r.get("fill_price_basis"),
                    "fill_contract": r.get("fill_contract"),
                    "held_contract": r.get("held_contract"),
                    "roll_events": r.get("roll_events"),
                    "entry_orig": r.get("entry_orig"),
                    "engine": ENGINE_TAG,
                }
            )
            if tag:
                row["tag"] = tag
            if _append_ledger(ledger, row):
                today_ids.append(row["trade_id"])
            closed_today.append(row)
        skipped_today += [dict(x, day=d) for x in roll["rejected"]]
        state = {
            "positions": roll["positions"],
            "pending": roll["waiting"],
            "equity": roll["equity"],
            "equity_realized": realized,
        }
    floating = sum(float(p.get("pnl_net") or 0.0) for p in state["positions"].values())
    out = seed_engine_book(
        asof=day,
        positions=state["positions"],
        pending=state["pending"],
        equity=state["equity"],
        equity_realized=state["equity_realized"],
        source=str(book.get("seed") or "paper_book"),
        settings={"stop_atr_mult": params["stop_atr_mult"], "reward_rr": params["reward_rr"]},
        ledger=ledger,
    )
    out.update(
        {
            "batch": book.get("batch") or "pathA",
            "parent_backtest_end": book.get("parent_backtest_end"),
            "equity_floating": round(floating, 2),
            "sizing_equity": roll["sizing_equity"],
            "closed_today": closed_today,
            "opened_today": opened_today,
            "skipped_today": skipped_today,
            "opened_n": len(opened_today),
            "closed_n": len(closed_today),
            "pending_n": len(state["pending"]),
            "base": base_snapshot,
            "today_trade_ids": today_ids,
            "days_rolled": seq,
            "notes": (
                "R5b 引擎账本：与回测共用持仓管理与 T+1 开仓（book_core）。T 日收盘生成 pending，T+1 开盘成交；"
                "每日先成交 pending，再管理全部持仓（含当日新开）；15m 首触，缺分钟或分钟与日线不符时按日线高低价；"
                "equity_mark/equity_mtm 为逐日盯市扣成本权益；equity 为已实现（equity_mtm − 浮动），equity_floating 为未平仓净盈亏。"
            ),
        }
    )
    out["_engine"] = eng
    return out


def attach_pending(prev_book: dict, rolled: dict, pending: list[dict], meta: dict | None = None) -> dict[str, Any]:
    """Add ``day``'s new pending orders to the rolled book; same day + same state as ``prev_book``
    → ``prev_book`` unchanged with ``noop=True``."""
    if rolled.get("noop"):
        prev = dict(prev_book)
        prev["noop"] = True
        return prev
    out = {k: v for k, v in rolled.items() if k != "_engine"}
    out["pending"] = list(out.get("pending") or []) + [dict(c) for c in pending]
    out["pending_n"] = len(out["pending"])
    meta = meta or {}
    out["plan"] = {k: meta.get(k) for k in ("slots_left", "sizing_equity", "candidates", "held_book", "selected")}
    out["state_fingerprint"] = _state_hash(
        {"asof": out["asof"], "positions": out["positions"], "pending": out["pending"], "equity": out["equity_mtm"],
         "base": out.get("base")}
    )
    if (
        is_engine_book(prev_book)
        and _ymd(prev_book.get("asof")) == out["asof"]
        and prev_book.get("state_fingerprint") == out["state_fingerprint"]
    ):
        prev = dict(prev_book)
        prev["noop"] = True
        return prev
    return out


class SnapshotWorld:
    """Offline replay inputs from a frozen ``bt_input_*.json`` snapshot (bars already stamped with
    the contract overlay, seat / carry books already lagged) + the repo contract / minute caches."""

    def __init__(self, snap_path: Path, *, root: Path | None = None):
        import historical_backtest as hb
        from signal_core import covered_dates

        self.hb = hb
        self.root = Path(root or ROOT)
        self.snap_path = Path(snap_path)
        self.snap = json.loads(self.snap_path.read_text(encoding="utf-8"))
        self.p = hb._load_cfg()
        self.settings = engine_settings(self.p)
        self.meta = {u["code"]: dict(u) for u in self.p["cfg"]["symbols"] if u["code"] in self.snap["bars"]}
        self.curves = {
            c: ({"carry": v} if not (isinstance(v, dict) and "carry" in v) else v)
            for c, v in (self.snap.get("carry") or {}).items()
        }
        full = {c: {"meta": m, "hist": self.snap["bars"][c]} for c, m in self.meta.items()}
        self.days = covered_dates(full)[hb.WARMUP:]

    def bars_upto(self, day: str) -> dict:
        out = {}
        for c in self.meta:
            hist = self.snap["bars"][c]
            k = max((j for j, b in enumerate(hist) if b["date"] <= day), default=None)
            if k is not None:
                out[c] = deepcopy(hist[: k + 1])
        return out

    def engine_for_day(self, day: str):
        from signal_core import build_signal_inputs

        bars = self.bars_upto(day)
        series = {c: {"meta": dict(m), "hist": bars[c]} for c, m in self.meta.items() if c in bars}
        main_map, adj = build_signal_inputs(series, root=self.root)
        eng = build_engine(series, self.settings, main_map=main_map, adj=adj, contract_root=self.root,
                           minute_root=self.root)
        eng._bars = bars
        return eng

    def plan_for_day(self, eng, pos: dict, day: str, sizing_raw: float):
        import daily_update as du

        hb, p = self.hb, self.p
        sizing_eq, risk = sizing_for(sizing_raw, self.settings)
        universe = [dict(m) for c, m in self.meta.items() if c in eng._bars]
        member = self.snap.get("member") or {}
        _sigs, info = du.compute_signals(
            universe, eng._bars, mode=p["entry_filter"], bypass=hb.carry_bypass_cfg(p.get("carry_bypass")),
            vbypass=hb.vol_bypass_cfg(p.get("vol_bypass")), curves=self.curves,
            member_loader=lambda dates, codes: member, risk_budget=risk, lag=0, contract_root=self.root,
            min_seat_days=p.get("min_seat_days", hb.MIN_SEAT_DAYS), observe_min_lots=0, day=day,
            inputs=(eng.main_map, eng.adj),
        )
        return plan_entries(info["core"], eng=eng, pos=pos, day=day, sizing_equity=sizing_eq,
                            settings=self.settings)

    def prev_day(self, d: str):
        k = self.days.index(d)
        return self.days[k - 1] if k > 0 else None

    def next_day(self, d: str):
        k = self.days.index(d)
        return self.days[k + 1] if k + 1 < len(self.days) else None

    def simulate(self, state_log: list | None = None) -> dict:
        """``simulate`` over the snapshot with the snapshot's books (no network)."""
        hb = self.hb
        snap = self.snap
        saved = {k: getattr(hb, k) for k in ("prepare_pack_for_execution", "load_member_seats",
                                              "load_member_changes", "lag_member", "load_curves",
                                              "lag_curves_carry")}
        try:
            hb.prepare_pack_for_execution = lambda pack, root=None: {"fill_series": "snapshot_stamped"}
            hb.load_member_seats = lambda dates, codes: snap["member"]
            hb.load_member_changes = lambda dates, codes: snap["member"]
            hb.lag_member = lambda mm, dates, lag: mm
            hb.load_curves = lambda codes: self.curves
            hb.lag_curves_carry = lambda cv, dates, lag: cv
            series = {c: {"meta": dict(m), "hist": deepcopy(snap["bars"][c])} for c, m in self.meta.items()}
            pack = (series, dict(snap.get("errors") or {}), dict(snap.get("sources") or {}))
            return hb._simulate_cfg(self.p, self.p["entry_filter"], pack=pack, contract_root=self.root,
                                    state_log=state_log)
        finally:
            for k, v in saved.items():
                setattr(hb, k, v)


def _legacy_to_engine_pos(code: str, lp: dict, eng: Any, day: str) -> dict:
    """A legacy paper position (entered at the signal close of ``entry_date``) as an engine
    position joining the book at that close: managed from the next session, marked from ``entry``."""
    i = eng.idx[code][day]
    bar = eng.series[code]["hist"][i]
    p = {
        "code": code,
        "direction": lp["direction"],
        "lots": int(lp["lots"]),
        "entry": float(lp["entry"]),
        "entry_date": day,
        "stop": float(lp["stop"]),
        "target": float(lp["target"]),
        "atr": lp.get("atr"),
        "r20": lp.get("r20"),
        "r60": lp.get("r60"),
        "bucket": lp.get("bucket"),
        "reason": lp.get("reason"),
        "fill_price_basis": "continuous_proxy",
        "last_mark": float(lp["entry"]),
        "stale_days": 0,
    }
    if bar.get("contract"):
        p["fill_contract"] = bar["contract"]
    if eng.main_map is not None and eng.main_map.usable(code):
        p["held_contract"] = eng.main_map.main(code, day)
    for k in ("sleeve",):
        if lp.get(k) is not None:
            p[k] = lp[k]
    return p


def rebuild_preview(book: dict, world: SnapshotWorld) -> dict[str, Any]:
    """R5b repair preview (nothing written to the root book).

    Scheme A (repair): keep the book's history and its open lots (legacy entries at the signal
    close), re-run their management with the shared engine from the session after each entry to
    the last local session (15m first touch + daily fallback, roll, signal / delivery exits, costs);
    closes are tagged ``backfill_R5``; pending orders for the next session from the current code.
    Scheme B (reseed): the backtest's own state on the last local session (open positions, the
    orders selected that day as pending, equity)."""
    hb = world.hb
    params = {"stop_atr_mult": world.settings["stop_atr_mult"], "reward_rr": world.settings["reward_rr"]}
    legacy = {str(k).upper(): dict(v) for k, v in (book.get("positions") or {}).items() if isinstance(v, dict)}
    last = world.days[-1]
    mults = _mult_map()
    # ---- scheme A
    entry_days = sorted({_ymd(v.get("entry_date")) for v in legacy.values()})
    start = entry_days[0] if entry_days else last
    days = [d for d in world.days if start <= d <= last]
    realized0 = float(book.get("equity") or 0.0)
    state = {"positions": {}, "pending": [], "equity": realized0}
    realized = realized0
    ledger = [dict(r) for r in (book.get("trade_ledger") or [])]
    closes: list[dict] = []
    added: list[dict] = []
    stats = {k: 0 for k in ("minute_exit_n", "daily_exit_fallback_n", "minute_rejected_mismatch")}
    eng = None
    for d in days:
        eng = world.engine_for_day(d)
        roll = roll_book(state, eng, d, prev_day=world.prev_day(d), next_day=world.next_day(d))
        for k in stats:
            stats[k] += eng.stats[k]
        for c in roll["closed"]:
            r, p = c["row"], c["pos"]
            v = _engine_pos_view(r["code"], p, params, mults)
            v["entry"] = r["entry"]
            row = _detail_row(event="平仓", code=r["code"], date=d, pos=v, params=params, exit_px=r["exit"],
                              exit_reason=r["reason"], equity_before=realized, mults=mults)
            realized += float(p["pnl_net"])
            row.update({"equity_delta": round(float(p["pnl_net"]), 2), "equity_after": round(realized, 2),
                        "fill_price_basis": r.get("fill_price_basis"), "fill_contract": r.get("fill_contract"),
                        "held_contract": r.get("held_contract"), "engine": ENGINE_TAG, "tag": BACKFILL_TAG})
            _append_ledger(ledger, row)
            added.append(row)
            closes.append({
                "code": r["code"], "direction": r["direction"], "lots": r["lots"], "entry_date": r["entry_date"],
                "entry": r["entry"], "stop": r["stop"], "target": r["target"], "exit_date": d, "exit": r["exit"],
                "reason": r["reason"], "pnl_net": round(float(p["pnl_net"]), 2),
                "minute_checks_that_day": eng.stats["minute_manage_checks"],
                "daily_fallback_that_day": eng.stats["daily_exit_fallback_n"],
                "bar": {k: eng.series[r["code"]]["hist"][eng.idx[r["code"]][d]].get(k)
                        for k in ("date", "open", "high", "low", "close", "contract")},
            })
        positions = roll["positions"]
        equity = roll["equity"]
        for code, lp in legacy.items():
            if _ymd(lp.get("entry_date")) != d:
                continue
            p = _legacy_to_engine_pos(code, lp, eng, d)
            cost = hb.fill_cost(eng.series[code]["meta"], p["entry"], p["lots"],
                                slippage_ticks=eng.slippage_ticks, fee_mult=eng.fee_mult)
            p["pnl_net"] = -cost
            p["entry_cost_backfill"] = cost
            positions[code] = p
            equity -= cost
        state = {"positions": positions, "pending": [], "equity": equity}
    pend_a, meta_a = world.plan_for_day(eng, state["positions"], last, state["equity"])
    book_a = seed_engine_book(asof=last, positions=state["positions"], pending=pend_a, equity=state["equity"],
                              equity_realized=realized, source="rebuild_preview:A_repair", settings=params,
                              ledger=ledger)
    book_a.update({"batch": book.get("batch") or "pathA", "parent_backtest_end": book.get("parent_backtest_end"),
                   "sizing_equity": state["equity"], "plan": {k: meta_a.get(k) for k in ("slots_left", "candidates", "held_book")}})
    # ---- scheme B
    slog: list = []
    res = world.simulate(state_log=slog)
    e = slog[-1]
    assert e["date"] == last, (e["date"], last)
    pos_b = {c: deepcopy(q) for c, q in e["pos"].items() if str(q.get("entry_date") or "") <= last}
    pend_b = [dict(c, signal_date=last) for c in e["selected"]]
    book_b = seed_engine_book(asof=last, positions=pos_b, pending=pend_b, equity=e["equity"] + e["entry_cost"],
                              source="rebuild_preview:B_reseed_backtest", settings=params, ledger=[])
    book_b.update({"batch": "pathA", "parent_backtest_end": last, "sizing_equity": e["equity"] + e["entry_cost"]})

    def _summ(b):
        return {
            "asof": b["asof"],
            "equity_mtm": round(b["equity_mtm"], 2),
            "equity_realized": round(b["equity_realized"], 2),
            "equity_floating": b["equity_floating"],
            "positions": {c: {k: q.get(k) for k in ("direction", "lots", "entry_date", "entry", "stop", "target",
                                                   "last_mark", "fill_price_basis", "held_contract", "pnl_net")}
                          for c, q in b["positions"].items()},
            "pending": [{k: c.get(k) for k in ("code", "direction", "lots", "entry", "stop", "target", "signal_date",
                                                "reason")} for c in b["pending"]],
        }

    sa, sb = _summ(book_a), _summ(book_b)
    return {
        "generated_by": "paper_book.py --rebuild-preview (R5b)",
        "snapshot": str(world.snap_path.name),
        "last_local_session": last,
        "note": "预览，不写根目录 paper_book_latest.json；正式写入待 R7 签字。",
        "legacy_book": {
            "asof": book.get("asof"),
            "equity_realized": book.get("equity"),
            "equity_mark": book.get("equity_mark"),
            "positions": {c: {k: v.get(k) for k in ("direction", "lots", "entry_date", "entry", "stop", "target",
                                                   "mark")} for c, v in legacy.items()},
        },
        "scheme_A_repair": {
            **sa,
            "replayed_sessions": days,
            "closes": closes,
            "ledger_rows_added": added,
            "engine_stats": stats,
            "costs_note": "旧账本从未扣成本；回补时对 P/I 按回测成本模型扣开仓+平仓成本。",
        },
        "scheme_B_reseed": {
            **sb,
            "backtest_window": [world.days[0], last],
            "backtest_ret_pct": res.get("ret_pct"),
            "backtest_closed_n": len(res.get("closed_pnls") or []),
            "ledger_note": "账本历史不继承（旧 trade_ledger 归档保留，另起 R5b 账本）",
        },
        "comparison": {
            "equity_mtm_A_minus_B": round(sa["equity_mtm"] - sb["equity_mtm"], 2),
            "positions_A": sorted(sa["positions"]),
            "positions_B": sorted(sb["positions"]),
            "pending_A": [(c["code"], c["direction"], c["lots"]) for c in sa["pending"]],
            "pending_B": [(c["code"], c["direction"], c["lots"]) for c in sb["pending"]],
        },
        "_books": {"A": book_a, "B": book_b},
    }


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
            "engine": paper.get("engine"),
            "pending": [dict(c) for c in (paper.get("pending") or []) if isinstance(c, dict)],
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


def _rebuild_cli(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="R5b paper book rebuild preview (never writes the root book)")
    ap.add_argument("--rebuild-preview", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--book", default=str(PAPER_PATH), help="book to repair (read-only)")
    ap.add_argument("--snapshot", default=None, help="bt_input snapshot (default: newest archive/snapshots/bt_input_*.json)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.resolve() == PAPER_PATH.resolve():
        ap.error("--out must not be the root paper_book_latest.json")
    snap = Path(args.snapshot) if args.snapshot else max((ROOT / "archive/snapshots").glob("bt_input_*.json"))
    book = _load(Path(args.book))
    if not book:
        ap.error(f"cannot read {args.book}")
    prev = rebuild_preview(book, SnapshotWorld(snap))
    books = prev.pop("_books")
    for k, b in books.items():
        path = out.with_name(f"{out.stem}_book{k}.json")
        _atomic_write_json(path, b)
        prev[f"scheme_{'A_repair' if k == 'A' else 'B_reseed'}"]["book_file"] = str(path.name)
    _atomic_write_json(out, prev)
    a, b = prev["scheme_A_repair"], prev["scheme_B_reseed"]
    print(f"[rebuild] last session {prev['last_local_session']} → {out}")
    for c in a["closes"]:
        print(f"  A close {c['code']} {c['direction']} {c['exit_date']} @{c['exit']} {c['reason']} pnl={c['pnl_net']}")
    print(f"  A equity_mtm={a['equity_mtm']} held={sorted(a['positions'])} pending={prev['comparison']['pending_A']}")
    print(f"  B equity_mtm={b['equity_mtm']} held={sorted(b['positions'])} pending={prev['comparison']['pending_B']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if "--rebuild-preview" in argv:
        return _rebuild_cli(argv)
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
