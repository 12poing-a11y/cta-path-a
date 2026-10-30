# -*- coding: utf-8 -*-
"""Shared helpers for Plan A lab IC / OOS scripts."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parent

FACTOR_COLS = [
    "mom_20",
    "mom_60",
    "vol_s",
    "vol_m",
    "vol_l",
    "vol_ratio_sl",
    "carry_gap_pct",
    "basis_mom_20",
    "skew_60",
    "mom_vol_20",
    "hedge_pressure",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def oos_split() -> dict:
    return load_json(LAB / "config" / "oos_split.json")


def file_sha16(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def run_meta(extra: dict | None = None) -> dict:
    panel = LAB / "data" / "factors" / "panel_daily.jsonl"
    bars_mani = LAB / "data" / "bars" / "continuous_manifest.json"
    meta = {
        "plan": "A",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT).replace("\\", "/"),
        "oos_split": oos_split(),
        "panel_sha16": file_sha16(panel),
        "bars_manifest_sha16": file_sha16(bars_mani),
        "factors_registry_sha16": file_sha16(LAB / "config" / "factors_registry.json"),
    }
    if extra:
        meta.update(extra)
    return meta


def load_panel_rows() -> list[dict]:
    path = LAB / "data" / "factors" / "panel_daily.jsonl"
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
    return rows


def load_closes() -> dict[str, dict[str, float]]:
    """code -> {date: close} from lab continuous bars."""
    out: dict[str, dict[str, float]] = {}
    for path in sorted((LAB / "data" / "bars" / "continuous").glob("*.json")):
        if path.name.startswith("."):
            continue
        payload = load_json(path)
        code = str(payload.get("code") or path.stem).upper()
        out[code] = {
            str(b["date"]): float(b["close"])
            for b in (payload.get("bars") or [])
            if b.get("date") is not None and b.get("close") is not None
        }
    return out


def next_day_map(dates: list[str]) -> dict[str, str]:
    ordered = sorted(set(dates))
    return {ordered[i]: ordered[i + 1] for i in range(len(ordered) - 1)}


def attach_fwd_ret(
    rows: list[dict], closes: dict[str, dict[str, float]]
) -> list[dict]:
    """Add fwd_ret = close[t+1]/close[t]-1 using per-code calendar."""
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_code[str(r["code"]).upper()].append(r)
    out: list[dict] = []
    for code, items in by_code.items():
        items = sorted(items, key=lambda x: x["date"])
        cmap = closes.get(code) or {}
        for i, row in enumerate(items):
            day = row["date"]
            nxt = items[i + 1]["date"] if i + 1 < len(items) else None
            c0 = cmap.get(day)
            c1 = cmap.get(nxt) if nxt else None
            fwd = None
            if c0 and c1 and c0 > 0:
                fwd = c1 / c0 - 1.0
            out.append({**row, "fwd_ret": fwd, "next_date": nxt})
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx <= 1e-15 or dy <= 1e-15:
        return None
    return num / (dx * dy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    if len(xs) < 3:
        return None
    return pearson(ranks(xs), ranks(ys))


def mean_std(vals: list[float]) -> tuple[float | None, float | None]:
    if not vals:
        return None, None
    mu = sum(vals) / len(vals)
    if len(vals) < 2:
        return mu, None
    var = sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)
    return mu, math.sqrt(var) if var > 0 else 0.0


def max_dd(equity: list[float]) -> float:
    peak = equity[0] if equity else 0.0
    dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak)
    return dd * 100.0


def window_mask(day: str, start: str | None, end: str | None) -> bool:
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True
