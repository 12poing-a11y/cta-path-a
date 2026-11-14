# -*- coding: utf-8 -*-
"""Shadow performance ledger: candidate → T+N attribution → category win rates.

Research / observe only. Never writes paper_book, never changes entry_filter.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "cta-shadow-perf-v1"
HORIZONS = (1, 3, 5)
MIN_SAMPLE = 20  # below this: show only, no conclusion
OUT_REL = Path("data") / "shadow_perf"
LEDGER_NAME = "ledger.jsonl"
SUMMARY_NAME = "summary_latest.json"
SNAPSHOT_DIR = "snapshots"

STRATEGY_LABEL = {
    "path_a": "路径A seats",
    "path_a_selected": "路径A·入选",
    "sentiment_mds": "情绪MDS+EHI",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _norm_ymd(raw: Any) -> str | None:
    s = str(raw or "").strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _ymd_compact(iso: str) -> str:
    return str(iso).replace("-", "")[:8]


def out_dir(root: Path) -> Path:
    d = Path(root) / OUT_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
    return d


def ledger_path(root: Path) -> Path:
    return out_dir(root) / LEDGER_NAME


def summary_path(root: Path) -> Path:
    return out_dir(root) / SUMMARY_NAME


def load_ledger(root: Path) -> list[dict[str, Any]]:
    path = ledger_path(root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load_summary(root: Path) -> dict[str, Any] | None:
    path = summary_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_ledger(root: Path, rows: list[dict[str, Any]]) -> Path:
    path = ledger_path(root)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _universe_meta(root: Path) -> dict[str, dict[str, Any]]:
    path = Path(root) / "universe.json"
    if not path.is_file():
        return {}
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in cfg.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        if code:
            out[code] = row
    return out


def _side_from_direction(direction: Any) -> int | None:
    d = str(direction or "").strip()
    if d in ("多", "long", "Long", "BUY", "1"):
        return 1
    if d in ("空", "short", "Short", "SELL", "-1"):
        return -1
    return None


def _row_id(strategy_id: str, code: str, asof: str, side: int) -> str:
    side_s = "long" if side > 0 else "short"
    return f"{strategy_id}|{code}|{asof}|{side_s}"


def _candidate(
    *,
    strategy_id: str,
    code: str,
    asof: str,
    side: int,
    entry_px: float | None,
    bucket: str = "",
    name: str = "",
    stop: float | None = None,
    target: float | None = None,
    atr: float | None = None,
    selected: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "id": _row_id(strategy_id, code, asof, side),
        "asof": asof,
        "code": code,
        "bucket": bucket or "",
        "name": name or "",
        "strategy_id": strategy_id,
        "strategy_label": STRATEGY_LABEL.get(strategy_id, strategy_id),
        "side": int(side),
        "entry_px": entry_px,
        "stop": stop,
        "target": target,
        "atr": atr,
        "selected": selected,
        "horizons": list(HORIZONS),
        "fwd": {},
        "status": "open",
        "live_trading": False,
        "updated_at": _iso_now(),
        **(extra or {}),
    }


def extract_l1_candidates(
    report: dict[str, Any], *, universe: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Path-A directional signals (同向) + selected subset."""
    asof = _norm_ymd(report.get("asof") or report.get("bar_date"))
    if not asof:
        return []
    uni = universe or {}
    out: list[dict[str, Any]] = []
    for sig in report.get("signals") or []:
        if not isinstance(sig, dict):
            continue
        code = str(sig.get("code") or "").upper()
        if not code:
            continue
        side = _side_from_direction(sig.get("direction"))
        if side is None:
            continue
        # Only mom-aligned candidates (空仓 / 冲突 skip).
        align = str(sig.get("align") or "")
        if align and align not in ("同向", "aligned", "ok"):
            # Still allow selected rows if any
            if not sig.get("selected"):
                continue
        meta = uni.get(code) or {}
        try:
            entry = float(sig["close"]) if sig.get("close") is not None else None
        except (TypeError, ValueError):
            entry = None
        stop = sig.get("stop")
        target = sig.get("target")
        atr = sig.get("atr")
        try:
            stop_f = float(stop) if stop is not None else None
        except (TypeError, ValueError):
            stop_f = None
        try:
            target_f = float(target) if target is not None else None
        except (TypeError, ValueError):
            target_f = None
        try:
            atr_f = float(atr) if atr is not None else None
        except (TypeError, ValueError):
            atr_f = None
        base_kw = dict(
            code=code,
            asof=asof,
            side=side,
            entry_px=entry,
            bucket=str(sig.get("bucket") or meta.get("bucket") or ""),
            name=str(sig.get("name") or meta.get("name") or ""),
            stop=stop_f,
            target=target_f,
            atr=atr_f,
            selected=bool(sig.get("selected")),
            extra={
                "source": "l1_report",
                "action": sig.get("action"),
                "seat": sig.get("seat"),
                "r20": sig.get("r20"),
                "r60": sig.get("r60"),
            },
        )
        out.append(_candidate(strategy_id="path_a", **base_kw))
        if sig.get("selected"):
            out.append(_candidate(strategy_id="path_a_selected", **base_kw))
    return out


def extract_sentiment_candidates(
    snap: dict[str, Any], *, universe: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    asof = _norm_ymd(snap.get("asof"))
    if not asof:
        return []
    uni = universe or {}
    out: list[dict[str, Any]] = []
    for row in snap.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        try:
            sig = int(row.get("signal") or 0)
        except (TypeError, ValueError):
            continue
        if sig == 0:
            continue
        code = str(row.get("code") or "").upper()
        if not code:
            continue
        meta = uni.get(code) or {}
        out.append(
            _candidate(
                strategy_id="sentiment_mds",
                code=code,
                asof=asof,
                side=1 if sig > 0 else -1,
                entry_px=None,  # filled from closes on backfill if missing
                bucket=str(meta.get("bucket") or ""),
                name=str(meta.get("name") or ""),
                selected=None,
                extra={
                    "source": "sentiment_mds_shadow",
                    "mds": row.get("mds"),
                    "ehi": row.get("ehi"),
                    "w_norm": row.get("w_norm"),
                },
            )
        )
    return out


def _bars_to_close_map(bars: Any) -> dict[str, float]:
    """ISO date → close."""
    out: dict[str, float] = {}
    if not isinstance(bars, list):
        return out
    for b in bars:
        if not isinstance(b, dict) or b.get("close") is None:
            continue
        day = _norm_ymd(b.get("date"))
        if not day:
            continue
        try:
            out[day] = float(b["close"])
        except (TypeError, ValueError):
            continue
    return out


def load_close_maps(root: Path, codes: Iterable[str] | None = None) -> dict[str, dict[str, float]]:
    """Prefer .cache/history CODE0, then sina day folders (same as sentiment_history)."""
    root = Path(root)
    want = {c.upper() for c in codes} if codes is not None else None
    out: dict[str, dict[str, float]] = {}

    hist = root / ".cache" / "history"
    if hist.is_dir():
        for f in hist.glob("*0.json"):
            code = f.stem[:-1].upper()
            if want is not None and code not in want:
                continue
            try:
                bars = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            m = _bars_to_close_map(bars)
            if m:
                out[code] = m

    sina = root / ".cache" / "sina"
    dirs = sorted(p for p in sina.glob("*") if p.is_dir()) if sina.is_dir() else []
    for d in dirs:
        for f in d.glob("*0.json"):
            code = f.stem[:-1].upper()
            if want is not None and code not in want:
                continue
            try:
                bars = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            m = _bars_to_close_map(bars)
            if not m:
                continue
            if code in out:
                out[code].update(m)
            else:
                out[code] = m
    return out


def _trading_days_after(closes: dict[str, float], asof: str, n: int) -> tuple[str | None, float | None]:
    """n-th session after asof (exclusive)."""
    days = sorted(closes.keys())
    if asof not in closes:
        # tolerate asof missing entry_px path: find first day >= asof
        later = [d for d in days if d >= asof]
        if not later:
            return None, None
        # if asof itself missing, treat later[0] as signal day index
        try:
            i0 = days.index(later[0])
        except ValueError:
            return None, None
        # if later[0] > asof, we still need n steps from signal day
        target_i = i0 + n
        if later[0] == asof:
            target_i = i0 + n
        if target_i >= len(days):
            return None, None
        day = days[target_i]
        return day, closes[day]
    i0 = days.index(asof)
    j = i0 + n
    if j >= len(days):
        return None, None
    day = days[j]
    return day, closes[day]


def _risk_frac(row: dict[str, Any]) -> float | None:
    entry = row.get("entry_px")
    stop = row.get("stop")
    atr = row.get("atr")
    try:
        entry_f = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        entry_f = None
    if entry_f is None or entry_f <= 0:
        return None
    try:
        stop_f = float(stop) if stop is not None else None
    except (TypeError, ValueError):
        stop_f = None
    if stop_f is not None and stop_f > 0:
        risk = abs(entry_f - stop_f) / entry_f
        return risk if risk > 0 else None
    try:
        atr_f = float(atr) if atr is not None else None
    except (TypeError, ValueError):
        atr_f = None
    if atr_f is not None and atr_f > 0:
        # Path-A default stop 0.8×ATR
        risk = (0.8 * atr_f) / entry_f
        return risk if risk > 0 else None
    return None


def backfill_row(row: dict[str, Any], closes: dict[str, float]) -> dict[str, Any]:
    """Fill fwd[horizon] for one ledger row using session closes."""
    asof = _norm_ymd(row.get("asof"))
    if not asof or not closes:
        return row
    side = int(row.get("side") or 0)
    if side not in (1, -1):
        return row
    entry = row.get("entry_px")
    try:
        entry_f = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        entry_f = None
    if entry_f is None or entry_f <= 0:
        # recover from close map
        if asof in closes and closes[asof] > 0:
            entry_f = float(closes[asof])
            row = {**row, "entry_px": entry_f}
        else:
            return row

    fwd = dict(row.get("fwd") or {})
    risk = _risk_frac(row)
    done = 0
    for h in HORIZONS:
        exit_day, exit_px = _trading_days_after(closes, asof, int(h))
        if exit_day is None or exit_px is None or exit_px <= 0:
            continue
        raw_ret = exit_px / entry_f - 1.0
        signed = side * raw_ret
        pack = {
            "exit_date": exit_day,
            "exit_px": round(exit_px, 6),
            "ret": round(signed, 6),
            "ret_pct": round(signed * 100, 4),
            "hit": bool(signed > 0),
            "r_mult": round(signed / risk, 4) if risk else None,
        }
        fwd[str(h)] = pack
        done += 1
    status = "closed" if done >= len(HORIZONS) else ("partial" if done else "open")
    return {
        **row,
        "fwd": fwd,
        "status": status,
        "updated_at": _iso_now(),
    }


def upsert_candidates(
    existing: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep prior fwd when re-snapshotting the same id."""
    by_id = {str(r.get("id")): dict(r) for r in existing if r.get("id")}
    for cand in candidates:
        cid = str(cand.get("id") or "")
        if not cid:
            continue
        prev = by_id.get(cid)
        if prev is None:
            by_id[cid] = cand
            continue
        merged = {**cand}
        # Preserve attribution already filled
        if prev.get("fwd"):
            merged["fwd"] = prev["fwd"]
            merged["status"] = prev.get("status") or cand.get("status")
        if prev.get("entry_px") and not merged.get("entry_px"):
            merged["entry_px"] = prev["entry_px"]
        by_id[cid] = merged
    # Stable order: asof, strategy, code
    rows = list(by_id.values())
    rows.sort(
        key=lambda r: (
            str(r.get("asof") or ""),
            str(r.get("strategy_id") or ""),
            str(r.get("code") or ""),
            str(r.get("id") or ""),
        )
    )
    return rows


def _stat_bucket(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    h = str(horizon)
    rets: list[float] = []
    hits = 0
    rs: list[float] = []
    for r in rows:
        pack = (r.get("fwd") or {}).get(h)
        if not isinstance(pack, dict) or pack.get("ret") is None:
            continue
        try:
            ret = float(pack["ret"])
        except (TypeError, ValueError):
            continue
        rets.append(ret)
        if pack.get("hit"):
            hits += 1
        if pack.get("r_mult") is not None:
            try:
                rs.append(float(pack["r_mult"]))
            except (TypeError, ValueError):
                pass
    n = len(rets)
    return {
        "n": n,
        "win_rate": round(hits / n, 4) if n else None,
        "win_rate_pct": round(100.0 * hits / n, 2) if n else None,
        "avg_ret_pct": round(100.0 * sum(rets) / n, 4) if n else None,
        "avg_r": round(sum(rs) / len(rs), 4) if rs else None,
        "enough": bool(n >= MIN_SAMPLE),
    }


def aggregate_summary(
    rows: list[dict[str, Any]], *, horizon: int = 1
) -> dict[str, Any]:
    """Build by_bucket / by_code / by_strategy tables for one horizon."""
    h = int(horizon)
    by_strategy: dict[str, list] = defaultdict(list)
    by_bucket: dict[tuple[str, str], list] = defaultdict(list)
    by_code: dict[tuple[str, str], list] = defaultdict(list)

    for r in rows:
        sid = str(r.get("strategy_id") or "")
        bucket = str(r.get("bucket") or "未分组")
        code = str(r.get("code") or "")
        by_strategy[sid].append(r)
        by_bucket[(sid, bucket)].append(r)
        by_code[(sid, code)].append(r)

    strategy_rows = []
    for sid, items in sorted(by_strategy.items()):
        st = _stat_bucket(items, h)
        strategy_rows.append(
            {
                "strategy_id": sid,
                "strategy_label": STRATEGY_LABEL.get(sid, sid),
                "horizon": h,
                **st,
            }
        )

    bucket_rows = []
    for (sid, bucket), items in sorted(by_bucket.items()):
        st = _stat_bucket(items, h)
        bucket_rows.append(
            {
                "strategy_id": sid,
                "strategy_label": STRATEGY_LABEL.get(sid, sid),
                "bucket": bucket,
                "horizon": h,
                **st,
            }
        )

    code_rows = []
    for (sid, code), items in sorted(by_code.items()):
        st = _stat_bucket(items, h)
        name = next((str(x.get("name") or "") for x in items if x.get("name")), "")
        bucket = next((str(x.get("bucket") or "") for x in items if x.get("bucket")), "")
        code_rows.append(
            {
                "strategy_id": sid,
                "strategy_label": STRATEGY_LABEL.get(sid, sid),
                "code": code,
                "name": name,
                "bucket": bucket,
                "horizon": h,
                **st,
            }
        )

    return {
        "schema": SCHEMA,
        "horizon": h,
        "min_sample": MIN_SAMPLE,
        "n_ledger": len(rows),
        "by_strategy": strategy_rows,
        "by_bucket": bucket_rows,
        "by_code": code_rows,
        "disclaimer": (
            "Research only · 影子归因不计分、不改 Path-A。"
            f"单格样本 <{MIN_SAMPLE} 只展示、不下结论。"
        ),
    }


def _load_l1_report(root: Path, asof: str | None = None) -> dict[str, Any] | None:
    root = Path(root)
    if asof:
        ymd = _ymd_compact(_norm_ymd(asof) or "")
        arch = root / "archive" / f"l1_report_{ymd}.json"
        if arch.is_file():
            try:
                return json.loads(arch.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    for name in ("l1_report_risk15.json", "l1_report.json"):
        p = root / name
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _load_sentiment_snap(root: Path, asof: str | None = None) -> dict[str, Any] | None:
    root = Path(root)
    shadow = root / "data" / "sentiment_mds" / "shadow"
    if asof:
        ymd = _ymd_compact(_norm_ymd(asof) or "")
        p = shadow / f"sentiment_{ymd}.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    # latest dated shadow file
    files = sorted(shadow.glob("sentiment_*.json")) if shadow.is_dir() else []
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_day_candidates(root: Path, asof: str | None = None) -> list[dict[str, Any]]:
    uni = _universe_meta(root)
    cands: list[dict[str, Any]] = []
    want = _norm_ymd(asof) if asof else None
    report = _load_l1_report(root, asof=asof)
    if report:
        rep_asof = _norm_ymd(report.get("asof"))
        if want is None or rep_asof == want:
            cands.extend(extract_l1_candidates(report, universe=uni))
    snap_asof_arg = asof or (report or {}).get("asof")
    snap = _load_sentiment_snap(root, asof=snap_asof_arg)
    if snap:
        snap_asof = _norm_ymd(snap.get("asof"))
        if want is None or snap_asof == want:
            cands.extend(extract_sentiment_candidates(snap, universe=uni))
    return cands


def backfill_history_candidates(root: Path, *, max_days: int = 60) -> list[dict[str, Any]]:
    """Rebuild candidates from archive L1 + sentiment shadow (idempotent upsert)."""
    root = Path(root)
    uni = _universe_meta(root)
    cands: list[dict[str, Any]] = []

    arch = root / "archive"
    l1_files = sorted(arch.glob("l1_report_????????.json")) if arch.is_dir() else []
    for p in l1_files[-max_days:]:
        try:
            report = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cands.extend(extract_l1_candidates(report, universe=uni))

    shadow = root / "data" / "sentiment_mds" / "shadow"
    sent_files = sorted(shadow.glob("sentiment_????????.json")) if shadow.is_dir() else []
    for p in sent_files[-max_days:]:
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cands.extend(extract_sentiment_candidates(snap, universe=uni))
    return cands


def refresh_shadow_perf(
    root: Path,
    *,
    asof: str | None = None,
    backfill_history: bool = False,
    max_history_days: int = 60,
    write: bool = True,
) -> dict[str, Any]:
    """Soft daily step: snapshot candidates, backfill fwd, write summary.

    Never touches Path-A formal artifacts.
    """
    root = Path(root)
    existing = load_ledger(root)
    cands = collect_day_candidates(root, asof=asof)
    if backfill_history:
        cands = backfill_history_candidates(root, max_days=max_history_days) + cands
    rows = upsert_candidates(existing, cands)

    codes = {str(r.get("code") or "").upper() for r in rows if r.get("code")}
    closes = load_close_maps(root, codes)
    filled: list[dict[str, Any]] = []
    for r in rows:
        code = str(r.get("code") or "").upper()
        filled.append(backfill_row(r, closes.get(code) or {}))

    summaries = {str(h): aggregate_summary(filled, horizon=h) for h in HORIZONS}
    primary = summaries[str(HORIZONS[0])]
    payload = {
        "schema": SCHEMA,
        "updated_at": _iso_now(),
        "asof": _norm_ymd(asof)
        or next((str(r.get("asof")) for r in reversed(filled) if r.get("asof")), None),
        "live_trading": False,
        "n_candidates_new": len(cands),
        "n_ledger": len(filled),
        "horizons": list(HORIZONS),
        "min_sample": MIN_SAMPLE,
        "primary_horizon": HORIZONS[0],
        "summary": primary,
        "summaries": summaries,
        "disclaimer": primary.get("disclaimer"),
    }

    if write:
        d = out_dir(root)
        _write_ledger(root, filled)
        (d / SUMMARY_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        day = _ymd_compact(payload.get("asof") or "")
        if day and len(day) == 8:
            snap_rows = [r for r in filled if _ymd_compact(str(r.get("asof") or "")) == day]
            (d / SNAPSHOT_DIR / f"{day}.json").write_text(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "asof": payload.get("asof"),
                        "n": len(snap_rows),
                        "rows": snap_rows,
                        "live_trading": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        # Soft breadcrumb on experiments ledger (paper only; repo root only).
        try:
            repo_root = Path(__file__).resolve().parents[2]
            if root.resolve() == repo_root.resolve():
                from research.governance.experiment_registry import register_experiment

                register_experiment(
                    name="shadow_perf_daily",
                    kind="shadow_attribution",
                    params={
                        "asof": payload.get("asof"),
                        "horizons": list(HORIZONS),
                        "n_ledger": len(filled),
                    },
                    metrics={
                        "by_strategy": primary.get("by_strategy"),
                        "n_bucket_rows": len(primary.get("by_bucket") or []),
                    },
                    artifact=str(OUT_REL / SUMMARY_NAME),
                    status="Shadow",
                    notes="影子归因台账日更；不计分、不改 Path-A",
                    root=root,
                )
        except Exception:  # noqa: BLE001
            pass

    payload["ok"] = True
    payload["path"] = str(summary_path(root).as_posix())
    return payload
