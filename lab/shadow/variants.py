import json, copy, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay as R

KEYS = ["ret_pct","max_dd_pct","closed_trades","trade_win_rate","realized_rr","expectancy_r","exits","proxy_entry_n","contract_entry_n","same_day_exit_n","avg_held","conclusion"]
def strip(bars):
    out = {}
    for c, h in bars.items():
        nh = []
        for b in h:
            b = {k: v for k, v in b.items() if not k.startswith("contract_")}
            b["fill_price_basis"] = b["price_basis"] = "continuous_proxy"
            nh.append(b)
        out[c] = nh
    return out
def ffill(bars):
    out = {}
    for c, h in bars.items():
        nh = []; off = None
        for b in h:
            b = dict(b)
            if b.get("contract_close") is not None:
                off = b["contract_close"] - b["close"]
            elif off is not None:
                for k in ("open","high","low","close"):
                    b["contract_"+k] = b[k] + off
                b["fill_price_basis"] = b["price_basis"] = "contract"; b["ffill_basis"] = True
            nh.append(b)
        out[c] = nh
    return out
def bysym(out):
    by = collections.defaultdict(lambda: [0,0,0.0])
    for t in out["closed_pnls"]:
        b = by[t["code"]]; b[0]+=1; b[1]+= t["R"]>0; b[2]+=t["R"]
    return {k:(v[0],v[1],round(v[2],1)) for k,v in sorted(by.items())}
def seg_ret(out, a, b):
    cur = out["equity_curve"]
    pre = [x for x in cur if x["date"] < a]; seg = [x for x in cur if a <= x["date"] <= b]
    e0 = pre[-1]["equity"] if pre else cur[0]["equity"]; e1 = seg[-1]["equity"]
    peak=e0; dd=0
    for x in seg:
        peak=max(peak,x["equity"]); dd=max(dd,(peak-x["equity"])/peak*100)
    n=sum(1 for t in out["closed_pnls"] if a<=t["entry_date"]<=b)
    return round((e1/e0-1)*100,2), round(dd,2), n
if __name__ == "__main__":
    res = {}
    for name, fn in [("A_formal_ee4476b", None), ("B_all_proxy", strip), ("C_ffill_basis", ffill)]:
        p, pack = R.make_pack(fn(R.snap["bars"]) if fn else None)
        out = R.run(p, pack)
        res[name] = {k: out.get(k) for k in KEYS}
        res[name]["bysym_R"] = bysym(out)
        res[name]["train_1223_0831"] = seg_ret(out, "2025-12-23", "2026-08-31")
        res[name]["test_0901_1113"] = seg_ret(out, "2026-09-01", "2026-11-13")
        res[name]["long_holds"] = [(t["code"],t["entry_date"],t["date"],t["reason"],t["R"]) for t in out["closed_pnls"] if (len([1 for b in pack[0][t["code"]]["hist"] if t["entry_date"]<=b["date"]<=t["date"]])>15)]
        print(name, json.dumps(res[name], ensure_ascii=False))
    Path(__file__).with_name("variants_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
