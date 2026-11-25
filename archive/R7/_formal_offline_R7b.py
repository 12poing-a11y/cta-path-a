# -*- coding: utf-8 -*-
"""R7b step 5/3: scheme-B seed from the FORMAL root run (same method as _candidate_offline.py).

1. Base re-sim via SnapshotWorld(formal snapshot) with state_log -> must equal root historical_backtest_latest.json.
2. Scheme B book from the last state_log entry -> archive/R7/paper_book_R7b_candidate.json and root paper_book_latest.json.
3. Stress re-sim vs formal stress row -> archive/R7/formal_kpis_R7b.json.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "archive" / "R7"
CMP_KEYS = ["ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan", "closed_trades", "trade_win_rate",
            "expectancy_r", "exits", "proxy_entry_n", "contract_entry_n", "same_day_exit_n",
            "minute_stop_exits", "daily_exit_fallback_checks", "equity_end", "caps_scaled_n",
            "caps_topup_lots", "caps_entry_risk_max", "caps_entry_gross_max", "roll_open_gap_stops"]


def main() -> int:
    import paper_book as pb
    from research.execution.cost_model import load_cost_scenario

    formal = json.loads((ROOT / "historical_backtest_latest.json").read_text(encoding="utf-8"))
    snap_path = ROOT / formal["input_snapshot"]["path"]
    world = pb.SnapshotWorld(snap_path)
    print(f"[formal-offline] snapshot {snap_path.name} store={world.store!r} days {world.days[0]}..{world.days[-1]}")

    slog: list = []
    base = world.simulate(state_log=slog)
    diff = {k: (formal.get(k), base.get(k)) for k in CMP_KEYS if formal.get(k) != base.get(k)}
    print(f"[formal-offline] base re-sim vs formal diffs: {diff or 'none'}")

    last = world.days[-1]
    e = slog[-1]
    assert e["date"] == last, (e["date"], last)
    params = {"stop_atr_mult": world.settings["stop_atr_mult"], "reward_rr": world.settings["reward_rr"]}
    pos_b = {c: deepcopy(q) for c, q in e["pos"].items() if str(q.get("entry_date") or "") <= last}
    pend_b = [dict(c, signal_date=last) for c in e["selected"]]
    book = pb.seed_engine_book(asof=last, positions=pos_b, pending=pend_b, equity=e["equity"] + e["entry_cost"],
                               source="R7b:B_reseed_formal_backtest", settings=params, ledger=[])
    book.update({"batch": "pathA", "parent_backtest_end": last, "sizing_equity": e["equity"] + e["entry_cost"],
                 "parent_backtest": "historical_backtest_latest.json",
                 "parent_snapshot": formal["input_snapshot"]["path"]})
    text = json.dumps(book, ensure_ascii=False, indent=2) + "\n"
    (OUT / "paper_book_R7b_candidate.json").write_text(text, encoding="utf-8")
    (ROOT / "paper_book_latest.json").write_text(text, encoding="utf-8")
    print(f"[formal-offline] wrote root paper_book_latest.json asof={book['asof']} equity_mtm={round(book['equity_mtm'], 2)}")

    sp = dict(world.p)
    sc = load_cost_scenario("stress", root=ROOT)
    world.p = {**sp, "slippage_ticks": sc["slippage_ticks"], "fee_mult": sc["fee_mult"], "cost_scenario": "stress"}
    stress = world.simulate()
    world.p = sp
    srow = (formal.get("cost_scenario_contrast") or {}).get("rows", {}).get("stress") or {}
    sdiff = {k: (srow.get(k), stress.get(k)) for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan",
                                                         "closed_trades") if srow.get(k) != stress.get(k)}
    print(f"[formal-offline] stress re-sim vs formal stress row diffs: {sdiff or 'none'}")
    res = {
        "formal": "historical_backtest_latest.json",
        "snapshot": formal["input_snapshot"]["path"],
        "base_resim_diffs": diff,
        "stress_resim_vs_formal_row_diffs": sdiff,
        "base": {k: formal.get(k) for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "closed_trades",
                                            "trade_win_rate", "expectancy_r", "exits")},
        "stress_row": srow,
        "stress_resim": {k: stress.get(k) for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan",
                                                    "closed_trades")},
        "book": {"asof": book["asof"], "equity_mtm": round(book["equity_mtm"], 2),
                 "equity_realized": round(book["equity_realized"], 2),
                 "positions": list(book["positions"].keys()),
                 "pending": [c.get("code") for c in book["pending"]]},
    }
    (OUT / "formal_kpis_R7b.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if not diff else 1


if __name__ == "__main__":
    raise SystemExit(main())
