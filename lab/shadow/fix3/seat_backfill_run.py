"""fix3-opt: rebuild post-lag seat books from .cache/member and rerun the formal engine (shadow only).

Main basis (H): window seats = frozen snapshot for non-DCE, DCE = historical-main backfill;
plus REAL pre-window seat sessions from cache (CZCE/SHFE exchange prints from 2025-09-22)
so the as-of-T >=60-day gate counts days that existed before the trade window."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parents[2]))
import historical_backtest as hb
import replay as R, variants as V, recompute as RC  # noqa: E402

DCE = ["M", "P", "JD", "EG", "EB", "V", "L", "PP", "I", "JM"]
_CACHE = {}


def build_member():
    if "m" not in _CACHE:
        bars = R.snap["bars"]
        dates = sorted({b["date"] for h in bars.values() for b in h})
        import member_rank as MR  # unpatched loader (replay.py patches hb.* at import)

        m = MR.load_member_seats(dates, list(bars))
        _CACHE["m"] = ({c: hb.lag_by_trade_dates(b, dates, 1) for c, b in (m or {}).items()}, dates)
    return _CACHE["m"]


def merged_member(prewindow: bool = True):
    mem, _ = build_member()
    lo = min(d for c in R.snap["member"] for d in R.snap["member"][c])
    new = {c: dict(v) for c, v in R.snap["member"].items()}
    for c in DCE:
        new[c] = {d: v for d, v in (mem.get(c) or {}).items() if d >= lo}
    if prewindow:
        pre_all = {c: {d: v for d, v in books.items() if d < lo} for c, books in mem.items()}
        pre_all = {c: v for c, v in pre_all.items() if v}
        frozen = HERE / "prewindow_seats.json"  # post-lag books < window start, frozen for CI
        if not pre_all and frozen.exists():
            pre_all = json.loads(frozen.read_text(encoding="utf-8"))["books"]
        for c, pre in pre_all.items():
            new.setdefault(c, {}).update(pre)
    return new


def freeze_prewindow():
    mem, _ = build_member()
    lo = min(d for c in R.snap["member"] for d in R.snap["member"][c])
    books = {c: {d: v for d, v in b.items() if d < lo} for c, b in mem.items()}
    books = {c: v for c, v in books.items() if v}
    (HERE / "prewindow_seats.json").write_text(json.dumps(
        {"note": "post-lag seat books before window start, from CZCE/SHFE exchange prints in .cache/member (2025-09-22..); shadow only",
         "window_start": lo, "books": books}, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def run_case(member, **kw):
    R.hb.load_member_seats = lambda d, c, _m=member: _m
    p, pack = R.make_pack()
    return R.run(p, pack, **kw)


def summarize(out):
    r = {k: out.get(k) for k in RC.KEYS}
    r["train"] = V.seg_ret(out, "2025-12-23", "2026-08-31"); r["test"] = V.seg_ret(out, "2026-09-01", "2026-11-13")
    r["cross_delivery_trades"] = RC.cross_delivery(out)
    ce, pe = out.get("contract_entry_n") or 0, out.get("proxy_entry_n") or 0
    r["proxy_entry_share"] = round(pe / max(1, ce + pe), 3)
    r["delivery_window_proxy_entries"] = sum(1 for t in out["closed_pnls"] if t.get("fill_price_basis") == "continuous_proxy" and t.get("fill_contract")) if False else None
    return r


if __name__ == "__main__":
    if "--freeze-prewindow" in sys.argv:
        freeze_prewindow()
    lo = min(d for c in R.snap["member"] for d in R.snap["member"][c])
    mem_pre = merged_member(True); mem_nopre = merged_member(False)
    res = {"window_start_member": lo,
           "prewindow_seat_days": {c: sum(1 for d in v if d < lo) for c, v in sorted(mem_pre.items())}}
    cases = [
        ("H_main_prewindow_proxy", mem_pre, {}),
        ("H_prewindow_block", mem_pre, dict(entry_delivery_action="block")),
        ("H_prewindow_no_entry_guard", mem_pre, dict(entry_delivery_buffer=0)),
        ("H_ae69c62_no_prewindow_proxy", mem_nopre, {}),
        ("H_no_prewindow_block", mem_nopre, dict(entry_delivery_action="block")),
    ]
    for name, m, kw in cases:
        out = run_case(m, **kw)
        r = summarize(out)
        res[name] = r
        print(name, r["ret_pct"], r["max_dd_pct"], r["closed_trades"], "train", r["train"], "test", r["test"],
              "proxy", out.get("proxy_entry_n"), "/", (out.get("proxy_entry_n") or 0) + (out.get("contract_entry_n") or 0),
              "skipSeat", sum((out["seat_gate"]["skipped_seat_filter_signals"] or {}).values()),
              "conc", str(out.get("conclusion"))[:60])
    (HERE / "seat_backfill_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
