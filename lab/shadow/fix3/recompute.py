"""fix3 shadow recompute (formal rules, snapshot bt_input_20261113). Writes only lab/shadow/fix3/."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import replay as R, variants as V

KEYS = ["ret_pct","max_dd_pct","closed_trades","trade_win_rate","expectancy_r","exits","freeze_fix","seat_gate","proxy_entry_n","contract_entry_n","same_day_exit_n","avg_held","conclusion"]

def cross_delivery(out):
    from historical_backtest import contract_delivery_ym
    bad = []
    for t in out["closed_pnls"]:
        if t.get("fill_price_basis") != "contract":
            continue
        ym = contract_delivery_ym(t.get("fill_contract"))
        if ym and str(t["date"])[:7] >= ym:
            bad.append((t["code"], t["fill_contract"], t["entry_date"], t["date"], t["reason"], t["R"]))
    return bad

def run_all():
    res = {}
    cases = [
        ("A_legacy_ee4476b", None, dict(freeze_fix=False, min_seat_days=0)),
        ("C_audit_ffill_approx", V.ffill, dict(freeze_fix=False, min_seat_days=0)),
        ("FIX3_proxy_basis_only", None, dict(freeze_fix=True, delivery_guard=False, max_stale_days=10**6, min_seat_days=0)),
        ("FIX3_freeze_fix", None, dict(freeze_fix=True, min_seat_days=0)),
        ("FIX3_full_formal_seatgate60", None, dict(freeze_fix=True)),
    ]
    for name, fn, kw in cases:
        p, pack = R.make_pack(fn(R.snap["bars"]) if fn else None)
        out = R.run(p, pack, **kw)
        r = {k: out.get(k) for k in KEYS}
        r["bysym_R"] = V.bysym(out)
        r["train_1223_0831"] = V.seg_ret(out, "2025-12-23", "2026-08-31")
        r["test_0901_1113"] = V.seg_ret(out, "2026-09-01", "2026-11-13")
        r["cross_delivery_trades"] = cross_delivery(out)
        r["L_FG_trades"] = [(t["code"], t["fill_contract"], t["entry_date"], t["date"], t["reason"], t["R"]) for t in out["closed_pnls"] if t["code"] in ("L", "FG")]
        res[name] = r
        print(name, r["ret_pct"], r["max_dd_pct"], r["closed_trades"], r["exits"], r.get("freeze_fix"), "cross", len(r["cross_delivery_trades"]))
    return res

if __name__ == "__main__":
    res = run_all()
    (HERE / "recompute_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
