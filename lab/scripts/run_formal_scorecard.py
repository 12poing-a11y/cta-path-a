# -*- coding: utf-8 -*-
"""A1: archive prior formal KPIs, re-run BT+PBO, write side-by-side scorecard.

Does not auto-promote Research → Path-A. Overwrites historical_backtest_latest.json
only after a successful simulate; prior file is copied to archive first.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        )
        return out.strip() or None
    except Exception:
        return None


def _snap_kpi(path: Path) -> dict:
    if not path.is_file():
        return {"missing": True, "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    cv = data.get("config_version") or {}
    return {
        "path": str(path.relative_to(ROOT)),
        "schema_version": data.get("schema_version"),
        "batch": data.get("batch"),
        "start": data.get("start"),
        "end": data.get("end"),
        "ret_pct": data.get("ret_pct"),
        "max_dd_pct": data.get("max_dd_pct"),
        "gross_ret_pct": data.get("gross_ret_pct"),
        "gross_max_dd_pct": data.get("gross_max_dd_pct"),
        "cost_yuan": data.get("cost_yuan"),
        "equity_end": data.get("equity_end"),
        "closed_trades": data.get("closed_trades"),
        "entry_filter": data.get("entry_filter"),
        "fill_price": data.get("fill_price") or data.get("fill"),
        "stop_atr_mult": data.get("stop_atr_mult"),
        "reward_rr": data.get("reward_rr"),
        "config_version": {
            "git_commit": cv.get("git_commit"),
            "execution_rules_sha256": (cv.get("execution_rules_sha256") or "")[:12] or None,
            "universe_sha256": (cv.get("universe_sha256") or "")[:12] or None,
            "research_cost_sha256": (cv.get("research_cost_sha256") or "")[:12] or None,
            "sha256": (cv.get("sha256") or "")[:12] or None,
        },
    }


def _snap_pbo(path: Path) -> dict:
    if not path.is_file():
        return {"missing": True, "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    pbo = data.get("pbo") or {}
    return {
        "path": str(path.relative_to(ROOT)),
        "pbo": pbo.get("pbo") if isinstance(pbo, dict) else pbo,
        "n_obs": (data.get("matrix_meta") or {}).get("n_obs") or pbo.get("n_obs"),
        "n_trials": (data.get("matrix_meta") or {}).get("n_trials") or pbo.get("n_trials"),
        "primary_trial_id": data.get("primary_trial_id"),
        "psr": ((data.get("psr_primary") or {}).get("psr")),
        "dsr": ((data.get("dsr_primary") or {}).get("dsr")),
        "primary_ret_pct": next(
            (
                t.get("ret_pct")
                for t in (data.get("trials") or [])
                if t.get("trial_id") == data.get("primary_trial_id")
            ),
            None,
        ),
    }


def main() -> int:
    archive = ROOT / "archive" / "scorecard"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bt_path = ROOT / "historical_backtest_latest.json"
    pbo_path = ROOT / "lab" / "research" / "validation" / "pbo_path_a_latest.json"
    readme_note = {
        "readme_claimed": {
            "schema_version": "cta-backtest-v11-next-open",
            "window": "2025-12-17→2026-11-10",
            "ret_pct": 2.25,
            "max_dd_pct": 5.57,
            "cost_yuan": 5880,
            "gross_ret_pct": 5.19,
            "note": "Stale README claim before A1 unify",
        }
    }

    before = {
        "captured_at": stamp,
        "git_head": _git_sha(),
        "readme": readme_note["readme_claimed"],
        "historical_backtest": _snap_kpi(bt_path),
        "pbo": _snap_pbo(pbo_path),
    }
    before_path = archive / f"before_{stamp}.json"
    before_path.write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if bt_path.is_file():
        shutil.copy2(bt_path, archive / f"historical_backtest_before_{stamp}.json")
    if pbo_path.is_file():
        shutil.copy2(pbo_path, archive / f"pbo_before_{stamp}.json")
    print(f"[scorecard] archived before → {before_path.relative_to(ROOT)}")

    print("[scorecard] running historical_backtest.py --fill next_open")
    rc = subprocess.call(
        [sys.executable, "historical_backtest.py", "--fill", "next_open"],
        cwd=ROOT,
    )
    if rc != 0:
        print(f"[scorecard] BT failed rc={rc}; formal file not trusted")
        return rc

    print("[scorecard] running PBO seats matrix")
    rc = subprocess.call(
        [sys.executable, "lab/scripts/run_pbo_path_a.py", "--mode", "seats"],
        cwd=ROOT,
    )
    if rc != 0:
        print(f"[scorecard] PBO failed rc={rc}")
        return rc

    after = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "git_head": _git_sha(),
        "historical_backtest": _snap_kpi(bt_path),
        "pbo": _snap_pbo(pbo_path),
        "code_schema": "cta-backtest-v13-tradability",
    }
    after_path = archive / f"after_{stamp}.json"
    after_path.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    card = {
        "ok": True,
        "schema": "cta-formal-scorecard-v1",
        "purpose": "A1 unify README / BT JSON / PBO under one code+data+cost stamp",
        "before": before,
        "after": after,
        "deltas": {
            "ret_pct": {
                "readme": before["readme"].get("ret_pct"),
                "bt_before": (before.get("historical_backtest") or {}).get("ret_pct"),
                "bt_after": (after.get("historical_backtest") or {}).get("ret_pct"),
                "pbo_primary_after": (after.get("pbo") or {}).get("primary_ret_pct"),
            },
            "max_dd_pct": {
                "readme": before["readme"].get("max_dd_pct"),
                "bt_before": (before.get("historical_backtest") or {}).get("max_dd_pct"),
                "bt_after": (after.get("historical_backtest") or {}).get("max_dd_pct"),
            },
            "pbo": {
                "before": (before.get("pbo") or {}).get("pbo"),
                "after": (after.get("pbo") or {}).get("pbo"),
            },
        },
        "live_trading": False,
        "note": "Formal KPI = after.historical_backtest; PBO is Research diagnostic only.",
    }
    out = ROOT / "lab" / "research" / "validation" / "formal_scorecard_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[scorecard] wrote {out.relative_to(ROOT)}")
    print(
        f"[scorecard] BT after ret={card['deltas']['ret_pct']['bt_after']} "
        f"dd={card['deltas']['max_dd_pct']['bt_after']} "
        f"PBO={card['deltas']['pbo']['after']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
