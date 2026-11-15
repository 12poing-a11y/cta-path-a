"""Shadow replay of formal Path-A backtest from input snapshot (no network, no formal overwrite)."""
import json, sys, copy
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import historical_backtest as hb

SNAP = ROOT / "archive/snapshots/bt_input_20261113_d246813d911a.json"
snap = json.loads(SNAP.read_text())
formal = json.loads((ROOT / "historical_backtest_latest.json").read_text())

def make_pack(bars=None):
    p = hb._load_cfg()
    bars = bars or snap["bars"]
    series = {}
    for u in p["cfg"]["symbols"]:
        c = u["code"]
        if c in bars:
            series[c] = {"meta": dict(u), "hist": copy.deepcopy(bars[c])}
    return p, (series, dict(snap.get("errors") or {}), dict(snap.get("sources") or {}))

# freeze: overlay already stamped in snapshot; member/carry already post-lag
hb.prepare_pack_for_execution = lambda pack, root=None: formal.get("contract_pack") or {}
hb.load_member_seats = lambda dates, codes: snap["member"]
hb.load_member_changes = lambda dates, codes: snap["member"]
hb.lag_member = lambda m, dates, lag: m
hb.load_curves = lambda codes: {c: {"carry": v} if not (isinstance(v, dict) and "carry" in v) else v for c, v in snap["carry"].items()}
hb.lag_curves_carry = lambda curves, dates, lag: curves

def run(p=None, pack=None, **kw):
    if p is None or pack is None:
        p, pack = make_pack()
    mode = p["entry_filter"]
    return hb._simulate_cfg(p, mode, pack=pack, **kw)

if __name__ == "__main__":
    p, pack = make_pack()
    out = run(p, pack)
    keys = ["ret_pct","max_dd_pct","closed_trades","trade_win_rate","expectancy_r","exits","proxy_entry_n","contract_entry_n","same_day_exit_n","conclusion"]
    print({k: out.get(k) for k in keys})
    print("formal", {k: formal.get(k) for k in keys})
