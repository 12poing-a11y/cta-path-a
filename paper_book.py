# -*- coding: utf-8 -*-
"""Incremental Path-A paper book (simulated open lots).

Seeds from ``historical_backtest_latest.json`` → ``final_positions``, then
rolls with the latest ``l1_report.json`` so desk / Notion share one asof.
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


def _seed_positions() -> tuple[dict[str, dict], dict[str, Any]]:
    """Prefer existing paper book; else backtest final_positions."""
    paper = _load(PAPER_PATH)
    if paper and isinstance(paper.get("positions"), dict) and paper.get("ok"):
        pos = {
            str(k).upper(): dict(v)
            for k, v in paper["positions"].items()
            if isinstance(v, dict)
        }
        meta = {
            "parent_backtest_end": str(paper.get("parent_backtest_end") or ""),
            "batch": str(paper.get("batch") or "pathA"),
            "seed": "paper_book_latest",
        }
        return pos, meta

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
    return pos, meta


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
        "reason": "daily_selected",
        "entry_date": _ymd(sig.get("bar_date") or ""),
    }


def refresh_paper_book(
    root: Path | None = None,
    *,
    report: dict | None = None,
) -> dict[str, Any]:
    """Roll open book to l1 asof; write ``paper_book_latest.json``."""
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
    positions, meta = _seed_positions()
    sigs = _signal_map(report)
    closed_today: list[dict] = []
    kept: dict[str, dict] = {}

    for code, pos in positions.items():
        pos = deepcopy(pos)
        pos["code"] = code
        sig = sigs.get(code)
        reason = _should_exit(pos, sig)
        if reason:
            closed_today.append(
                {
                    "code": code,
                    "date": asof_iso,
                    "direction": pos.get("direction"),
                    "lots": pos.get("lots"),
                    "entry": pos.get("entry"),
                    "exit": (sig or {}).get("close"),
                    "reason": reason,
                    "entry_reason": pos.get("reason") or "path_a",
                    "entry_date": pos.get("entry_date"),
                }
            )
            continue
        if sig:
            # Refresh momentum labels only; keep stop/target unless ATR is sane.
            pos["r20"] = sig.get("r20", pos.get("r20"))
            pos["r60"] = sig.get("r60", pos.get("r60"))
            atr = float(sig.get("atr") or 0)
            close = float(sig.get("close") or 0)
            if atr > 0 and close > 0 and atr < close * 0.25:
                pos["atr"] = atr
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
            kept[code] = fresh
            opened += 1

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
        "positions": kept,
        "closed_today": closed_today,
        "opened_n": opened,
        "closed_n": len(closed_today),
        "held_n": len(kept),
        "notes": (
            "纸面模拟仓：以回测期末持仓为种子，按最新 l1_report 做信号平仓/组合入选开仓；"
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
    }


def main() -> int:
    out = refresh_paper_book(ROOT)
    if not out.get("ok"):
        print("[paper] fail:", out.get("error"))
        return 1
    print(
        f"[paper] asof={out.get('asof')} held={out.get('held_n')} "
        f"opened={out.get('opened_n')} closed={out.get('closed_n')} "
        f"→ {PAPER_PATH.name}"
    )
    for code, pos in sorted((out.get("positions") or {}).items()):
        print(f"  {code} {pos.get('direction')} {pos.get('lots')}手")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
