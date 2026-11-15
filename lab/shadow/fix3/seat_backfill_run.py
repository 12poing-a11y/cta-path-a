"""fix3: rebuild post-lag seat books from the (DCE-backfilled) .cache/member and rerun formal engine.
Non-DCE codes are compared to the frozen snapshot as a sanity check. Shadow only."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parents[2]))
import historical_backtest as hb
ORIG = {k: getattr(hb, k) for k in ("load_member_seats", "lag_member")}
import replay as R, variants as V, recompute as RC  # noqa: E402

DCE = ["M", "P", "JD", "EG", "EB", "V", "L", "PP", "I", "JM"]

def build_member():
    bars = R.snap["bars"]
    dates = sorted({b["date"] for h in bars.values() for b in h})
    m = ORIG["load_member_seats"](dates, list(bars))
    return ORIG["lag_member"](m, dates, 1), dates

if __name__ == "__main__":
    mem, dates = build_member()
    lo = min(d for c in R.snap["member"] for d in R.snap["member"][c])
    cov = {c: len([d for d in (mem.get(c) or {}) if d >= lo]) for c in sorted(mem)}
    same = {}
    for c in R.snap["member"]:
        if c in DCE: continue
        a, b = R.snap["member"][c], {d: v for d, v in (mem.get(c) or {}).items() if d in R.snap["member"][c]}
        same[c] = sum(1 for d in a if json.dumps(a[d], sort_keys=True) == json.dumps(b.get(d), sort_keys=True)) / max(1, len(a))
    snap_member = R.snap["member"]
    new = dict(snap_member)
    for c in DCE:
        new[c] = {d: v for d, v in (mem.get(c) or {}).items() if d >= lo}
    R.hb.load_member_seats = lambda d, c: new
    p, pack = R.make_pack(); out = R.run(p, pack)
    r = {k: out.get(k) for k in RC.KEYS}
    r["seat_days_dce"] = {c: len(new[c]) for c in DCE}
    r["nondce_match_vs_snapshot"] = same
    r["train"] = V.seg_ret(out, "2025-12-23", "2026-08-31"); r["test"] = V.seg_ret(out, "2026-09-01", "2026-11-13")
    r["cross_delivery_trades"] = RC.cross_delivery(out)
    print(json.dumps({k: r[k] for k in ("ret_pct", "max_dd_pct", "closed_trades", "seat_days_dce", "train", "test")}, ensure_ascii=False))
    print("non-DCE snapshot match share:", {k: round(v, 3) for k, v in same.items()})
    print("seat_gate", out["seat_gate"])
    (HERE / "seat_backfill_result.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
