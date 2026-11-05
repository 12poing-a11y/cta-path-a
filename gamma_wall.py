# -*- coding: utf-8 -*-
"""Gamma Wall research engine: free CZCE daily option data + Black-76.

No paid API is used. OI does not reveal dealer positioning; call/put side
bars are visual sides, not inferred dealer gamma signs.
"""
from __future__ import annotations
import argparse, json, math, re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "gamma_wall"
MULTIPLIERS = {"CF": 5.0, "SR": 10.0}
CZCE_NAMES = {"CF": "棉花期权", "SR": "白糖期权"}

def _num(v: Any) -> float | None:
    try:
        if v is None or str(v).strip() in {"", "-", "nan", "None"}: return None
        x = float(str(v).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError): return None

def czce_option_month(futures_contract: str) -> str:
    """CF2701 -> CF701; CZCE option codes use one-digit year + two-digit month."""
    m = re.fullmatch(r"([A-Za-z]+)(\d{4})", futures_contract.strip())
    if not m: raise ValueError("期货合约必须为品种+四位年月，例如 CF2701")
    product, yymm = m.group(1).upper(), m.group(2)
    return f"{product}{int(yymm[:2]) % 10}{yymm[2:]}"

def black76_gamma(futures: float, strike: float, years: float, rate: float, iv: float) -> float:
    """Black-76 gamma with respect to futures price."""
    if min(futures, strike, years, iv) <= 0: raise ValueError("F、K、T、IV 必须大于 0")
    vol_t = iv * math.sqrt(years)
    d1 = (math.log(futures / strike) + 0.5 * iv * iv * years) / vol_t
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return math.exp(-rate * years) * pdf / (futures * vol_t)

def _contract_side(code: str, product_month: str):
    text = str(code or "").upper().replace("-", "")
    m = re.fullmatch(re.escape(product_month) + r"([CP])(\d+(?:\.\d+)?)", text)
    return (m.group(1), float(m.group(2))) if m else None

def calculate_gamma_rows(option_rows, *, product_month, futures_price, expiry, asof, multiplier, rate=0.02):
    """Call-side positive / put-side negative is a display convention only."""
    days = (date.fromisoformat(expiry) - date.fromisoformat(asof[:10])).days
    if days <= 0: raise ValueError("到期日必须晚于快照日期")
    t, agg = days / 365.0, {}
    for row in option_rows:
        parsed = _contract_side(str(row.get("合约代码") or row.get("合约") or ""), product_month)
        if not parsed: continue
        side, strike = parsed
        oi = _num(row.get("空盘量"))
        if oi is None: oi = _num(row.get("持仓量"))
        iv = _num(row.get("隐含波动率"))
        if iv is not None and iv > 3: iv /= 100.0
        if oi is None or oi < 0 or iv is None or not (0.005 <= iv <= 5): continue
        gamma = black76_gamma(futures_price, strike, t, rate, iv)
        gex = gamma * oi * multiplier * futures_price * futures_price * 0.01
        b = agg.setdefault(strike, {"call_gex":0.0,"put_gex":0.0,"call_oi":0.0,"put_oi":0.0})
        key = "call" if side == "C" else "put"
        b[f"{key}_gex"] += gex
        b[f"{key}_oi"] += oi
    return [{"strike":k,"call_gex":v["call_gex"],"put_gex":-v["put_gex"],
             "gross_gex":v["call_gex"]+v["put_gex"],"call_oi":v["call_oi"],"put_oi":v["put_oi"]}
            for k,v in sorted(agg.items())]

def _fetch_czce_day(product, trade_date):
    import akshare as ak
    return ak.option_hist_czce(symbol=CZCE_NAMES[product], trade_date=trade_date.replace("-",""))

def _fetch_underlying(contract):
    import akshare as ak
    return ak.futures_zh_daily_sina(symbol=contract)

def fetch_snapshot(contract, *, expiry, trade_date=None, rate=0.02, root=None):
    """Fetch one CZCE option daily table + exact futures contract daily history."""
    root = root or ROOT
    contract = contract.upper()
    m = re.fullmatch(r"([A-Z]+)(\d{4})", contract)
    if not m or m.group(1) not in CZCE_NAMES: raise ValueError("V1 仅支持郑商所 CF/SR，例如 CF2701、SR2701")
    product, asof = m.group(1), (trade_date or date.today().isoformat())[:10]
    month = czce_option_month(contract)
    raw = root / ".cache" / "gamma_wall" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    op = raw / f"{product}_{asof}.json"
    fp = raw / f"{contract}_daily.json"
    if op.exists(): option_rows = json.loads(op.read_text(encoding="utf-8"))
    else:
        frame = _fetch_czce_day(product, asof)
        option_rows = frame.to_dict("records")
        op.write_text(json.dumps(option_rows, ensure_ascii=False, default=str), encoding="utf-8")
    fut_rows = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
    frow = next((r for r in reversed(fut_rows) if str(r.get("date",""))[:10] == asof), None)
    if frow is None:
        frame = _fetch_underlying(contract)
        fresh_rows = frame.to_dict("records")
        by_date = {str(r.get("date",""))[:10]: r for r in fut_rows}
        by_date.update({str(r.get("date",""))[:10]: r for r in fresh_rows})
        fut_rows = [by_date[k] for k in sorted(by_date) if k]
        fp.write_text(json.dumps(fut_rows, ensure_ascii=False, default=str), encoding="utf-8")
        frow = next((r for r in reversed(fut_rows) if str(r.get("date",""))[:10] == asof), None)
    if frow is None: raise RuntimeError(f"新浪未返回 {contract} 在 {asof} 的单合约日线；禁止用主连价格替代")
    futures_price = _num(frow.get("settle")) or _num(frow.get("close"))
    if futures_price is None or futures_price <= 0: raise RuntimeError("目标期货结算价/收盘价缺失")
    matching = [r for r in option_rows if _contract_side(str(r.get("合约代码") or ""), month)]
    if not matching: raise RuntimeError(f"郑商所期权表中没有匹配 {contract} 的系列（期权月份 {month}）")
    rows = calculate_gamma_rows(matching, product_month=month, futures_price=futures_price,
        expiry=expiry, asof=asof, multiplier=MULTIPLIERS[product], rate=rate)
    if not rows: raise RuntimeError("匹配到期权系列，但没有足够有效的 OI/IV 数据计算 Gamma")
    call_wall, put_wall = max(rows,key=lambda x:x["call_gex"]), min(rows,key=lambda x:x["put_gex"])
    snap = {"schema_version":1,"source":"AKShare -> CZCE daily option + Sina exact futures contract",
        "asof":asof,"contract":contract,"option_month":month,"expiry":expiry,"futures_price":futures_price,
        "rate":rate,"multiplier":MULTIPLIERS[product],"rows":rows,
        "call_wall":call_wall["strike"],"put_wall":put_wall["strike"],
        "call_wall_gex":call_wall["call_gex"],"put_wall_gex":abs(put_wall["put_gex"]),
        "data_quality":{"option_rows":len(matching),"valid_strikes":len(rows),"dealer_sign_known":False},
        "disclaimer":"Call/Put 两侧柱体是分类展示，不代表 dealer 净 Gamma 正负；OI 无法识别持仓方方向。"}
    outdir = root / ".cache" / "gamma_wall" / contract
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{asof}.json").write_text(json.dumps(snap,ensure_ascii=False,indent=2),encoding="utf-8")
    return snap

def load_history(contract, *, root=None):
    folder = (root or ROOT) / ".cache" / "gamma_wall" / contract.upper()
    rows = []
    if folder.exists():
        for p in sorted(folder.glob("*.json")):
            try: rows.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError,json.JSONDecodeError): pass
    return rows

def migration_rows(contract, window=20, *, root=None):
    if window not in {5,10,20,30,60}: raise ValueError("window 仅支持 5/10/20/30/60")
    history = load_history(contract,root=root)[-window:]
    if not history: return []
    base = history[0]
    return [{"date":s["asof"],"futures_price":s["futures_price"],"call_wall":s["call_wall"],
        "put_wall":s["put_wall"],"call_wall_move":s["call_wall"]-base["call_wall"],
        "put_wall_move":s["put_wall"]-base["put_wall"],"call_wall_gex":s["call_wall_gex"],
        "put_wall_gex":s["put_wall_gex"],"observations":len(history)} for s in history]

def main():
    p=argparse.ArgumentParser(description="Build free-source commodity Gamma Wall snapshot")
    p.add_argument("--contract",default="CF2701")
    p.add_argument("--expiry",required=True,help="经交易所规则核实的期权到期/最后交易日 YYYY-MM-DD")
    p.add_argument("--date",default=None,help="交易日 YYYY-MM-DD，默认今天")
    p.add_argument("--rate",type=float,default=0.02)
    a=p.parse_args()
    result=fetch_snapshot(a.contract,expiry=a.expiry,trade_date=a.date,rate=a.rate)
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
