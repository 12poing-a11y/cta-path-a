# -*- coding: utf-8 -*-
"""Lab IS-frozen composite → soft trading edge (cross-section disagree veto).

Does not replace entry_filter=seats. Missing panel / thin cross-section → pass.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LAB = ROOT / "lab"
OOS_PATH = LAB / "research" / "oos" / "oos_vs_path_a_latest.json"
PANEL_PATH = LAB / "data" / "factors" / "panel_daily.jsonl"
SIGNAL_PATH = LAB / "research" / "signals" / "latest.json"


def lab_edge_bypass_cfg(raw: dict | None = None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    action = str(src.get("action") or "observe").strip().lower()
    if action not in ("observe", "block"):
        action = "observe"
    try:
        frac = float(src.get("disagree_frac") if src.get("disagree_frac") is not None else 0.2)
    except (TypeError, ValueError):
        frac = 0.2
    frac = min(0.5, max(0.05, frac))
    return {
        "enabled": bool(src.get("enabled")),
        "action": action,
        "disagree_frac": frac,
        "note": str(src.get("note") or ""),
    }


def load_frozen_members(path: Path | None = None) -> list[dict[str, Any]]:
    """IS-screened members from latest OOS report (sign + weight frozen)."""
    path = path or OOS_PATH
    if not path.is_file():
        return []
    try:
        rep = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    selected = ((rep.get("contribution") or {}).get("is_screen") or {}).get("selected") or []
    out: list[dict[str, Any]] = []
    for row in selected:
        name = str(row.get("factor") or "")
        if not name:
            continue
        try:
            sign = float(row.get("sign") if row.get("sign") is not None else 1.0)
            weight = float(row.get("weight") if row.get("weight") is not None else 0.0)
        except (TypeError, ValueError):
            continue
        if weight == 0:
            continue
        out.append({"factor": name, "sign": sign, "weight": weight})
    return out


def _zscore(vals: dict[str, float]) -> dict[str, float]:
    if len(vals) < 3:
        return {k: 0.0 for k in vals}
    xs = list(vals.values())
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / len(xs)
    sd = math.sqrt(var) if var > 1e-18 else 0.0
    if sd <= 0:
        return {k: 0.0 for k in vals}
    return {k: (v - mu) / sd for k, v in vals.items()}


def _panel_by_day(panel_path: Path | None = None) -> dict[str, list[dict]]:
    panel_path = panel_path or PANEL_PATH
    by_day: dict[str, list[dict]] = {}
    if not panel_path.is_file():
        return by_day
    with panel_path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            day = str(row.get("date") or "")
            if not day:
                continue
            by_day.setdefault(day, []).append(row)
    return by_day


def _scores_for_day(
    rows: list[dict], members: list[dict[str, Any]]
) -> dict[str, float]:
    scores: dict[str, float] = {}
    present_count: dict[str, int] = {}
    for mem in members:
        fac = mem["factor"]
        sign = float(mem["sign"])
        weight = float(mem["weight"])
        raw = {
            str(r["code"]).upper(): float(r[fac])
            for r in rows
            if r.get(fac) is not None and r.get("code")
        }
        if len(raw) < 5:
            continue
        for code, z in _zscore(raw).items():
            scores[code] = scores.get(code, 0.0) + sign * weight * z
            present_count[code] = present_count.get(code, 0) + 1
    return {c: s for c, s in scores.items() if present_count.get(c, 0) >= 2}


def latest_cross_scores(
    *,
    members: list[dict[str, Any]] | None = None,
    panel_path: Path | None = None,
    min_codes: int = 10,
) -> dict[str, Any]:
    """Composite score + percentile for the newest panel day with a full cross-section."""
    members = members if members is not None else load_frozen_members()
    by_day = _panel_by_day(panel_path)
    empty = {
        "ok": False,
        "date": None,
        "n_codes": 0,
        "scores": {},
        "percentiles": {},
        "members": members,
        "reason": "no_panel" if not by_day else "no_members",
    }
    if not by_day or not members:
        return empty
    # Walk newest → older until cross-section is thick enough (partial last day ok to skip).
    for day in sorted(by_day.keys(), reverse=True):
        scores = _scores_for_day(by_day[day], members)
        if len(scores) < min_codes:
            continue
        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        n = len(ranked)
        percentiles = {code: i / max(1, n - 1) for i, (code, _) in enumerate(ranked)}
        return {
            "ok": True,
            "date": day,
            "n_codes": n,
            "scores": {c: round(v, 6) for c, v in scores.items()},
            "percentiles": {c: round(p, 4) for c, p in percentiles.items()},
            "members": members,
            "reason": None,
        }
    last = sorted(by_day.keys())[-1] if by_day else None
    return {
        "ok": False,
        "date": last,
        "n_codes": 0,
        "scores": {},
        "percentiles": {},
        "members": members,
        "reason": "thin_cross_section",
    }


def lab_edge_decision(
    direction: str,
    code: str,
    pack: dict[str, Any] | None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Return soft veto vs proposed 多/空.

    Strong disagree: long & pct in bottom disagree_frac; short & pct in top.
    """
    cfg = lab_edge_bypass_cfg(cfg)
    code = str(code or "").upper()
    out: dict[str, Any] = {
        "enabled": bool(cfg.get("enabled")),
        "action": cfg.get("action"),
        "disagree_frac": cfg.get("disagree_frac"),
        "code": code,
        "direction": direction,
        "force_observe": False,
        "block": None,
        "label": "旁路关闭",
        "score": None,
        "percentile": None,
        "date": None,
        "agree": None,
    }
    if not cfg.get("enabled"):
        return out
    pack = pack or {}
    out["date"] = pack.get("date")
    if not pack.get("ok"):
        out["label"] = f"缺lab边({pack.get('reason') or 'no_pack'})"
        return out
    pct_map = pack.get("percentiles") or {}
    score_map = pack.get("scores") or {}
    if code not in pct_map:
        out["label"] = "缺品种lab分位·放行"
        return out
    pct = float(pct_map[code])
    score = float(score_map.get(code) or 0.0)
    frac = float(cfg.get("disagree_frac") or 0.2)
    out["percentile"] = round(pct, 4)
    out["score"] = round(score, 6)
    disagree = False
    if direction == "多" and pct <= frac:
        disagree = True
        side = f"低分位{pct:.0%}"
    elif direction == "空" and pct >= (1.0 - frac):
        disagree = True
        side = f"高分位{pct:.0%}"
    else:
        side = f"分位{pct:.0%}"
    if disagree:
        out["agree"] = False
        out["label"] = f"lab边逆向({side})"
        if cfg.get("action") == "block":
            out["block"] = f"lab边逆向禁开{direction}"
            out["force_observe"] = True
        else:
            out["force_observe"] = True
        return out
    # mild agree / mid
    if direction == "多" and pct >= (1.0 - frac):
        out["agree"] = True
        out["label"] = f"lab边同向({side})"
    elif direction == "空" and pct <= frac:
        out["agree"] = True
        out["label"] = f"lab边同向({side})"
    else:
        out["agree"] = None
        out["label"] = f"lab边中性({side})·放行"
    return out


def refresh_latest(*, root: Path | None = None, cfg: dict | None = None) -> dict[str, Any]:
    """Recompute cross scores and write lab/research/signals/latest.json."""
    root = root or ROOT
    uni_path = root / "universe.json"
    uni = {}
    if uni_path.is_file():
        try:
            uni = json.loads(uni_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            uni = {}
    cfg = lab_edge_bypass_cfg(cfg if cfg is not None else uni.get("lab_edge_bypass"))
    members = load_frozen_members(root / "lab" / "research" / "oos" / "oos_vs_path_a_latest.json")
    pack = latest_cross_scores(
        members=members,
        panel_path=root / "lab" / "data" / "factors" / "panel_daily.jsonl",
    )
    payload = {
        "ok": bool(pack.get("ok")),
        "asof": datetime.now(timezone.utc).isoformat(),
        "cfg": cfg,
        "panel_date": pack.get("date"),
        "n_codes": pack.get("n_codes"),
        "reason": pack.get("reason"),
        "members": members,
        "scores": pack.get("scores") or {},
        "percentiles": pack.get("percentiles") or {},
        "entry_filter_unchanged": "seats",
        "note": "IS-frozen composite soft edge; disagree → observe/block; missing → pass.",
    }
    out_path = root / "lab" / "research" / "signals" / "latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_latest_pack(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    path = root / "lab" / "research" / "signals" / "latest.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("scores") is not None:
                return {
                    "ok": bool(data.get("ok")),
                    "date": data.get("panel_date"),
                    "n_codes": data.get("n_codes") or 0,
                    "scores": data.get("scores") or {},
                    "percentiles": data.get("percentiles") or {},
                    "members": data.get("members") or [],
                    "reason": data.get("reason"),
                }
        except (OSError, json.JSONDecodeError):
            pass
    return latest_cross_scores(
        panel_path=root / "lab" / "data" / "factors" / "panel_daily.jsonl",
        members=load_frozen_members(root / "lab" / "research" / "oos" / "oos_vs_path_a_latest.json"),
    )


if __name__ == "__main__":
    rep = refresh_latest()
    print(
        f"[lab_signal] ok={rep.get('ok')} date={rep.get('panel_date')} "
        f"n={rep.get('n_codes')} reason={rep.get('reason')}"
    )
    pcts = rep.get("percentiles") or {}
    for code in sorted(pcts, key=lambda c: pcts[c]):
        print(f"  {code}: pct={pcts[code]:.2f} score={rep['scores'].get(code)}")
