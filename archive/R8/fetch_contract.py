# -*- coding: utf-8 -*-
"""R8 data-feasibility fetcher (READ-ONLY with respect to the repo's data layer).

Downloads exchange-official per-contract daily quotes for every trading day of the master calendar
(2016-01-04 .. 2025-12-31) and stores the raw responses (gzip) under archive/R8/raw_contract/<exch>/.
Writes a manifest (url, status, bytes, sha256 of the raw response, fetch time) -> committed; raw files are NOT committed.

usage: python archive/R8/fetch_contract.py shfe|czce [--workers 4]
Resumable: days already in the manifest with status ok/404 are skipped.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "archive" / "R8" / "raw_contract"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
W0, W1 = "2016-01-04", "2025-12-31"
if "--range" in sys.argv:  # optional: --range 2026-01-05 2026-11-25 (extra window, same manifests)
    _i = sys.argv.index("--range")
    W0, W1 = sys.argv[_i + 1], sys.argv[_i + 2]


def master_calendar() -> list[str]:
    uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    days = set()
    for u in uni["symbols"]:
        for b in json.loads((ROOT / ".cache" / "history" / f"{u['code']}0.json").read_text(encoding="utf-8")):
            d = str(b["date"])[:10]
            if W0 <= d <= W1:
                days.add(d)
    return sorted(days)


def url_for(exch: str, d: str) -> str:
    ymd = d.replace("-", "")
    if exch == "shfe":
        return f"https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{ymd}.dat"
    if exch == "czce":
        return f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{d[:4]}/{ymd}/FutureDataDaily.txt"
    raise SystemExit(f"unknown exchange {exch}")


def main() -> None:
    exch = sys.argv[1].lower()
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 4
    d_out = OUT / exch
    d_out.mkdir(parents=True, exist_ok=True)
    mpath = OUT / f"MANIFEST_{exch}.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    lock = threading.Lock()
    todo = [d for d in master_calendar() if manifest.get(d, {}).get("status") not in ("ok", "404")]
    print(exch, "todo", len(todo), "of", len(master_calendar()), flush=True)

    def work(d: str) -> None:
        u = url_for(exch, d)
        rec = {"url": u}
        for attempt in range(4):
            try:
                r = requests.get(u, headers=H, timeout=40)
                rec["fetched_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if r.status_code == 200 and len(r.content) > 500:
                    ymd = d.replace("-", "")
                    (d_out / f"{ymd}.gz").write_bytes(gzip.compress(r.content, 6))
                    rec.update(status="ok", bytes=len(r.content), sha256=hashlib.sha256(r.content).hexdigest())
                elif r.status_code == 404:
                    rec.update(status="404", bytes=len(r.content))
                else:
                    rec.update(status=f"http{r.status_code}", bytes=len(r.content))
                break
            except Exception as e:  # noqa: BLE001
                rec.update(status="error", error=repr(e)[:120])
                time.sleep(1.5 * (attempt + 1))
        time.sleep(0.05)
        with lock:
            manifest[d] = rec

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, _ in enumerate(ex.map(work, todo), 1):
            if i % 200 == 0:
                with lock:
                    mpath.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                print(exch, i, "/", len(todo), f"{time.time() - t0:.0f}s", flush=True)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
    st = {}
    for v in manifest.values():
        st[v.get("status")] = st.get(v.get("status"), 0) + 1
    print(exch, "DONE", st, f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
