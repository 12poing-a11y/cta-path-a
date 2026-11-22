# -*- coding: utf-8 -*-
"""Dual-source observability: free primary vs cache / public secondary.

Default policy: never call paid keys (Tq / Fuyao / iFinD). Compare Sina free
bars against local merged history, and Eastmoney seat books against exchange
prints / Sina-fill tags already on disk.

Read-only — does not write paper_book, seats rules, or formal BT.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = "cta-dual-source-diff-v1"
DEFAULT_CLOSE_TOL_PCT = 0.15  # 0.15% ≈ a few ticks on many CZCE names
DEFAULT_LOOKBACK_DAYS = 60


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(d: Any) -> str:
    s = str(d or "").strip().replace("/", "-")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s[:10]


def _bar_index(bars: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in bars or []:
        d = _iso(row.get("date"))
        if d:
            out[d] = row
    return out


def _kind_nets_from_product(row: dict[str, Any] | None) -> dict[str, float]:
    """Collapse member legs into Path-A seat kinds (inst/foreign/holder)."""
    if not isinstance(row, dict):
        return {}
    try:
        from member_rank import _product_to_seat

        book = _product_to_seat(row)
    except Exception:
        book = None
    if not isinstance(book, dict):
        return {}
    return {
        k: float(book.get(k) or 0.0)
        for k in ("inst", "foreign", "holder")
    }


def load_history_bars(root: Path, code: str) -> list[dict]:
    path = Path(root) / ".cache" / "history" / f"{str(code).upper()}0.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    return data if isinstance(data, list) else []


def load_em_day(root: Path, ymd: str) -> dict[str, Any] | None:
    ymd = str(ymd or "").replace("-", "")
    path = Path(root) / ".cache" / "member" / f"em-{ymd}.json"
    if not path.is_file() or path.stat().st_size < 50:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def diff_bars(
    code: str,
    free_bars: list[dict],
    history_bars: list[dict],
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    close_tol_pct: float = DEFAULT_CLOSE_TOL_PCT,
    asof: date | None = None,
) -> dict[str, Any]:
    """Compare free (Sina) series vs local merged history (may include fills)."""
    code = str(code or "").upper()
    end = asof or date.today()
    start = (end - timedelta(days=max(1, int(lookback_days)))).isoformat()
    end_s = end.isoformat()

    free_ix = {
        d: r
        for d, r in _bar_index(free_bars).items()
        if start <= d <= end_s
    }
    hist_ix = {
        d: r
        for d, r in _bar_index(history_bars).items()
        if start <= d <= end_s
    }
    free_dates = set(free_ix)
    hist_dates = set(hist_ix)
    only_free = sorted(free_dates - hist_dates)
    only_hist = sorted(hist_dates - free_dates)
    overlap = sorted(free_dates & hist_dates)

    mismatches: list[dict[str, Any]] = []
    max_abs_pct = 0.0
    for d in overlap:
        fc = _f(free_ix[d].get("close"))
        hc = _f(hist_ix[d].get("close"))
        if fc is None or hc is None or fc == 0:
            continue
        pct = abs(hc - fc) / abs(fc) * 100.0
        if pct > max_abs_pct:
            max_abs_pct = pct
        if pct > float(close_tol_pct):
            mismatches.append(
                {
                    "date": d,
                    "free_close": fc,
                    "history_close": hc,
                    "abs_pct": round(pct, 4),
                }
            )

    status = "ok"
    if not free_ix and not hist_ix:
        status = "empty"
    elif mismatches:
        status = "mismatch"
    elif only_hist:
        status = "history_only_fill"
    elif only_free and not hist_ix:
        status = "free_only"

    return {
        "code": code,
        "status": status,
        "lookback_days": int(lookback_days),
        "close_tol_pct": float(close_tol_pct),
        "free_n": len(free_ix),
        "history_n": len(hist_ix),
        "overlap_n": len(overlap),
        "only_free_n": len(only_free),
        "only_history_n": len(only_hist),
        "only_history_sample": only_hist[-10:],
        "mismatch_n": len(mismatches),
        "mismatch_sample": mismatches[:20],
        "max_abs_close_pct": round(max_abs_pct, 4),
        "paid_fill_suspected": bool(only_hist),
        "note": (
            "history_only dates likely came from Tq/Fuyao/iFinD gap-fill; "
            "overlap mismatches mean free vs merged disagree."
        ),
    }


def diff_seat_product(
    code: str,
    em_row: dict[str, Any] | None,
    exchange_row: dict[str, Any] | None,
    *,
    net_tol: float = 1.0,
) -> dict[str, Any]:
    """Compare EM/Sina product book vs exchange print at inst/foreign/holder."""
    code = str(code or "").upper()
    em_row = em_row if isinstance(em_row, dict) else None
    exchange_row = exchange_row if isinstance(exchange_row, dict) else None
    src = str((em_row or {}).get("source") or "")
    out: dict[str, Any] = {
        "code": code,
        "em_present": bool(em_row) and int((em_row or {}).get("n") or 0) >= 15,
        "exchange_present": bool(exchange_row),
        "em_source": src,
        "sina_fill": "sina" in src.lower(),
        "status": "ok",
    }
    if not out["em_present"] and not out["exchange_present"]:
        out["status"] = "missing"
        return out
    if out["em_present"] and not out["exchange_present"]:
        out["status"] = "em_only"
        return out
    if out["exchange_present"] and not out["em_present"]:
        out["status"] = "exchange_only"
        return out

    em_nets = _kind_nets_from_product(em_row)
    ex_nets = {
        k: float(exchange_row.get(k) or 0.0)
        for k in ("inst", "foreign", "holder")
    }
    diffs = []
    for kind in ("inst", "foreign", "holder"):
        delta = abs(em_nets.get(kind, 0.0) - ex_nets.get(kind, 0.0))
        if delta > float(net_tol):
            diffs.append(
                {
                    "kind": kind,
                    "em_net": em_nets.get(kind, 0.0),
                    "exchange_net": ex_nets.get(kind, 0.0),
                    "abs_delta": delta,
                }
            )
    out.update(
        {
            "em_kind_nets": em_nets,
            "exchange_kind_nets": ex_nets,
            "kind_diff_n": len(diffs),
            "kind_diff_sample": diffs,
            "em_long_total": _f(em_row.get("long_total")),
            "em_short_total": _f(em_row.get("short_total")),
            "status": "mismatch" if diffs else "ok",
        }
    )
    return out


def build_report(
    root: Path,
    *,
    codes: list[str] | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    close_tol_pct: float = DEFAULT_CLOSE_TOL_PCT,
    seat_ymd: str | None = None,
    fetch_free: bool = True,
    allow_paid: bool = False,
) -> dict[str, Any]:
    """Assemble dual-source diff. ``allow_paid`` is accepted but ignored (hard off)."""
    root = Path(root)
    if allow_paid:
        # Explicit fence: this report never burns paid quota.
        pass

    if codes is None:
        try:
            uni = json.loads((root / "universe.json").read_text(encoding="utf-8"))
            codes = [
                str(u.get("code") or "").upper()
                for u in (uni.get("symbols") or [])
                if u.get("code")
            ]
        except (OSError, json.JSONDecodeError, TypeError):
            codes = []
    codes = [c for c in (codes or []) if c]

    free_loader = None
    if fetch_free:
        try:
            from market_data import load_free_bars as free_loader  # type: ignore
        except Exception:
            free_loader = None

    bar_rows: list[dict[str, Any]] = []
    for code in codes:
        free_bars: list[dict] = []
        free_meta: dict[str, Any] = {}
        if free_loader is not None:
            try:
                free_bars, free_meta = free_loader(code)
            except Exception as exc:  # noqa: BLE001
                free_meta = {"error": str(exc)[:160]}
        hist = load_history_bars(root, code)
        row = diff_bars(
            code,
            free_bars,
            hist,
            lookback_days=lookback_days,
            close_tol_pct=close_tol_pct,
        )
        row["free_source"] = free_meta.get("source") or ("sina" if free_bars else "")
        row["free_error"] = free_meta.get("sina_error") or free_meta.get("error") or ""
        row["history_path"] = f".cache/history/{code}0.json"
        bar_rows.append(row)

    # Seat day: newest em-* cache unless specified.
    member_dir = root / ".cache" / "member"
    ymd = str(seat_ymd or "").replace("-", "")
    if len(ymd) != 8:
        em_files = sorted(member_dir.glob("em-*.json")) if member_dir.is_dir() else []
        ymd = em_files[-1].stem.replace("em-", "") if em_files else ""

    seat_rows: list[dict[str, Any]] = []
    seat_fill: dict[str, str] = {}
    em_payload = load_em_day(root, ymd) if ymd else None
    products = dict((em_payload or {}).get("products") or {})
    # Exchange prints only (SHFE/CZCE). Skip DCE json — often same EM underlay.
    exchange_books: dict[str, Any] = {}
    if ymd:
        try:
            from member_rank import _czce_seats, _shfe_seats

            exchange_books.update(_shfe_seats(ymd) or {})
            exchange_books.update(_czce_seats(ymd) or {})
        except Exception:
            exchange_books = {}

    for code in codes:
        em_row = products.get(code)
        if isinstance(em_row, dict) and "sina" in str(em_row.get("source") or "").lower():
            seat_fill[code] = "sina"
        elif isinstance(em_row, dict) and em_row.get("source"):
            seat_fill[code] = str(em_row.get("source"))
        seat_rows.append(
            diff_seat_product(code, em_row, exchange_books.get(code))
        )

    bar_mismatch = sum(1 for r in bar_rows if r.get("status") == "mismatch")
    bar_fill = sum(1 for r in bar_rows if r.get("paid_fill_suspected"))
    seat_mismatch = sum(1 for r in seat_rows if r.get("status") == "mismatch")
    seat_missing = sum(1 for r in seat_rows if r.get("status") == "missing")

    summary = {
        "codes": len(codes),
        "bars_mismatch": bar_mismatch,
        "bars_paid_fill_suspected": bar_fill,
        "seats_mismatch": seat_mismatch,
        "seats_missing": seat_missing,
        "seats_sina_fill": sum(1 for v in seat_fill.values() if v == "sina"),
        "paid_calls": 0,
        "policy": "free_primary_cache_secondary_no_paid",
    }
    overall = "ok"
    if bar_mismatch or seat_mismatch:
        overall = "mismatch"
    elif bar_fill or seat_missing:
        overall = "warn"

    return {
        "schema_version": SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "seat_ymd": ymd or None,
        "lookback_days": int(lookback_days),
        "close_tol_pct": float(close_tol_pct),
        "fetch_free": bool(fetch_free),
        "allow_paid": False,
        "overall_status": overall,
        "summary": summary,
        "bars": bar_rows,
        "seats": seat_rows,
        "seat_fill": seat_fill,
        "fence": "no_paper_book_no_seats_no_formal_bt",
    }


def write_report(report: dict[str, Any], root: Path) -> Path:
    root = Path(root)
    out_dir = root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "dual_source_diff_latest.json"
    latest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return latest
