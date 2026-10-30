# -*- coding: utf-8 -*-
"""Batch paper sweep of Path-A stop / RR / momentum thresholds.

Reuses ``historical_backtest`` simulate path (no new engine). Writes
``param_sweep_latest.json`` for the desk strategy registry and refreshes
``archive/rr_grid.json`` summary rows.

Usage:
  python param_sweep.py           # stop × reward_rr (default)
  python param_sweep.py --thresh  # also sweep min_r20/min_r60
  python param_sweep.py --from-archive  # rebuild desk JSON from archive/rr_grid.json only
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Compact threshold grid used only with --thresh.
THRESH_GRID = (
    (3.0, 5.0),
    (2.0, 4.0),
    (4.0, 6.0),
)


def _from_archive() -> dict:
    path = ROOT / "archive" / "rr_grid.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    best = raw.get("best") or {}
    rows = raw.get("rows") or []
    out = {
        "ok": True,
        "strategy": "param_sweep",
        "source": "archive/rr_grid.json",
        "entry_filter": "base",
        "stop_atr_mult": best.get("stop_atr_mult"),
        "reward_rr": best.get("reward_rr"),
        "ret_pct": best.get("ret_pct"),
        "max_dd_pct": best.get("max_dd_pct"),
        "trade_win_rate": best.get("trade_win_rate"),
        "breakeven_win_rate": best.get("breakeven_win_rate"),
        "expectancy_r": best.get("expectancy_r"),
        "closed_trades": best.get("closed_trades"),
        "equity_end": best.get("equity_end"),
        "conclusion": best.get("conclusion"),
        "param_sweep_best": best.get("name"),
        "param_sweep": rows,
        "summary": (
            f"扫参归档 best={best.get('name')} "
            f"ret={best.get('ret_pct')} dd={best.get('max_dd_pct')} "
            f"calmar={best.get('calmar')}"
        ),
    }
    return out


def _run(*, with_thresh: bool) -> dict:
    from historical_backtest import (  # noqa: WPS433
        RR_GRID,
        STOP_GRID,
        _fetch_pack,
        _load_cfg,
        _simulate_cfg,
    )

    p = _load_cfg()
    p["equity0"] = float(p["cfg"].get("equity") or 200_000)
    p["min_lots"] = 0
    p["option_hedge"] = False
    p["observe_mode"] = False
    mode = p["entry_filter"] if p["entry_filter"] in (
        "base",
        "p0",
        "carry",
        "oi",
        "member",
        "climax",
        "seats",
    ) else "base"
    pack = _fetch_pack(p["cfg"]["symbols"])
    thresh_list = THRESH_GRID if with_thresh else ((p["min_r20"], p["min_r60"]),)
    rows: list[dict] = []
    saved: dict[str, dict] = {}
    for min_r20, min_r60 in thresh_list:
        for stop in STOP_GRID:
            for rr in RR_GRID:
                tag = f"r{min_r20:g}/{min_r60:g}_stop{stop:g}_rr{rr:g}"
                print(f"[sweep] {tag}")
                cfg = dict(p)
                cfg["min_r20"] = float(min_r20)
                cfg["min_r60"] = float(min_r60)
                one = _simulate_cfg(
                    cfg,
                    mode,
                    pack=pack,
                    option_hedge=False,
                    reward_rr=rr,
                    stop_atr_mult=stop,
                )
                saved[tag] = one
                calmar = None
                if one.get("ok") and one.get("max_dd_pct"):
                    calmar = round(float(one["ret_pct"]) / float(one["max_dd_pct"]), 3)
                rows.append(
                    {
                        "name": tag,
                        "min_r20_pct": min_r20,
                        "min_r60_pct": min_r60,
                        "stop_atr_mult": stop,
                        "reward_rr": rr,
                        "ret_pct": one.get("ret_pct"),
                        "max_dd_pct": one.get("max_dd_pct"),
                        "trade_win_rate": one.get("trade_win_rate"),
                        "breakeven_win_rate": one.get("breakeven_win_rate"),
                        "expectancy_r": one.get("expectancy_r"),
                        "closed_trades": one.get("closed_trades"),
                        "equity_end": one.get("equity_end"),
                        "conclusion": one.get("conclusion"),
                        "calmar": calmar,
                    }
                )
                print(
                    f"  ret={one.get('ret_pct')} dd={one.get('max_dd_pct')} "
                    f"calmar={calmar} {one.get('conclusion')}"
                )
    ranked = [r for r in rows if r.get("calmar") is not None]
    best_row = max(ranked, key=lambda r: (r["calmar"], r["ret_pct"])) if ranked else rows[0]
    out = dict(saved[best_row["name"]])
    out["strategy"] = "param_sweep"
    out["entry_filter"] = mode
    out["param_sweep_best"] = best_row["name"]
    out["param_sweep"] = rows
    out["stop_atr_mult"] = best_row.get("stop_atr_mult")
    out["reward_rr"] = best_row.get("reward_rr")
    out["min_r20_pct"] = best_row.get("min_r20_pct")
    out["min_r60_pct"] = best_row.get("min_r60_pct")
    out["summary"] = (
        f"扫参 best={best_row['name']} calmar={best_row.get('calmar')} "
        f"ret={best_row.get('ret_pct')} dd={best_row.get('max_dd_pct')}"
    )
    (ROOT / "archive").mkdir(exist_ok=True)
    (ROOT / "archive" / "rr_grid.json").write_text(
        json.dumps({"best": best_row, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def main() -> None:
    from_archive = "--from-archive" in sys.argv
    with_thresh = "--thresh" in sys.argv
    if from_archive:
        out = _from_archive()
    else:
        out = _run(with_thresh=with_thresh)
    path = ROOT / "param_sweep_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[sweep] wrote {path.name} best={out.get('param_sweep_best')} {out.get('summary')}")


if __name__ == "__main__":
    main()
