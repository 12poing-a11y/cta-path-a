# -*- coding: utf-8 -*-
"""T-P1: trade-level shadow attribution + simple regime×strategy matrix.

Research only. Reads formal BT closed_pnls + universe; does not write paper_book.
Regime labels use trailing HV/return on local continuous bars (no HMM fit).
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "cta-shadow-attribution-v1"
OUT_REL = Path("lab") / "research" / "validation" / "shadow_attribution_latest.json"
MIN_CELL = 5


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _universe_meta(root: Path) -> dict[str, dict[str, Any]]:
    path = Path(root) / "universe.json"
    if not path.is_file():
        return {}
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in cfg.get("symbols") or []:
        if isinstance(row, dict) and row.get("code"):
            out[str(row["code"]).upper()] = row
    return out


def _hold_days(entry: str | None, exit_d: str | None) -> int | None:
    if not entry or not exit_d:
        return None
    try:
        from datetime import date

        e = date.fromisoformat(str(entry)[:10])
        x = date.fromisoformat(str(exit_d)[:10])
        return max(0, (x - e).days)
    except ValueError:
        return None


def _hold_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days <= 1:
        return "0-1d"
    if days <= 3:
        return "2-3d"
    if days <= 7:
        return "4-7d"
    if days <= 15:
        return "8-15d"
    return "16d+"


def _pnl_r(trade: dict[str, Any]) -> float | None:
    if trade.get("R") is not None:
        try:
            return float(trade["R"])
        except (TypeError, ValueError):
            pass
    try:
        entry = float(trade["entry"])
        exit_px = float(trade["exit"])
        side = 1 if str(trade.get("direction") or "") in ("多", "long", "Long", "BUY") else -1
        if entry <= 0:
            return None
        return side * (exit_px / entry - 1.0)
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return None


def _load_closes(root: Path, code: str) -> list[tuple[str, float]]:
    path = Path(root) / ".cache" / "history" / f"{code.upper()}0.json"
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[tuple[str, float]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date") or "")[:10]
        try:
            px = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if d and px > 0:
            out.append((d, px))
    out.sort(key=lambda x: x[0])
    return out


def _simple_regime_at(closes: list[tuple[str, float]], asof: str) -> str:
    """Rule labels using only bars dated <= asof (no lookahead)."""
    asof = str(asof or "")[:10]
    hist = [(d, px) for d, px in closes if d <= asof]
    if len(hist) < 25:
        return "unknown"
    px = [p for _, p in hist]
    rets = []
    for i in range(1, len(px)):
        if px[i - 1] > 0:
            rets.append(px[i] / px[i - 1] - 1.0)
    if len(rets) < 20:
        return "unknown"
    r20 = rets[-20:]
    r60 = rets[-60:] if len(rets) >= 60 else rets
    def _std(xs: list[float]) -> float:
        if len(xs) < 2:
            return 0.0
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    hv20 = _std(r20) * math.sqrt(252)
    hv60 = _std(r60) * math.sqrt(252) if len(r60) >= 10 else hv20
    ret20 = sum(r20)
    if hv60 > 1e-12 and hv20 / hv60 >= 1.25:
        return "vol_expand"
    if ret20 >= 0.04:
        return "trend_up"
    if ret20 <= -0.04:
        return "trend_down"
    return "chop"


def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rs = [float(r["R"]) for r in rows if r.get("R") is not None]
    n = len(rs)
    wins = sum(1 for x in rs if x > 0)
    return {
        "n": n,
        "win_rate": round(wins / n, 4) if n else None,
        "avg_R": round(sum(rs) / n, 4) if n else None,
        "sum_R": round(sum(rs), 4) if n else None,
        "enough": bool(n >= MIN_CELL),
    }


def enrich_trades(
    closed_pnls: list[dict[str, Any]],
    *,
    root: Path,
    uni: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    uni = uni or _universe_meta(root)
    close_cache: dict[str, list[tuple[str, float]]] = {}
    out: list[dict[str, Any]] = []
    for t in closed_pnls:
        if not isinstance(t, dict):
            continue
        code = str(t.get("code") or "").upper()
        meta = uni.get(code) or {}
        hold = _hold_days(t.get("entry_date"), t.get("date"))
        if code not in close_cache:
            close_cache[code] = _load_closes(root, code)
        regime = _simple_regime_at(close_cache[code], str(t.get("entry_date") or t.get("date") or ""))
        r = _pnl_r(t)
        out.append(
            {
                "code": code,
                "name": meta.get("name") or code,
                "bucket": meta.get("bucket") or "未分组",
                "direction": t.get("direction"),
                "side": "long" if str(t.get("direction") or "") in ("多", "long", "Long", "BUY") else "short",
                "entry_date": t.get("entry_date"),
                "exit_date": t.get("date"),
                "hold_days": hold,
                "hold_bucket": _hold_bucket(hold),
                "exit_reason": t.get("reason") or "unknown",
                "sleeve": t.get("sleeve") or t.get("entry_reason") or "path_a",
                "fill_price_basis": t.get("fill_price_basis") or "unknown",
                "lots": t.get("lots"),
                "R": None if r is None else round(float(r), 6),
                "regime": regime,
            }
        )
    return out


def build_attribution_tables(trades: list[dict[str, Any]]) -> dict[str, Any]:
    dims = {
        "by_code": "code",
        "by_bucket": "bucket",
        "by_side": "side",
        "by_exit_reason": "exit_reason",
        "by_hold_bucket": "hold_bucket",
        "by_fill_basis": "fill_price_basis",
        "by_sleeve": "sleeve",
        "by_regime": "regime",
    }
    tables: dict[str, list[dict[str, Any]]] = {}
    for name, key in dims.items():
        groups: dict[str, list] = defaultdict(list)
        for t in trades:
            groups[str(t.get(key) or "unknown")].append(t)
        rows = []
        for k, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            rows.append({"key": k, **_agg(items)})
        tables[name] = rows

    # strategy × regime matrix (sleeve × regime)
    matrix_groups: dict[tuple[str, str], list] = defaultdict(list)
    for t in trades:
        matrix_groups[(str(t.get("sleeve") or "path_a"), str(t.get("regime") or "unknown"))].append(t)
    matrix = []
    for (sleeve, regime), items in sorted(matrix_groups.items()):
        matrix.append({"sleeve": sleeve, "regime": regime, **_agg(items)})

    return {
        **tables,
        "regime_x_sleeve": matrix,
    }


def build_shadow_attribution(
    root: Path | None = None,
    *,
    bt_path: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    root = Path(root or Path(__file__).resolve().parents[2])
    path = Path(bt_path) if bt_path else root / "historical_backtest_latest.json"
    if not path.is_file():
        return {"ok": False, "error": "bt_missing", "path": str(path)}
    try:
        bt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    closed = bt.get("closed_pnls") or []
    if not isinstance(closed, list):
        closed = []
    uni = _universe_meta(root)
    trades = enrich_trades(closed, root=root, uni=uni)
    tables = build_attribution_tables(trades)
    report = {
        "ok": True,
        "schema": SCHEMA,
        "built_at": _iso_now(),
        "live_trading": False,
        "source_bt": (
            str(path.relative_to(root))
            if str(path).startswith(str(root))
            else str(path)
        ),
        "bt_window": {"start": bt.get("start"), "end": bt.get("end")},
        "n_trades": len(trades),
        "min_cell": MIN_CELL,
        "proxy_entry_share": bt.get("proxy_entry_share"),
        "cost_yuan": bt.get("cost_yuan"),
        "tables": tables,
        "disclaimer": (
            "Research shadow attribution only · 不改 Path-A / paper_book / seats。"
            f"单格 n<{MIN_CELL} 只展示。"
            "regime=trailing HV/ret 规则标签（非 HMM）。"
        ),
    }
    if write:
        out = root / OUT_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["path"] = str(out.relative_to(root))
    return report
