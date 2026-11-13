# -*- coding: utf-8 -*-
"""IV × OI joint changes from raw CZCE option day files."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _num(v: Any) -> float | None:
    try:
        if v is None or str(v).strip().lower() in {"", "-", "nan", "none"}:
            return None
        x = float(str(v).replace(",", "").strip())
        return x
    except (TypeError, ValueError):
        return None


def summarize_raw_day(path: Path, product: str = "CF") -> dict[str, Any] | None:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    # date from filename CF_2026-11-12.json
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    asof = m.group(1) if m else path.stem
    call_iv_oi = 0.0
    put_iv_oi = 0.0
    call_oi = 0.0
    put_oi = 0.0
    iv_w = 0.0
    oi_w = 0.0
    for row in rows:
        code = str(row.get("合约代码") or "")
        oi = _num(row.get("持仓量") or row.get("空盘量"))
        iv = _num(row.get("隐含波动率"))
        if oi is None or oi <= 0 or iv is None:
            continue
        if iv > 3:
            iv = iv / 100.0
        if not (0.005 <= iv <= 5):
            continue
        side = "C" if "C" in code[len(product) :] else ("P" if "P" in code[len(product) :] else None)
        if side is None:
            # CF701C13000 style
            if re.search(r"C\d", code):
                side = "C"
            elif re.search(r"P\d", code):
                side = "P"
            else:
                continue
        iv_w += iv * oi
        oi_w += oi
        if side == "C":
            call_oi += oi
            call_iv_oi += iv * oi
        else:
            put_oi += oi
            put_iv_oi += iv * oi
    if oi_w <= 0:
        return None
    return {
        "date": asof,
        "product": product.upper(),
        "oi_total": round(oi_w, 2),
        "call_oi": round(call_oi, 2),
        "put_oi": round(put_oi, 2),
        "iv_oi_weighted": round(iv_w / oi_w, 6),
        "call_iv_oi_weighted": None if call_oi <= 0 else round(call_iv_oi / call_oi, 6),
        "put_iv_oi_weighted": None if put_oi <= 0 else round(put_iv_oi / put_oi, 6),
    }


def iv_oi_joint_series(product: str = "CF", *, root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    raw = root / ".cache" / "gamma_wall" / "raw"
    paths = sorted(raw.glob(f"{product.upper()}_*.json"))
    series = []
    for p in paths:
        row = summarize_raw_day(p, product=product.upper())
        if row:
            series.append(row)
    changes = []
    for i in range(1, len(series)):
        a, b = series[i - 1], series[i]
        d_iv = b["iv_oi_weighted"] - a["iv_oi_weighted"]
        d_oi = b["oi_total"] - a["oi_total"]
        if d_iv > 0 and d_oi > 0:
            regime = "iv_up_oi_up"
        elif d_iv < 0 and d_oi > 0:
            regime = "iv_down_oi_up"
        elif d_iv > 0 and d_oi < 0:
            regime = "iv_up_oi_down"
        elif d_iv < 0 and d_oi < 0:
            regime = "iv_down_oi_down"
        else:
            regime = "flat"
        call_sync = None
        if a.get("call_oi") and b.get("call_oi") and a.get("put_oi") and b.get("put_oi"):
            call_sync = (b["call_oi"] - a["call_oi"]) * (b["put_oi"] - a["put_oi"]) > 0
        changes.append(
            {
                "date": b["date"],
                "d_iv": round(d_iv, 6),
                "d_oi": round(d_oi, 2),
                "regime": regime,
                "call_put_oi_same_sign": call_sync,
                "iv": b["iv_oi_weighted"],
                "oi": b["oi_total"],
            }
        )
    reg_counts: dict[str, int] = {}
    for c in changes:
        reg_counts[c["regime"]] = reg_counts.get(c["regime"], 0) + 1
    return {
        "ok": True,
        "schema": "cta-gamma-iv-oi-v1",
        "product": product.upper(),
        "n_days": len(series),
        "series": series,
        "changes": changes,
        "regime_counts": reg_counts,
        "live_trading": False,
        "note": "OI-weighted IV; not dealer direction. Prefer vol demand reading over side inference.",
    }
