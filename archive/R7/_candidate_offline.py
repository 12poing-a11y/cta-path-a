# -*- coding: utf-8 -*-
"""R7a step 5/6: offline work on the candidate formal run (snapshot + its contract bundle only).

1. Base re-simulation via SnapshotWorld(candidate snapshot) with state_log → must equal candidate_bt.json.
2. Scheme B book from the last state_log entry → archive/R7/paper_book_candidate.json;
   root paper_book_latest.json copied to archive/R7/paper_book_legacy_pre_R7.json (read-only copy).
3. Stress re-simulation (cost_scenario=stress) → full KPI set; compared with the formal stress row.
4. KPI tables for Base / Stress → archive/R7/candidate_kpis.json.
"""
from __future__ import annotations

import json
import shutil
import statistics
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "archive" / "R7"
CMP_KEYS = ["ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan", "closed_trades", "trade_win_rate",
            "expectancy_r", "exits", "proxy_entry_n", "contract_entry_n", "same_day_exit_n",
            "minute_stop_exits", "daily_exit_fallback_checks", "equity_end", "caps_scaled_n",
            "caps_topup_lots", "caps_entry_risk_max", "caps_entry_gross_max", "roll_open_gap_stops"]


def kpis(out: dict, mults: dict) -> dict:
    cp = out.get("closed_pnls") or []
    days = [r["date"] for r in out.get("equity_curve") or []]
    pos = {d: i for i, d in enumerate(days)}
    eq = {r["date"]: float(r.get("equity") or r.get("value") or 0) for r in out.get("equity_curve") or []}
    held = [pos[t["date"]] - pos[t["entry_date"]] for t in cp if t["date"] in pos and t["entry_date"] in pos]
    gap = [t for t in cp if t["reason"] == "stop" and abs(float(t["exit"]) - float(t["stop"])) > 1e-6]
    risk = []
    for t in cp:
        prev = [d for d in days if d < t["entry_date"]]
        e0 = eq.get(prev[-1]) if prev else out.get("equity_start")
        if e0:
            risk.append(abs(float(t["entry"]) - float(t["stop"])) * int(t["lots"]) * mults.get(t["code"], 1) / e0 * 100)
    return {
        "ret_pct": out.get("ret_pct"),
        "gross_ret_pct": out.get("gross_ret_pct"),
        "max_dd_pct": out.get("max_dd_pct"),
        "gross_max_dd_pct": out.get("gross_max_dd_pct"),
        "cost_yuan": out.get("cost_yuan"),
        "closed_trades": out.get("closed_trades"),
        "trade_win_rate": out.get("trade_win_rate"),
        "expectancy_r": out.get("expectancy_r"),
        "avg_hold_sessions": round(statistics.mean(held), 2) if held else None,
        "median_hold_sessions": statistics.median(held) if held else None,
        "same_day_exit_n": out.get("same_day_exit_n"),
        "same_day_exit_share": out.get("same_day_exit_share"),
        "proxy_entry_n": out.get("proxy_entry_n"),
        "proxy_entry_share": out.get("proxy_entry_share"),
        "contract_entry_n": out.get("contract_entry_n"),
        "exits": out.get("exits"),
        "exit_reasons": dict(Counter(t["reason"] for t in cp)),
        "gap_stops_n": len(gap),
        "gap_stops": [{k: t[k] for k in ("code", "date", "direction", "stop", "exit", "R")} for t in gap],
        "minute_stop_exits": out.get("minute_stop_exits"),
        "roll_open_gap_stops": out.get("roll_open_gap_stops"),
        "caps": {k: out.get(k) for k in ("caps_entry_days", "caps_entry_gross_max", "caps_entry_risk_max",
                                          "caps_scaled_n", "caps_topup_lots", "caps_topup_revived",
                                          "caps_drift_days_gt55")},
        "median_trade_risk_pct": round(statistics.median(risk), 3) if risk else None,
        "roll_shifted": out.get("roll_shifted"),
        "equity_end": out.get("equity_end"),
    }


def main() -> int:
    import paper_book as pb

    cand = json.loads((OUT / "candidate_bt.json").read_text(encoding="utf-8"))
    snap_path = ROOT / cand["input_snapshot"]["path"]
    world = pb.SnapshotWorld(snap_path)
    print(f"[offline] snapshot {snap_path.name} store={world.store!r} days {world.days[0]}..{world.days[-1]}")
    mults = {c: float(m.get("mult") or m.get("multiplier") or 1) for c, m in world.meta.items()}

    slog: list = []
    base = world.simulate(state_log=slog)
    diff = {k: (cand.get(k), base.get(k)) for k in CMP_KEYS if cand.get(k) != base.get(k)}
    print(f"[offline] base re-sim vs candidate diffs: {diff or 'none'}")

    last = world.days[-1]
    e = slog[-1]
    assert e["date"] == last, (e["date"], last)
    params = {"stop_atr_mult": world.settings["stop_atr_mult"], "reward_rr": world.settings["reward_rr"]}
    pos_b = {c: deepcopy(q) for c, q in e["pos"].items() if str(q.get("entry_date") or "") <= last}
    pend_b = [dict(c, signal_date=last) for c in e["selected"]]
    book = pb.seed_engine_book(asof=last, positions=pos_b, pending=pend_b, equity=e["equity"] + e["entry_cost"],
                               source="R7a:B_reseed_candidate_backtest", settings=params, ledger=[])
    book.update({"batch": "pathA", "parent_backtest_end": last, "sizing_equity": e["equity"] + e["entry_cost"],
                 "parent_backtest": "archive/R7/candidate_bt.json",
                 "parent_snapshot": cand["input_snapshot"]["path"]})
    (OUT / "paper_book_candidate.json").write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / "paper_book_latest.json", OUT / "paper_book_legacy_pre_R7.json")

    sp = dict(world.p)
    from research.execution.cost_model import load_cost_scenario

    sc = load_cost_scenario("stress", root=ROOT)
    world.p = {**sp, "slippage_ticks": sc["slippage_ticks"], "fee_mult": sc["fee_mult"], "cost_scenario": "stress"}
    stress = world.simulate()
    world.p = sp
    srow = (cand.get("cost_scenario_contrast") or {}).get("rows", {}).get("stress") or {}
    sdiff = {k: (srow.get(k), stress.get(k)) for k in ("ret_pct", "gross_ret_pct", "max_dd_pct", "cost_yuan",
                                                         "closed_trades") if srow.get(k) != stress.get(k)}
    print(f"[offline] stress re-sim vs formal stress row diffs: {sdiff or 'none'}")

    summary = {
        "asof": book["asof"],
        "equity_mtm": round(book["equity_mtm"], 2),
        "equity_realized": round(book["equity_realized"], 2),
        "positions": {c: {k: q.get(k) for k in ("direction", "lots", "entry_date", "entry", "stop", "target",
                                               "last_mark", "fill_price_basis", "fill_contract", "held_contract")}
                      for c, q in book["positions"].items()},
        "pending": [{k: c.get(k) for k in ("code", "direction", "lots", "entry", "stop", "target", "signal_date")}
                    for c in book["pending"]],
    }
    res = {
        "candidate": "archive/R7/candidate_bt.json",
        "snapshot": cand["input_snapshot"]["path"],
        "store": repr(world.store),
        "base_resim_diffs": diff,
        "stress_resim_vs_formal_row_diffs": sdiff,
        "base": kpis(cand, mults),
        "stress": kpis(stress, mults),
        "scheme_B_book": summary,
    }
    (OUT / "candidate_kpis.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("base_resim_diffs", "stress_resim_vs_formal_row_diffs", "scheme_B_book")},
                     ensure_ascii=False, indent=1))
    return 0 if not diff else 1


if __name__ == "__main__":
    raise SystemExit(main())
