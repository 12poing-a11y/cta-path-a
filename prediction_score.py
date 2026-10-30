# -*- coding: utf-8 -*-
"""Score desk predictions at T+1/3/5 (paper attribution).

Classes (ChatGPT research loop):
  命中 / 方向错误 / 无法判断
Amplitude band is optional V1 (no explicit target → no 幅度错误 class yet).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_log import (
    HORIZONS,
    _iso_date,
    _read_json,
    _write_json,
    _ymd,
    list_prediction_files,
    load_day,
)

ROOT = Path(__file__).resolve().parent


def load_code_bars(root: Path, code: str) -> list[tuple[str, float]]:
    """Return sorted (iso_date, close) pairs for continuous contract."""
    path = root / "lab" / "data" / "bars" / "continuous" / f"{str(code).upper()}.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return []
    rows: list[tuple[str, float]] = []
    for b in payload.get("bars") or []:
        if not isinstance(b, dict):
            continue
        d = str(b.get("date") or "")
        if not d:
            continue
        try:
            c = float(b["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if c <= 0:
            continue
        rows.append((d if "-" in d else _iso_date(d), c))
    rows.sort(key=lambda x: x[0])
    return rows


def forward_return(
    bars: list[tuple[str, float]],
    asof: str,
    horizon: int,
) -> dict[str, Any]:
    """Trading-session forward return from asof along continuous calendar."""
    if not bars or horizon <= 0:
        return {"ok": False, "error": "no_bars"}
    asof_iso = _iso_date(asof)
    asof_c = _ymd(asof)
    idx = None
    for i, (d, _) in enumerate(bars):
        if d == asof_iso or _ymd(d) == asof_c:
            idx = i
            break
    if idx is None:
        # last bar on/before asof
        for i, (d, _) in enumerate(bars):
            if _ymd(d) <= asof_c:
                idx = i
            else:
                break
    if idx is None:
        return {"ok": False, "error": "asof_not_in_bars"}
    j = idx + int(horizon)
    if j >= len(bars):
        return {
            "ok": False,
            "error": "horizon_pending",
            "entry_date": bars[idx][0],
            "entry_close": bars[idx][1],
        }
    c0 = bars[idx][1]
    c1 = bars[j][1]
    if c0 <= 0:
        return {"ok": False, "error": "bad_entry_close"}
    ret = c1 / c0 - 1.0
    return {
        "ok": True,
        "entry_date": bars[idx][0],
        "exit_date": bars[j][0],
        "entry_close": c0,
        "exit_close": c1,
        "ret": ret,
        "horizon_days": horizon,
    }


def classify_outcome(direction: str, ret: float | None) -> str:
    """Map direction × realized return → attribution class."""
    d = str(direction or "").strip()
    if d not in ("多", "空"):
        return "无法判断"
    if ret is None:
        return "无法判断"
    if abs(ret) < 1e-12:
        return "无法判断"
    if d == "多":
        return "命中" if ret > 0 else "方向错误"
    return "命中" if ret < 0 else "方向错误"


def score_prediction(
    pred: dict[str, Any],
    *,
    root: Path,
    horizons: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Mutate/return prediction with filled scores for due horizons."""
    code = str(pred.get("code") or "").upper()
    asof = _ymd(pred.get("asof"))
    direction = str(pred.get("direction") or "观望")
    bars = load_code_bars(root, code)
    hs = horizons or tuple(int(x) for x in (pred.get("horizons") or HORIZONS))
    scores = dict(pred.get("scores") or {})
    now = datetime.now(timezone.utc).isoformat()
    changed = False
    for h in hs:
        key = str(h)
        prev = scores.get(key) if isinstance(scores.get(key), dict) else {}
        if str(prev.get("status") or "") == "scored":
            continue
        if direction == "观望":
            scores[key] = {
                "status": "scored",
                "horizon_days": h,
                "class": "无法判断",
                "reason": "观望无方向",
                "scored_at": now,
            }
            changed = True
            continue
        fwd = forward_return(bars, asof, h)
        if not fwd.get("ok"):
            if fwd.get("error") == "horizon_pending":
                scores[key] = {
                    "status": "pending",
                    "horizon_days": h,
                    "entry_date": fwd.get("entry_date"),
                    "entry_close": fwd.get("entry_close"),
                }
            else:
                scores[key] = {
                    "status": "scored",
                    "horizon_days": h,
                    "class": "无法判断",
                    "reason": fwd.get("error") or "price_missing",
                    "scored_at": now,
                }
                changed = True
            continue
        ret = float(fwd["ret"])
        cls = classify_outcome(direction, ret)
        scores[key] = {
            "status": "scored",
            "horizon_days": h,
            "class": cls,
            "ret": round(ret, 6),
            "ret_pct": round(ret * 100.0, 4),
            "entry_date": fwd.get("entry_date"),
            "exit_date": fwd.get("exit_date"),
            "entry_close": fwd.get("entry_close"),
            "exit_close": fwd.get("exit_close"),
            "scored_at": now,
        }
        changed = True
    pred = {**pred, "scores": scores, "updated_at": now if changed else pred.get("updated_at")}
    return pred


def summarize(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_horizon: dict[str, dict[str, int]] = {}
    hits = misses = voids = pending = 0
    for p in predictions:
        for key, sc in (p.get("scores") or {}).items():
            if not isinstance(sc, dict):
                continue
            st = str(sc.get("status") or "")
            if st == "pending":
                pending += 1
                continue
            if st != "scored":
                continue
            cls = str(sc.get("class") or "无法判断")
            counts[cls] = counts.get(cls, 0) + 1
            bucket = by_horizon.setdefault(str(key), {})
            bucket[cls] = bucket.get(cls, 0) + 1
            if cls == "命中":
                hits += 1
            elif cls == "方向错误":
                misses += 1
            else:
                voids += 1
    decided = hits + misses
    hit_rate = (hits / decided) if decided else None
    return {
        "n_predictions": len(predictions),
        "counts": counts,
        "by_horizon": by_horizon,
        "hits": hits,
        "misses": misses,
        "voids": voids,
        "pending": pending,
        "hit_rate": None if hit_rate is None else round(hit_rate, 4),
        "hit_rate_pct": None if hit_rate is None else round(hit_rate * 100.0, 1),
    }


def score_predictions(
    root: Path | None = None,
    *,
    asof: str | None = None,
    rewrite: bool = True,
) -> dict[str, Any]:
    """Score one day or all pred_*.json files; rewrite + write summary."""
    root = Path(root or ROOT)
    files: list[Path]
    if asof:
        p = root / "lab" / "research" / "predictions" / f"pred_{_ymd(asof)}.json"
        files = [p] if p.is_file() else []
    else:
        files = list_prediction_files(root)
    if not files:
        # try latest only
        latest = load_day(root)
        if not latest:
            return {"ok": False, "error": "no_predictions", "summary": summarize([])}
        files = [root / "lab" / "research" / "predictions" / "latest.json"]

    all_preds: list[dict[str, Any]] = []
    scored_n = 0
    for path in files:
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        preds = []
        for pred in data.get("predictions") or []:
            if not isinstance(pred, dict):
                continue
            before = json.dumps(pred.get("scores") or {}, sort_keys=True)
            upd = score_prediction(pred, root=root)
            after = json.dumps(upd.get("scores") or {}, sort_keys=True)
            if before != after:
                scored_n += 1
            preds.append(upd)
            all_preds.append(upd)
        if rewrite and preds:
            data["predictions"] = preds
            data["scored_at"] = datetime.now(timezone.utc).isoformat()
            data["summary"] = summarize(preds)
            _write_json(path, data)
            if path.name != "latest.json":
                # keep latest in sync if this is the newest asof
                pass

    # Refresh latest from newest day file
    day_files = list_prediction_files(root)
    if day_files and rewrite:
        newest = _read_json(day_files[-1])
        if isinstance(newest, dict):
            _write_json(root / "lab" / "research" / "predictions" / "latest.json", newest)

    summary = summarize(all_preds)
    out = {
        "ok": True,
        "files": len(files),
        "updated_score_slots": scored_n,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_trading": False,
        "note": "纸面归因；命中=方向与到期收益同号。观望→无法判断。",
    }
    _write_json(root / "lab" / "research" / "predictions" / "score_summary.json", out)
    return out


def main() -> int:
    out = score_predictions(ROOT)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
