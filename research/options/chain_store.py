# -*- coding: utf-8 -*-
"""Daily option chain snapshots under data/options/snapshots/ (research only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.options.parse import legs_from_czce_rows, product_from_contract
from research.options.quality import assess_chain_quality
from research.options.specs import get_spec

SCHEMA = "cta-options-chain-v1"
SNAP_REL = Path("data") / "options" / "snapshots"


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def snapshots_root(root: Path) -> Path:
    d = Path(root) / SNAP_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_path(root: Path, code: str, asof: str) -> Path:
    code_u = str(code).upper()
    ymd = str(asof)[:10]
    return snapshots_root(root) / code_u / f"{ymd}.json"


def build_snapshot(
    *,
    code: str,
    asof: str,
    futures_contract: str,
    underlying_settle: float | None,
    option_rows: list[dict[str, Any]],
    source: str = "czce_day",
    futures_date: str | None = None,
    expiry: str | None = None,
) -> dict[str, Any]:
    code_u = str(code).upper()
    product, _ = product_from_contract(futures_contract)
    if product != code_u:
        raise ValueError(f"code {code_u} 与合约 {futures_contract} 品种不一致")
    month, legs = legs_from_czce_rows(option_rows, futures_contract=futures_contract)
    quality = assess_chain_quality(
        legs,
        asof=str(asof)[:10],
        underlying_settle=underlying_settle,
        futures_date=futures_date,
    )
    try:
        spec = get_spec(code_u, include_observe=True)
        mult = spec.multiplier
    except KeyError:
        mult = None
    return {
        "schema": SCHEMA,
        "code": code_u,
        "asof": str(asof)[:10],
        "underlying": month,
        "futures_contract": futures_contract.upper(),
        "underlying_settle": float(underlying_settle) if underlying_settle is not None else None,
        "futures_date": futures_date,
        "expiry": expiry,
        "source": source,
        "multiplier": mult,
        "quality": quality,
        "legs": legs,
        "pricing_note": quality.get("pricing_note"),
        "built_at": _iso_now(),
    }


def write_snapshot(root: Path, snap: dict[str, Any], *, allow_reject: bool = True) -> Path:
    """Persist snapshot. REJECT still written (with quality) unless allow_reject=False."""
    q = (snap.get("quality") or {}).get("status")
    if q == "REJECT" and not allow_reject:
        raise RuntimeError("chain quality REJECT; not written: " + ";".join((snap.get("quality") or {}).get("reasons") or []))
    path = snapshot_path(root, str(snap["code"]), str(snap["asof"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def resolve_option_expiry(root: Path, futures_contract: str, asof: str) -> str | None:
    """Option last-trading day for ``futures_contract`` from validated Gamma snapshots.

    Gamma Wall snapshots carry a verified ``expiry``. It is constant per contract,
    so prefer the snapshot dated ``asof`` and otherwise the newest earlier/later one.
    Returns ``YYYY-MM-DD`` or None (never guesses a date).
    """
    contract = str(futures_contract or "").upper()
    if not contract:
        return None
    gdir = Path(root) / "data" / "gamma_wall" / contract
    if not gdir.is_dir():
        return None
    asof_s = str(asof)[:10]
    exact = gdir / f"{asof_s}.json"
    others = sorted((p for p in gdir.glob("*.json") if p != exact), reverse=True)
    for path in ([exact] if exact.is_file() else []) + others:
        try:
            g = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        exp = str((g or {}).get("expiry") or "")[:10] if isinstance(g, dict) else ""
        if len(exp) == 10:
            return exp
    return None


def load_snapshot(root: Path, code: str, asof: str) -> dict[str, Any] | None:
    path = snapshot_path(root, code, asof)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # Older gamma-cache snapshots were written without ``expiry``; the IV surface
    # then fails closed (bad_or_expired_tenor). Backfill in memory only.
    if not data.get("expiry"):
        exp = resolve_option_expiry(
            root, str(data.get("futures_contract") or ""), str(data.get("asof") or asof)
        )
        if exp:
            data["expiry"] = exp
            data["expiry_source"] = "gamma_wall_snapshot"
    return data


def list_snapshot_dates(root: Path, code: str) -> list[str]:
    d = snapshots_root(root) / str(code).upper()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        out.append(p.stem)
    return out


def load_chain_series(root: Path, code: str) -> list[dict[str, Any]]:
    rows = []
    for asof in list_snapshot_dates(root, code):
        snap = load_snapshot(root, code, asof)
        if snap:
            rows.append(snap)
    return rows


def list_raw_cache_dates(root: Path, code: str) -> list[str]:
    raw = Path(root) / ".cache" / "gamma_wall" / "raw"
    if not raw.is_dir():
        return []
    out = []
    for p in sorted(raw.glob(f"{str(code).upper()}_????-??-??.json")):
        out.append(p.stem.split("_", 1)[-1])
    return out


def collect_code_from_cache(
    root: Path,
    code: str,
    *,
    month: str | None = None,
    asof_list: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Build+write snapshots from gamma raw cache. Soft per-date errors omitted."""
    from gamma_wall import OBSERVE_MONTH

    code_u = str(code).upper()
    contract = f"{code_u}{month or OBSERVE_MONTH}"
    dates = asof_list if asof_list is not None else list_raw_cache_dates(root, code_u)
    if limit is not None:
        dates = dates[-int(limit) :]
    results: list[dict[str, Any]] = []
    for asof in dates:
        try:
            snap = build_from_gamma_raw_cache(
                root, code=code_u, asof=asof, futures_contract=contract
            )
            path = write_snapshot(root, snap, allow_reject=True)
            results.append(
                {
                    "code": code_u,
                    "asof": asof,
                    "path": str(path),
                    "quality": (snap.get("quality") or {}).get("status"),
                    "n_legs": len(snap.get("legs") or []),
                }
            )
        except Exception as exc:
            results.append({"code": code_u, "asof": asof, "error": str(exc)})
    return results


def build_from_tq_live(
    root: Path,
    *,
    code: str,
    futures_contract: str | None = None,
    max_options: int = 80,
    compute_iv: bool = False,
    overall_deadline_s: float = 60.0,
) -> dict[str, Any]:
    """Live Tq chain → research snapshot (includes Bid/Ask when quote has them).

    Default is **fast Bid/Ask** (no per-leg IV) so daily accumulate cannot hang.
    Soft path: if no credentials / empty chain, raises RuntimeError for caller to soft-fail.
    Does not promote strategy_state; historical BT remains settle_discount/WARN.
    """
    from gamma_wall import OBSERVE_MONTH
    from tqsdk_client import fetch_option_chain_snapshot

    code_u = str(code).upper()
    contract = (futures_contract or f"{code_u}{OBSERVE_MONTH}").upper()
    raw = fetch_option_chain_snapshot(
        contract,
        root=Path(root),
        max_options=max_options,
        compute_iv=compute_iv,
        overall_deadline_s=overall_deadline_s,
    )
    rows = raw.get("rows") or []
    if not rows:
        notes = raw.get("notes") or []
        raise RuntimeError(f"tq live empty for {contract}: {';'.join(map(str, notes))}")

    asof = str(raw.get("asof") or "")[:10]
    if len(asof) < 10:
        from datetime import date as _date

        asof = _date.today().isoformat()
    settle = raw.get("underlying_last")
    expiry = None
    for r in rows:
        if r.get("到期日"):
            expiry = str(r["到期日"])[:10]
            break

    snap = build_snapshot(
        code=code_u,
        asof=asof,
        futures_contract=contract,
        underlying_settle=float(settle) if settle is not None else None,
        option_rows=rows,
        source="tq_live_fast" if not compute_iv else "tq_live",
        futures_date=asof,
        expiry=expiry,
    )
    snap["tq_notes"] = raw.get("notes") or []
    snap["bid_ask_coverage"] = raw.get("bid_ask_coverage")
    snap["n_with_bid_ask"] = raw.get("n_with_bid_ask")
    snap["elapsed_s"] = raw.get("elapsed_s")
    return snap


def accumulate_live_bidask(
    root: Path,
    *,
    codes: list[str] | None = None,
    month: str | None = None,
    max_options: int = 80,
    overall_deadline_s: float = 45.0,
) -> dict[str, Any]:
    """Soft daily accumulate: one live Bid/Ask snapshot per code (research only)."""
    from gamma_wall import OBSERVE_MONTH

    codes_u = [c.upper() for c in (codes or ["CF", "SR", "MA"])]
    m = month or OBSERVE_MONTH
    results: list[dict[str, Any]] = []
    for code in codes_u:
        contract = f"{code}{m}"
        try:
            snap = build_from_tq_live(
                root,
                code=code,
                futures_contract=contract,
                max_options=max_options,
                compute_iv=False,
                overall_deadline_s=overall_deadline_s,
            )
            path = write_snapshot(root, snap, allow_reject=True)
            results.append(
                {
                    "code": code,
                    "asof": snap.get("asof"),
                    "path": str(path),
                    "quality": (snap.get("quality") or {}).get("status"),
                    "n_legs": len(snap.get("legs") or []),
                    "n_with_bid_ask": snap.get("n_with_bid_ask"),
                    "elapsed_s": snap.get("elapsed_s"),
                    "ok": True,
                }
            )
        except Exception as exc:
            results.append({"code": code, "ok": False, "error": str(exc)})
    return {
        "n_ok": sum(1 for r in results if r.get("ok")),
        "n_fail": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }


def build_from_gamma_raw_cache(
    root: Path,
    *,
    code: str,
    asof: str,
    futures_contract: str | None = None,
    expiry: str | None = None,
) -> dict[str, Any]:
    """Build from gamma_wall raw cache when present (offline-friendly)."""
    from gamma_wall import MULTIPLIERS, OBSERVE_MONTH, _load_exact_contract_daily, _num, _row_on_date

    code_u = str(code).upper()
    asof_s = str(asof)[:10]
    contract = (futures_contract or f"{code_u}{OBSERVE_MONTH}").upper()
    raw_op = Path(root) / ".cache" / "gamma_wall" / "raw" / f"{code_u}_{asof_s}.json"
    if not raw_op.is_file():
        raise FileNotFoundError(f"missing gamma raw option cache: {raw_op}")
    option_rows = json.loads(raw_op.read_text(encoding="utf-8"))
    if not isinstance(option_rows, list):
        raise RuntimeError("option raw cache is not a list")

    fut_rows = _load_exact_contract_daily(contract, root=Path(root), refresh=False, need_date=asof_s)
    frow = _row_on_date(fut_rows, asof_s)
    settle = None
    futures_date = None
    if frow:
        futures_date = str(frow.get("date") or "")[:10]
        settle = _num(frow.get("settle")) or _num(frow.get("close"))
    # Fallback: read settle from existing gamma snapshot
    if settle is None:
        gpath = Path(root) / "data" / "gamma_wall" / contract / f"{asof_s}.json"
        if gpath.is_file():
            try:
                g = json.loads(gpath.read_text(encoding="utf-8"))
                settle = _num(g.get("futures_price"))
                expiry = expiry or g.get("expiry")
            except (OSError, json.JSONDecodeError):
                pass

    if not expiry:
        expiry = resolve_option_expiry(root, contract, asof_s)

    snap = build_snapshot(
        code=code_u,
        asof=asof_s,
        futures_contract=contract,
        underlying_settle=float(settle) if settle is not None else None,
        option_rows=option_rows,
        source="czce_day_gamma_cache",
        futures_date=futures_date,
        expiry=expiry,
    )
    if snap.get("multiplier") is None and code_u in MULTIPLIERS:
        snap["multiplier"] = float(MULTIPLIERS[code_u])
    return snap
