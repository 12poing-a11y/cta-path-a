# -*- coding: utf-8 -*-
"""Ingest DCE official per-contract daily quotes fetched through a real browser session (same-origin fetch of
/dcereport/publicweb/dailystat/dayQuotes, varietyId=all, tradeType=1), filtered in-page to the 10 universe varieties.

usage: python archive/R8/ingest_dce.py <cdp-response.json> [...]
Writes archive/R8/raw_contract/dce/<YYYYMMDD>.gz (gzip of canonical JSON of the kept rows) and updates MANIFEST_dce.json
(sha256 = sha256 of the canonical JSON bytes that were saved; `resp_len` = byte length of the full raw response seen in-page).
Days where the API returned zero rows are recorded as status 'empty' (non-trading day).
"""
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "archive" / "R8" / "raw_contract"
(OUT / "dce").mkdir(parents=True, exist_ok=True)
mpath = OUT / "MANIFEST_dce.json"
manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
COLS = ["contractId", "open", "high", "low", "close", "lastClear", "clearPrice", "volumn", "openInterest", "turnover"]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
for p in sys.argv[1:]:
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    val = raw["result"]["value"] if isinstance(raw, dict) and "result" in raw else raw
    payload = json.loads(val) if isinstance(val, str) else val
    days = payload["days"]
    n_ok = n_empty = n_bad = 0
    for ymd, rec in sorted(days.items()):
        d = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        if rec.get("s") != 200:
            manifest[d] = {"status": f"http{rec.get('s')}", "fetched_utc": now}
            n_bad += 1
            continue
        rows = rec["rows"]
        if not rows:
            manifest[d] = {"status": "empty", "resp_len": rec.get("len"), "api_rows": rec.get("n"), "fetched_utc": now}
            n_empty += 1
            continue
        body = json.dumps({"cols": COLS, "rows": rows}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        (OUT / "dce" / f"{ymd}.gz").write_bytes(gzip.compress(body, 6))
        manifest[d] = {
            "status": "ok", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "resp_len": rec.get("len"), "api_rows": rec.get("n"),
            "kept_rows": len(rows), "fetched_utc": now,
            "url": "POST https://www.dce.com.cn/dcereport/publicweb/dailystat/dayQuotes {tradeDate,varietyId:all,tradeType:1}",
        }
        n_ok += 1
    print(p, "year", payload.get("year"), "elapsed_s", payload.get("sec"), "ok", n_ok, "empty", n_empty, "bad", n_bad)
mpath.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
print("manifest days:", len(manifest))
