# -*- coding: utf-8 -*-
"""Read-only feasibility probe of external per-contract daily data sources (no strategy, nothing written to the data layer)."""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import requests

ROOT = Path(__file__).resolve().parents[2]
H = {"User-Agent": "Mozilla/5.0"}
raw = json.loads((ROOT / ".cache" / "contracts" / "AG2510.json").read_text(encoding="utf-8"))
print("local contract file keys:", list(raw.keys()), "n", raw["n"], "source", raw["source"])
print("first bar:", raw["bars"][0])
print("last bar:", raw["bars"][-1])

cands = {
    "SHFE_a": "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20240102.dat",
    "SHFE_b": "https://www.shfe.cn/data/tradedata/future/dailydata/kx20240102.dat",
    "SHFE_old": "https://www.shfe.com.cn/data/dailydata/kx/kx20190102.dat",
    "INE_a": "https://www.ine.cn/data/tradedata/future/dailydata/kx20240102.dat",
    "INE_b": "https://www.ine.cn/data/dailydata/kx/kx20240102.dat",
    "CZCE_2016": "http://www.czce.com.cn/cn/DFSStaticFiles/Future/2016/20160104/FutureDataDaily.txt",
    "CZCE_2020": "http://www.czce.com.cn/cn/DFSStaticFiles/Future/2020/20200102/FutureDataDaily.txt",
    "CZCE_2025": "http://www.czce.com.cn/cn/DFSStaticFiles/Future/2025/20251231/FutureDataDaily.txt",
}
for k, u in cands.items():
    try:
        r = requests.get(u, headers=H, timeout=25)
        print(k, r.status_code, len(r.content), r.headers.get("content-type"))
        if r.status_code == 200:
            print("   head:", r.content[:200].decode("utf-8", "ignore").replace("\n", " | ")[:200])
    except Exception as e:  # noqa: BLE001
        print(k, "ERR", repr(e)[:120])

import akshare as ak
for mkt, day in (("SHFE", "20240102"), ("INE", "20240102"), ("DCE", "20240102"), ("CZCE", "20240102")):
    try:
        df = ak.get_futures_daily(start_date=day, end_date=day, market=mkt)
        print("akshare", mkt, day, None if df is None else df.shape, None if df is None else list(df.columns))
        if df is not None and len(df):
            print(df.head(3).to_string())
    except Exception as e:  # noqa: BLE001
        print("akshare", mkt, day, "ERR", repr(e)[:200])
