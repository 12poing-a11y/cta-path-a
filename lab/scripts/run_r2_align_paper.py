# -*- coding: utf-8 -*-
"""Paper check: Path-A closed trades vs trend-R2 at entry (agree / disagree / flat).

Uses the same seats Path-A simulate as historical_backtest; R2 params from
desk/model_vote_weights.json. Does not change entry_filter.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from desk.regime_board import _trend_r2_calls, load_vote_weights  # noqa: E402
from historical_backtest import _fetch_pack, _load_cfg, _simulate_cfg  # noqa: E402


def _dir_from_signal(sig: int) -> str:
    if sig > 0:
        return "多"
    if sig < 0:
        return "空"
    return "震荡"


def _r2_map_for_code(hist: list[dict], *, window: int, r2_min: float) -> dict[str, str]:
    calls = _trend_r2_calls(hist, window=window, r2_min=r2_min)
    return {str(c["date"]): _dir_from_signal(int(c["signal"])) for c in calls}


def _bucket_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"ok": False, "n": 0}
    rs = [float(t["R"]) for t in rows]
    wins = sum(1 for r in rs if r > 0)
    return {
        "ok": True,
        "n": len(rows),
        "win_rate_pct": round(100.0 * wins / len(rows), 2),
        "mean_R": round(sum(rs) / len(rs), 3),
        "sum_R": round(sum(rs), 3),
        "median_R": round(sorted(rs)[len(rs) // 2], 3),
        "pos_n": wins,
        "neg_n": len(rows) - wins,
    }


def main() -> int:
    p = _load_cfg()
    vote = load_vote_weights(ROOT)
    tr = vote.get("trend_r2") or {}
    window = int(tr.get("window") or 60)
    r2_min = float(tr.get("r2_min") or 0.2)
    mode = "seats"
    print(f"[r2-align] mode={mode} r2_window={window} r2_min={r2_min}")
    pack = _fetch_pack(p["cfg"]["symbols"])
    series, _errors, _sources = pack
    out = _simulate_cfg(p, mode, pack=pack)
    if not out.get("ok"):
        print("[r2-align] simulate failed", out.get("errors"))
        return 1
    trades = list(out.get("closed_pnls") or out.get("closed_pnls_tail") or [])
    # R2 direction by code/date
    r2_by_code: dict[str, dict[str, str]] = {}
    for code, s in series.items():
        r2_by_code[str(code).upper()] = _r2_map_for_code(
            s["hist"], window=window, r2_min=r2_min
        )

    # Secondary: slope sign only (r2_min=0) — more disagrees for diagnostic.
    r2_raw_by_code: dict[str, dict[str, str]] = {}
    for code, s in series.items():
        r2_raw_by_code[str(code).upper()] = _r2_map_for_code(
            s["hist"], window=window, r2_min=0.0
        )

    def _align(direction: str, r2_dir: str | None) -> str:
        if r2_dir is None:
            return "missing"
        if r2_dir == "震荡":
            return "flat"
        if direction in ("多", "空") and r2_dir == direction:
            return "agree"
        if direction in ("多", "空") and r2_dir in ("多", "空"):
            return "disagree"
        return "flat"

    annotated = []
    for t in trades:
        code = str(t.get("code") or "").upper()
        entry = str(t.get("entry_date") or "")
        direction = str(t.get("direction") or "")
        r2_dir = (r2_by_code.get(code) or {}).get(entry)
        r2_raw = (r2_raw_by_code.get(code) or {}).get(entry)
        row = {
            **{k: t.get(k) for k in ("code", "direction", "entry_date", "date", "R", "reason")},
            "r2_dir": r2_dir or "—",
            "r2_dir_raw": r2_raw or "—",
            "align": _align(direction, r2_dir),
            "align_raw": _align(direction, r2_raw),
        }
        annotated.append(row)

    def _bucketize(key: str) -> dict:
        by = defaultdict(list)
        for row in annotated:
            by[row[key]].append(row)
        return {k: _bucket_stats(v) for k, v in by.items()}

    buckets = _bucketize("align")
    buckets_raw = _bucketize("align_raw")
    agree = buckets.get("agree") or {"ok": False, "n": 0, "mean_R": None}
    disagree = buckets.get("disagree") or {"ok": False, "n": 0, "mean_R": None}
    agree_r = buckets_raw.get("agree") or {"ok": False, "n": 0, "mean_R": None}
    disagree_r = buckets_raw.get("disagree") or {"ok": False, "n": 0, "mean_R": None}

    # Decision hint for observe bypass (no auto-enable).
    hint = "样本不足，暂不建议改旁路"
    edge = None
    if agree.get("ok") and disagree.get("ok") and agree["n"] >= 8 and disagree["n"] >= 5:
        edge = round(float(agree["mean_R"]) - float(disagree["mean_R"]), 3)
        if edge >= 0.25 and float(disagree["mean_R"]) < 0:
            hint = (
                f"disagree 组 mean_R={disagree['mean_R']} 且低于 agree {edge}R；"
                "可讨论把趋势R2逆向升为 decision observe 旁路（仍不改 seats）。"
            )
        elif edge >= 0.15:
            hint = f"agree 优于 disagree 约 {edge}R；继续观察，阈值未到强旁路。"
        else:
            hint = f"agree−disagree 仅 {edge}R，暂不升旁路。"
    elif (disagree.get("n") or 0) == 0 and (agree.get("n") or 0) >= 10:
        # Official threshold: Path-A almost never opens against active R2.
        raw_edge = None
        if agree_r.get("ok") and disagree_r.get("ok") and disagree_r["n"] >= 5:
            raw_edge = round(float(agree_r["mean_R"]) - float(disagree_r["mean_R"]), 3)
        hint = (
            "正式R²阈下 Path-A 开仓几乎不与「有方向的R2」逆向（disagree=0），"
            "升 observe 旁路历史触发极少。"
        )
        if raw_edge is not None:
            hint += f" 斜率符号对照 agree−disagree≈{raw_edge}R（仅诊断）。"
            edge = raw_edge

    report = {
        "ok": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "window": {
            "start": out.get("start"),
            "end": out.get("end"),
            "ret_pct": out.get("ret_pct"),
            "max_dd_pct": out.get("max_dd_pct"),
            "closed_trades": out.get("closed_trades"),
        },
        "trend_r2": {"window": window, "r2_min": r2_min},
        "buckets": buckets,
        "buckets_slope_only": buckets_raw,
        "agree_minus_disagree_mean_R": edge,
        "hint": hint,
        "trades": annotated,
        "note": (
            "align=入场日趋势R2(R²≥阈)与开仓方向；"
            "align_raw=忽略R²阈只看斜率符号（诊断）。纸面R乘数。"
        ),
        "entry_filter_unchanged": "seats",
    }
    out_path = ROOT / "lab" / "research" / "oos" / "r2_align_paper_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # trim huge trade dump in stamp only keep summary+trades in latest
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stamp = report["created_at"][:19].replace(":", "").replace("-", "")
    run_dir = ROOT / "lab" / "research" / "runs" / f"r2_align_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("=== R2 align paper (seats Path-A) ===")
    print(f"window {out.get('start')}→{out.get('end')} trades={len(annotated)}")
    print("-- official R² threshold --")
    for name in ("agree", "disagree", "flat", "missing"):
        b = buckets.get(name) or {"n": 0}
        print(
            f"  {name}: n={b.get('n')} win%={b.get('win_rate_pct')} "
            f"mean_R={b.get('mean_R')} sum_R={b.get('sum_R')}"
        )
    print("-- slope-only (r2_min=0) --")
    for name in ("agree", "disagree", "flat", "missing"):
        b = buckets_raw.get(name) or {"n": 0}
        print(
            f"  {name}: n={b.get('n')} win%={b.get('win_rate_pct')} "
            f"mean_R={b.get('mean_R')} sum_R={b.get('sum_R')}"
        )
    print(f"agree−disagree mean_R: {edge}")
    print(f"hint: {hint}")
    print(f"[r2-align] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
