# -*- coding: utf-8 -*-
"""akshare roll-yield and spot-basis helpers with local JSON cache.

Sina delivery-month files stay the primary carry source. These helpers fill
gaps when that cache is thin, and feed desk「基差极端」events. Network errors
and empty frames soft-fail; callers treat missing days as absent.
"""
from __future__ import annotations

import json
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# |dom_basis_rate| at or above this → desk event「基差极端」.
BASIS_EXTREME = 0.03


def _iso(ymd: str) -> str:
    ymd = str(ymd or "").replace("-", "")
    if len(ymd) == 8 and ymd.isdigit():
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    return str(ymd or "")


def _ymd(value: str) -> str:
    text = str(value or "").replace("-", "").strip()
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    return ""


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _basis_day_path(root: Path, ymd: str) -> Path:
    return root / ".cache" / "akshare" / "basis" / f"{ymd}.json"


def _roll_path(root: Path, code: str) -> Path:
    return root / ".cache" / "akshare" / "roll" / f"{str(code).upper()}.json"


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _read_json(path: Path) -> Any | None:
    if not path.is_file() or path.stat().st_size < 2:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _row_from_spot(rec: dict) -> dict[str, Any] | None:
    code = str(rec.get("symbol") or "").upper()
    if not code:
        return None
    day = _iso(_ymd(str(rec.get("date") or "")))
    if not day:
        return None
    near_px = _num(rec.get("near_contract_price"))
    dom_px = _num(rec.get("dominant_contract_price"))
    near_rate = _num(rec.get("near_basis_rate"))
    dom_rate = _num(rec.get("dom_basis_rate"))
    gap = None
    if near_px is not None and dom_px is not None and near_px > 0:
        gap = (dom_px - near_px) / near_px
    return {
        "date": day,
        "code": code,
        "spot": _num(rec.get("spot_price")),
        "near": str(rec.get("near_contract") or ""),
        "dominant": str(rec.get("dominant_contract") or ""),
        "near_basis_rate": near_rate,
        "dom_basis_rate": dom_rate,
        "gap": gap,
    }


def fetch_spot_basis_day(ymd: str, *, root: Path | None = None) -> dict[str, dict]:
    """One session of futures_spot_price → map code -> row. Soft-fail."""
    root = root or ROOT
    ymd = _ymd(ymd)
    if not ymd:
        return {}
    path = _basis_day_path(root, ymd)
    cached = _read_json(path)
    if isinstance(cached, dict) and cached.get("products"):
        return {str(k).upper(): v for k, v in cached["products"].items()}
    try:
        import akshare as ak
    except ImportError:
        return {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = ak.futures_spot_price(date=ymd)
    except Exception:
        return {}
    products: dict[str, dict] = {}
    try:
        records = frame.to_dict("records") if hasattr(frame, "to_dict") else []
    except Exception:
        records = []
    for rec in records:
        row = _row_from_spot(rec if isinstance(rec, dict) else {})
        if row:
            products[row["code"]] = row
    if products:
        _write_json(path, {"ymd": ymd, "source": "akshare.futures_spot_price", "products": products})
    return products


def ensure_spot_basis_range(
    root: Path,
    start_ymd: str,
    end_ymd: str,
    *,
    max_days: int = 40,
) -> int:
    """Pull missing basis days between start and end (inclusive). Returns fetches tried."""
    start = _ymd(start_ymd)
    end = _ymd(end_ymd)
    if not start or not end or start > end:
        return 0
    d0 = datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.strptime(end, "%Y%m%d").date()
    tried = 0
    cur = d1
    while cur >= d0 and tried < max_days:
        ymd = cur.strftime("%Y%m%d")
        path = _basis_day_path(root, ymd)
        if not path.is_file():
            fetch_spot_basis_day(ymd, root=root)
            tried += 1
        cur -= timedelta(days=1)
    return tried


def load_basis_series(root: Path, code: str) -> list[dict]:
    """Cached spot-basis rows for one variety, oldest first."""
    code = str(code or "").upper()
    folder = root / ".cache" / "akshare" / "basis"
    if not folder.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        products = payload.get("products") or {}
        row = products.get(code)
        if isinstance(row, dict) and row.get("date"):
            rows.append(row)
    rows.sort(key=lambda r: str(r.get("date") or ""))
    return rows


def fetch_roll_yield_bar(
    code: str,
    start_ymd: str,
    end_ymd: str,
    *,
    root: Path | None = None,
    force: bool = False,
) -> list[dict]:
    """Cache get_roll_yield_bar for SHFE/CZCE-style symbols. Soft-fail."""
    root = root or ROOT
    code = str(code or "").upper()
    start = _ymd(start_ymd)
    end = _ymd(end_ymd)
    if not code or not start or not end:
        return []
    path = _roll_path(root, code)
    if not force:
        cached = _read_json(path)
        if isinstance(cached, dict) and isinstance(cached.get("rows"), list):
            rows = [
                r
                for r in cached["rows"]
                if isinstance(r, dict) and start <= _ymd(r.get("date", "")) <= end
            ]
            if rows or cached.get("empty"):
                return rows
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = ak.get_roll_yield_bar(
                type_method="date",
                var=code,
                start_day=start,
                end_day=end,
            )
    except Exception:
        _write_json(path, {"code": code, "empty": True, "rows": [], "source": "akshare.get_roll_yield_bar"})
        return []
    rows: list[dict] = []
    if frame is not None and hasattr(frame, "iterrows") and not getattr(frame, "empty", True):
        for idx, rec in frame.iterrows():
            day = _iso(_ymd(str(idx)))
            if not day:
                day = _iso(_ymd(str(rec.get("date") or "")))
            gap = _num(rec.get("roll_yield"))
            if not day or gap is None:
                continue
            rows.append(
                {
                    "date": day,
                    "gap": float(gap),
                    "near": str(rec.get("near_by") or ""),
                    "deferred": str(rec.get("deferred") or ""),
                    "source": "roll",
                }
            )
    _write_json(
        path,
        {
            "code": code,
            "empty": not bool(rows),
            "rows": rows,
            "source": "akshare.get_roll_yield_bar",
            "start": start,
            "end": end,
        },
    )
    return rows


def carry_gaps_from_akshare(root: Path, code: str, *, lookback_days: int = 120) -> list[dict] | None:
    """Front/next gap series: prefer spot near→dominant, else roll-yield bar."""
    code = str(code or "").upper()
    end = date.today()
    start = end - timedelta(days=lookback_days)
    ensure_spot_basis_range(
        root,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        max_days=min(lookback_days, 45),
    )
    basis_rows = load_basis_series(root, code)
    gaps: list[dict] = []
    for row in basis_rows:
        gap = _num(row.get("gap"))
        day = str(row.get("date") or "")
        if gap is None or not day:
            continue
        # Skip when near and dominant are the same contract (gap ~ 0 noise).
        near = str(row.get("near") or "").upper()
        dom = str(row.get("dominant") or "").upper()
        if near and dom and near == dom:
            continue
        gaps.append({"date": day, "gap": float(gap), "source": "basis"})
    if len(gaps) >= 5:
        return gaps
    roll = fetch_roll_yield_bar(
        code,
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        root=root,
    )
    if len(roll) >= 3:
        return [{"date": r["date"], "gap": r["gap"], "source": "roll"} for r in roll]
    return gaps or None


def basis_extreme_events(root: Path, codes: set[str] | list[str]) -> list[dict]:
    """Emit 基差极端 when |dom_basis_rate| crosses BASIS_EXTREME."""
    want = {str(c).upper() for c in codes if c}
    if not want:
        return []
    # Warm a short recent window once.
    end = date.today()
    start = end - timedelta(days=25)
    ensure_spot_basis_range(root, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), max_days=20)
    events: list[dict] = []
    for code in sorted(want):
        series = load_basis_series(root, code)
        prev_side = 0
        for row in series:
            rate = _num(row.get("dom_basis_rate"))
            if rate is None:
                rate = _num(row.get("near_basis_rate"))
            if rate is None:
                continue
            if rate <= -BASIS_EXTREME:
                side = 1  # 贴水/back — 偏多
                label = "多"
            elif rate >= BASIS_EXTREME:
                side = -1
                label = "空"
            else:
                side = 0
                label = "震荡"
            if side == 0:
                prev_side = 0
                continue
            if side == prev_side:
                continue
            prev_side = side
            events.append(
                {
                    "日期": row.get("date") or "",
                    "代码": code,
                    "类型": "基差极端",
                    "细节": (
                        f"主力基差率 {rate:+.2%}，门槛 ±{BASIS_EXTREME:.0%}；"
                        f"现货 {row.get('spot')} / 主力 {row.get('dominant')}"
                    ),
                    "支持": label,
                    "标记": "事件驱动",
                }
            )
    return events
