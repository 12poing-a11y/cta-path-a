import json, sys, copy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay as R, variants as V
import historical_backtest as hb
TR_END="2026-08-31"; TE_A="2026-09-01"; TE_B="2026-11-13"
def trunc(bars, end):
    return {c:[b for b in h if b["date"]<=end] for c,h in bars.items()}
res={"lookahead":{}, "grid":{}}
# 1) truncation lookahead test (freqtrade-style): entries before cut must not change
base_p, base_pack = R.make_pack(); full = R.run(base_p, base_pack)
fe = {(t["code"],t["entry_date"],t["direction"],round(t["entry"],2)) for t in full["closed_pnls"]} | {(c,p["entry_date"],p["direction"],round(p["entry"],2)) for c,p in (full.get("final_positions") or {}).items()}
for cut in ["2026-03-31","2026-06-30","2026-08-31","2026-10-15"]:
    p, pack = R.make_pack(trunc(R.snap["bars"], cut)); o = R.run(p, pack)
    te = {(t["code"],t["entry_date"],t["direction"],round(t["entry"],2)) for t in o["closed_pnls"]} | {(c,q["entry_date"],q["direction"],round(q["entry"],2)) for c,q in (o.get("final_positions") or {}).items()}
    a = {x for x in fe if x[1]<=cut}; b = {x for x in te if x[1]<=cut}
    res["lookahead"][cut] = {"full_entries":len(a),"trunc_entries":len(b),"only_full":sorted(a-b)[:6],"only_trunc":sorted(b-a)[:6]}
    print("cut",cut,res["lookahead"][cut])
# 2) OOS grid
for vname, fn in [("A_formal", None), ("B_all_proxy", V.strip), ("C_ffill_basis", V.ffill)]:
    bars = fn(R.snap["bars"]) if fn else R.snap["bars"]
    rows=[]
    for s in hb.STOP_GRID:
        for rr in hb.RR_GRID:
            p, pack = R.make_pack(trunc(bars, TR_END)); tr = R.run(p, pack, stop_atr_mult=s, reward_rr=rr)
            p, pack = R.make_pack(bars); fu = R.run(p, pack, stop_atr_mult=s, reward_rr=rr)
            te = V.seg_ret(fu, TE_A, TE_B)
            rows.append({"stop":s,"rr":rr,"train_ret":tr["ret_pct"],"train_dd":tr["max_dd_pct"],"train_n":tr["closed_trades"],"train_calmar":round(tr["ret_pct"]/tr["max_dd_pct"],3) if tr["max_dd_pct"] else None,"test_ret":te[0],"test_dd":te[1],"test_n":te[2],"full_ret":fu["ret_pct"],"full_dd":fu["max_dd_pct"]})
    best = max(rows, key=lambda r:(r["train_calmar"] or -99, r["train_ret"]))
    formal = [r for r in rows if r["stop"]==0.8 and r["rr"]==2.0][0]
    import statistics
    rank_corr = None
    try:
        import numpy as np
        a=np.argsort(np.argsort([r["train_ret"] for r in rows])); b=np.argsort(np.argsort([r["test_ret"] for r in rows]))
        rank_corr = round(float(np.corrcoef(a,b)[0,1]),3)
    except Exception: pass
    res["grid"][vname]={"rows":rows,"best_by_train_calmar":best,"formal_0.8_2":formal,"train_test_rank_corr":rank_corr,"test_pos_share":round(sum(r["test_ret"]>0 for r in rows)/len(rows),3)}
    print(vname,"best",best,"\n formal",formal,"rankcorr",rank_corr,"test_pos",res["grid"][vname]["test_pos_share"])
Path(__file__).with_name("oos_lookahead_result.json").write_text(json.dumps(res,ensure_ascii=False,indent=1))
