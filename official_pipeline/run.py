# -*- coding: utf-8 -*-
"""Official daily pipeline entry point.

  python -m official_pipeline run              fetch missing days in the window (17:30 / 18:30 / 20:00 / 22:00 tasks)
  python -m official_pipeline judge [--day D]  fetch + validate + derive + judge every pending weekday before today (08:30 task)
  python -m official_pipeline seed             verified seed from archive/R8/raw_contract (one-off)
  python -m official_pipeline status           streak / gate status
  python -m official_pipeline export-hashes    hash manifests -> official_pipeline/manifest_repo (only repo-side data)
  python -m official_pipeline install-tasks    register Windows scheduled tasks (wake-to-run)

Exit codes: 0 ok | 1 fetch incomplete | 2 validation or derivation failed | 3 revision of a stored day | 9 crash.
Trading-day rule (deviation from a holiday table, documented in the design doc): a weekday is CLOSED only if all three
exchanges answered "not published" (404 / empty). Any error, HTTP 412 or format problem is NOT treated as closed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config as C
from . import state as S
from .alerts import notify, write_alert
from .store import Store, utc_now

EXIT_OK, EXIT_FETCH, EXIT_VALID, EXIT_REVISION, EXIT_CRASH = 0, 1, 2, 3, 9
NOT_PUBLISHED = {"not_published", "404", "empty", "status:404", "status:empty"}
WINDOW_WEEKDAYS = 14


def weekdays_before(today: date, n: int = WINDOW_WEEKDAYS) -> list[str]:
    """The last n weekdays strictly before today, ascending."""
    out, d = [], today - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def _log_factory():
    C.LOGS.mkdir(parents=True, exist_ok=True)
    path = C.LOGS / f"{date.today().isoformat()}.log"

    def log(msg: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return log


# ---- fetch ---------------------------------------------------------------------------------------------------------------
def fetch_missing(store: Store, days: list[str], *, log) -> dict:
    """Fetch every (exchange, day) not yet stored. Records every attempt in the manifest."""
    from .sources import fetch_dce_days, fetch_http
    import requests

    res: dict = {"new": [], "revisions": [], "failed": {}}
    session = requests.Session()
    todo_http = [(ex, d) for ex in ("shfe", "czce") for d in days if not store.is_stored(ex, d)]
    for ex, d in todo_http:
        status, body, url = fetch_http(ex, d, session=session)
        if status == "ok":
            how = store.put(ex, d, body, url=url, meta={"method": "http"})
            log(f"{ex} {d}: {how}")
            res["revisions" if how == "revision" else "new"].append(f"{ex} {d}")
        else:
            store.record_failure(ex, d, status, url=url)
            res["failed"][f"{ex} {d}"] = status
            log(f"{ex} {d}: {status}")
    dce_days = [d for d in days if not store.is_stored("dce", d)]
    if dce_days:
        try:
            got = fetch_dce_days(dce_days)
        except Exception as e:  # noqa: BLE001  browser could not start / session broke
            log(f"dce session error: {e!r}"[:300])
            got = {d: ("error", None, C.DCE_API) for d in dce_days}
        for d, (status, body, url) in got.items():
            if status == "ok":
                how = store.put("dce", d, body, url=url, meta={"method": "browser"})
                res["revisions" if how == "revision" else "new"].append(f"dce {d}")
                log(f"dce {d}: {how}")
            else:
                store.record_failure("dce", d, status, url=url)
                res["failed"][f"dce {d}"] = status
                log(f"dce {d}: {status}")
    return res


def is_closed(store: Store, day: str) -> bool:
    """All three exchanges explicitly report 'not published' for a weekday -> non-trading day."""
    return all(store.status(ex, day) in NOT_PUBLISHED for ex in C.EXCHANGES)


# ---- derive / validate ---------------------------------------------------------------------------------------------------
def load_store_by(store: Store, upto: str | None = None) -> dict:
    import contract_loader as cl

    old = cl.RAW
    cl.RAW = store.raw
    try:
        by = cl.load_all()
    finally:
        cl.RAW = old
    if upto is not None:
        by = {c: {d: r for d, r in v.items() if d <= upto} for c, v in by.items()}
        by = {c: v for c, v in by.items() if v}
    return by


def derive_main(by: dict, day: str) -> dict:
    """Official main-contract map from the R8 long-sample routine (5% volume guard; Sina continuous only as the price
    matcher). Full rebuild every day; `by` is truncated to `day` so nothing after the judged day is visible."""
    from long_sample import build_official_pack, W0

    _pack, main_map, _store, info = build_official_pack(w0=W0, w1=day, by=by)
    mains = {p: main_map.main(p, day) for p in C.PRODUCTS}
    unidentified = sorted(p for p, m in mains.items() if m is None)
    return {
        "day": day,
        "mains": {p: m for p, m in mains.items() if m is not None},
        "unidentified": unidentified,
        "unidentified_symbol_days_carried": info["unidentified_symbol_days_carried"],
        "roll_events_total": info["roll_events"],
        "pack_sha256": info["pack_sha256"],
        "built_utc": utc_now(),
    }


def judge_day(store: Store, day: str, *, log) -> dict:
    from .validate import validate_day

    reasons: list[str] = []
    details: list[str] = []
    code = EXIT_OK
    missing = [ex for ex in C.EXCHANGES if not store.is_stored(ex, day)]
    if missing:
        reasons.append(f"not stored: {','.join(missing)}")
        code = EXIT_FETCH
    rev = {ex: day in store.revision_days().get(ex, []) for ex in C.EXCHANGES}
    if any(rev.values()):
        reasons.append("revision of stored day: " + ",".join(e for e, v in rev.items() if v))
        code = EXIT_REVISION
    val = derived = None
    if not missing:
        prev = prev_stored_day(store, day)
        by_all = load_store_by(store, upto=day)
        val = validate_day(by_all, day, prev_day=prev)
        details += val["fails"] + val["infos"] + val["examples"]
        if not val["ok"]:
            reasons.append("validation failed")
            code = code or EXIT_VALID
        stale = [p for p in C.PRODUCTS if day not in sina_bar_days(p)]
        if stale:
            # The derived main needs the local Sina continuous bar of the judged day as its price matcher. That cache is
            # produced by the CTA daily job (daily.yml -> main), not by this pipeline. Missing bar = not normal, never guessed.
            reasons.append(f"sina continuous bar missing for {len(stale)} products")
            details.append("sina continuous bar missing (cache not updated to this day): " + ",".join(stale))
            code = code or EXIT_VALID
        else:
            try:
                derived = derive_main(by_all, day)
                C.DERIVED.mkdir(parents=True, exist_ok=True)
                (C.DERIVED / f"main_{day}.json").write_text(json.dumps(derived, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                if derived["unidentified"]:
                    details.append(f"main not identified (carried from previous day): {derived['unidentified']}")
            except Exception as e:  # noqa: BLE001
                reasons.append("derived main failed")
                details.append(repr(e)[:300])
                code = code or EXIT_VALID
    normal = not reasons
    rep = {"day": day, "normal": normal, "reasons": reasons, "details": details, "exit_code": code,
           "validation": val, "derived": {k: v for k, v in (derived or {}).items() if k != "mains"} or None,
           "judged_utc": utc_now()}
    C.REPORTS.mkdir(parents=True, exist_ok=True)
    (C.REPORTS / f"{day}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log(f"judge {day}: normal={normal} reasons={reasons}")
    return rep


_SINA_DAYS: dict[str, set[str]] = {}


def sina_bar_days(code: str) -> set[str]:
    """Dates present in the local Sina continuous cache for one product (read-only)."""
    if code not in _SINA_DAYS:
        f = C.ROOT / ".cache" / "history" / f"{code}0.json"
        days: set[str] = set()
        if f.exists():
            days = {str(b["date"])[:10] for b in json.loads(f.read_text(encoding="utf-8"))}
        _SINA_DAYS[code] = days
    return _SINA_DAYS[code]


def prev_stored_day(store: Store, day: str) -> str | None:
    cands = [d for d in store.stored_days("shfe") if d < day]
    return cands[-1] if cands else None


# ---- backup --------------------------------------------------------------------------------------------------------------
def maybe_backup(*, log) -> None:
    """Weekly copy of raw + state outside the repo (design decision 2)."""
    C.BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name for p in C.BACKUP_ROOT.iterdir() if p.is_dir())
    if existing and (date.today() - date.fromisoformat(existing[-1])).days < 7:
        return
    dst = C.BACKUP_ROOT / date.today().isoformat()
    shutil.copytree(C.RAW, dst / "raw")
    if C.STATE.exists():
        shutil.copyfile(C.STATE, dst / "state.json")
    log(f"weekly backup -> {dst}")


# ---- commands ------------------------------------------------------------------------------------------------------------
def _start_day(st: dict, today: date) -> str:
    """The first live day of the pipeline. Only days from here on are judged; seeded history is not counted toward the gate."""
    if not st.get("start_day"):
        st["start_day"] = today.isoformat()
    return st["start_day"]


def cmd_run(today: date, log) -> int:
    store = Store()
    st = S.load()
    _start_day(st, today)
    S.save(st)
    days = [d for d in weekdays_before(today) + [today.isoformat()] if d not in st["closed"]]
    res = fetch_missing(store, days, log=log)
    rv = store.revision_days()
    if any(rv.values()):
        p = write_alert(today.isoformat(), ["revision of a stored day detected"],
                        [f"{ex}: {', '.join(v)}" for ex, v in rv.items() if v] + ["stored content kept; see revisions/"])
        notify("CTA 官方数据：已入库日期出现修订", str(p))
        return EXIT_REVISION
    log(f"run {today}: window {days[0]}..{days[-1]}; new {res['new']}; failed {res['failed']}")
    return EXIT_OK


def cmd_judge(today: date, day: str | None, log) -> int:
    store = Store()
    st = S.load()
    start = _start_day(st, today)
    targets = [day] if day else [t for t in weekdays_before(today) if t >= start]
    worst = EXIT_OK
    fetch_missing(store, [t for t in targets if t not in st["closed"] and not S.is_final_normal(st, t)], log=log)
    for t in targets:
        if S.is_final_normal(st, t) or t in st["closed"]:
            continue
        if is_closed(store, t):
            S.mark_closed(st, t)
            log(f"{t}: closed (all exchanges not published)")
            continue
        prior = st["days"].get(t)
        rep = judge_day(store, t, log=log)
        st = S.judge(st, t, rep["normal"], rep["reasons"])
        if not rep["normal"]:
            worst = max(worst, rep["exit_code"])
            if prior is None or prior.get("reasons") != rep["reasons"]:  # alert on first judgement or changed reasons only
                p = write_alert(t, rep["reasons"], rep["details"] or ["(no detail)"])
                notify("CTA 官方数据：" + t + " 不正常", str(p))
    S.save(st)
    if worst == EXIT_OK:
        maybe_backup(log=log)
    log(f"streak={st['streak']} ready={S.gate_ready(st)}")
    return worst


def cmd_status() -> int:
    st = S.load()
    print(json.dumps({"streak": st["streak"], "gate_ready": S.gate_ready(st), "closed_recent": st["closed"][-5:],
                      "last_judged": sorted(st["days"])[-5:]}, ensure_ascii=False, indent=1))
    return 0


def cmd_export_hashes() -> int:
    store = Store()
    C.HASH_EXPORT.mkdir(parents=True, exist_ok=True)
    for ex in C.EXCHANGES:
        m = store.load_manifest(ex)
        out = {d: r.get("sha256") for d, r in sorted(m.items()) if r.get("status") == "ok"}
        (C.HASH_EXPORT / f"hashes_{ex}.json").write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    print("exported", C.HASH_EXPORT)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="official_pipeline")
    ap.add_argument("cmd", choices=["run", "judge", "seed", "status", "export-hashes", "install-tasks"])
    ap.add_argument("--day", default=None)
    a = ap.parse_args(argv)
    log = _log_factory()
    today = date.today()
    try:
        if a.cmd == "run":
            return cmd_run(today, log)
        if a.cmd == "judge":
            return cmd_judge(today, a.day, log)
        if a.cmd == "seed":
            from .seed import verify_and_copy
            rep = verify_and_copy()
            print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
            return EXIT_OK if not rep["mismatch"] else EXIT_VALID
        if a.cmd == "status":
            return cmd_status()
        if a.cmd == "export-hashes":
            return cmd_export_hashes()
        if a.cmd == "install-tasks":
            from .install_tasks import install
            install(log=log)
            return EXIT_OK
    except Exception as e:  # noqa: BLE001
        log("UNHANDLED " + repr(e)[:300] + "\n" + traceback.format_exc()[-1500:])
        p = write_alert(today.isoformat(), ["pipeline crashed"], [repr(e)[:300]])
        notify("CTA 官方数据：管道异常", str(p))
        return EXIT_CRASH
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
