"""fix3-opt: re-backfill DCE seat ranks with the HISTORICAL dominant (max-OI) contract per day.
Usage: python lab/shadow/fix3/dce_seat_hist_backfill.py START END   (YYYYMMDD)
Writes .cache/member/{dce,em}-YYYYMMDD.json DCE slices + lab/shadow/fix3/dce_seat_hist_log.json."""
import json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import member_rank as m

start, end = sys.argv[1], sys.argv[2]
codes = ["M", "P", "JD", "EG", "EB", "V", "L", "PP", "I", "JM"]
days = sorted({p.name[5:13] for p in (ROOT / ".cache/member").glob("czce-*.txt")} | {p.name[4:12] for p in (ROOT / ".cache/member").glob("dce-*.json")})
days = [d for d in days if start <= d <= end]
def _done(d):
    f = ROOT / f".cache/member/dce-{d}.json"
    return f.exists() and "historical_oi_max" in f.read_text(encoding="utf-8")
days = [d for d in days if "--redo" in sys.argv or not _done(d)]
cands = sorted({c for d in days for v in codes for c in m._candidate_contracts(v, d)})
with ThreadPoolExecutor(8) as ex:
    list(ex.map(m._sina_contract_hold, cands))
print("candidates", len(cands), "with data", sum(1 for c in cands if m._HIST_DAILY_CACHE.get(c)), flush=True)
log = {}
def one(d):
    r = m.fetch_dce_member_day_historical(d, codes)
    return d, r
with ThreadPoolExecutor(10) as ex:
    for i, (d, r) in enumerate(ex.map(one, days)):
        log[d] = r["status"]
        if i % 5 == 0: print(d, r["products"], flush=True)
out = ROOT / "lab/shadow/fix3/dce_seat_hist_log.json"
prev = json.loads(out.read_text()) if out.exists() else {}
prev.update(log)
out.write_text(json.dumps(prev, ensure_ascii=False, indent=0, sort_keys=True))
print("done days", len(days), flush=True)
