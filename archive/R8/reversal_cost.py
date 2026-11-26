# -*- coding: utf-8 -*-
"""Per-lot roll cost of the 35 same-magnitude (new-main volume >= 5% of old-main) round-trip rolls left by the 5% guard.
Each reversal A->B->A = 2 extra rolls = 4 extra fills (close A, open B, close B, open A) per lot held.  Read-only; no strategy run."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "archive" / "R8"))
import historical_backtest as hb
from research.execution.cost_model import load_cost_scenario
from contract_loader import load_all
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
by = load_all()
g = json.loads((ROOT / "archive/R8/guard_sensitivity.json").read_text(encoding="utf-8"))
rows = [r for r in g["details"]["5%"]["reversals"] if r[6] == "ge5pct"]
base_p = hb._load_cfg()
sc = {n: load_cost_scenario(n, root=ROOT) for n in ("base", "stress")}
out, tot = [], {"base": 0.0, "stress": 0.0}
for sym, d, a, b, vnew, vold, cls in rows:
    px = (by.get(a, {}).get(d) or {}).get("close") or (by.get(b, {}).get(d) or {}).get("close")
    rec = dict(symbol=sym, date=d, old_main=a, new_main=b, new_vol=vnew, old_vol=vold, px=px)
    for n in ("base", "stress"):
        c1 = hb.fill_cost(meta[sym], float(px), 1, slippage_ticks=sc[n]["slippage_ticks"], fee_mult=sc[n]["fee_mult"])
        rec[f"cost_per_lot_4fills_{n}"] = round(4 * c1, 2)
        tot[n] += 4 * c1
    out.append(rec)
res = dict(n_events=len(rows), total_cost_per_lot_if_held_yuan={k: round(v, 2) for k, v in tot.items()},
           mean_per_event_per_lot_yuan={k: round(v / max(1, len(rows)), 2) for k, v in tot.items()},
           note="cost of the 4 extra fills per reversal event for ONE lot held through it; real cost = x lots held x only when a position was held",
           events=out)
(ROOT / "archive/R8/reversal_cost_35.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print({k: v for k, v in res.items() if k != "events"})
