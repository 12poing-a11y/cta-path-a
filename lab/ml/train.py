# -*- coding: utf-8 -*-
"""Train P4 light binary models with time-based OOS split."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    if not rows:
        return np.zeros((0, 0)), np.zeros(0), [], []
    keys = sorted(rows[0]["features"].keys())
    x = np.array([[float(r["features"][k]) for k in keys] for r in rows], dtype=float)
    y = np.array([int(r["y"]) for r in rows], dtype=int)
    ts = [str(r.get("timestamp") or "") for r in rows]
    return x, y, keys, ts


def _time_split(n: int, oos_frac: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    cut = max(1, int(n * (1.0 - oos_frac)))
    if cut >= n:
        cut = n - 1
    tr = np.arange(0, cut)
    te = np.arange(cut, n)
    return tr, te


def _metrics(y_true: np.ndarray, proba: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        f1_score,
        roc_auc_score,
    )

    out: dict[str, Any] = {
        "n": int(len(y_true)),
        "pos_rate": float(y_true.mean()) if len(y_true) else None,
        "accuracy": float(accuracy_score(y_true, pred)) if len(y_true) else None,
        "f1": float(f1_score(y_true, pred, zero_division=0)) if len(y_true) else None,
        "brier": float(brier_score_loss(y_true, proba)) if len(y_true) else None,
    }
    if len(y_true) and len(set(y_true.tolist())) > 1:
        out["auc"] = float(roc_auc_score(y_true, proba))
    else:
        out["auc"] = None
    return out


def train_binary_task(
    rows: list[dict[str, Any]],
    *,
    task: str,
    oos_frac: float = 0.3,
) -> dict[str, Any]:
    x, y, keys, ts = _matrix(rows)
    if len(y) < 40:
        return {"ok": False, "task": task, "error": "insufficient_samples", "n": int(len(y))}
    # chronological order by timestamp
    order = np.argsort(np.array(ts))
    x, y = x[order], y[order]
    ts = [ts[i] for i in order]
    tr, te = _time_split(len(y), oos_frac=oos_frac)
    if len(te) < 10 or len(set(y[tr].tolist())) < 2:
        return {"ok": False, "task": task, "error": "bad_split", "n": int(len(y))}

    try:
        import lightgbm as lgb

        model = lgb.LGBMClassifier(
            n_estimators=80,
            learning_rate=0.05,
            num_leaves=15,
            min_child_samples=10,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            verbose=-1,
        )
        backend = "lightgbm"
    except Exception:
        from sklearn.ensemble import HistGradientBoostingClassifier

        model = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=80, random_state=42)
        backend = "sklearn_hist_gbm"

    model.fit(x[tr], y[tr])
    proba_tr = model.predict_proba(x[tr])[:, 1]
    proba_te = model.predict_proba(x[te])[:, 1]
    pred_tr = (proba_tr >= 0.5).astype(int)
    pred_te = (proba_te >= 0.5).astype(int)

    # Feature importance
    if hasattr(model, "feature_importances_"):
        imp = list(map(float, model.feature_importances_))
    else:
        imp = [0.0] * len(keys)
    importance = sorted(
        [{"feature": k, "importance": round(v, 6)} for k, v in zip(keys, imp)],
        key=lambda r: -r["importance"],
    )

    return {
        "ok": True,
        "task": task,
        "backend": backend,
        "n": int(len(y)),
        "n_train": int(len(tr)),
        "n_oos": int(len(te)),
        "features": keys,
        "is": _metrics(y[tr], proba_tr, pred_tr),
        "oos": _metrics(y[te], proba_te, pred_te),
        "importance_top": importance[:12],
        "oos_window": {"start": ts[te[0]], "end": ts[te[-1]]},
        "is_window": {"start": ts[tr[0]], "end": ts[tr[-1]]},
        "live_trading": False,
        "auto_promote": False,
        "note": "Research only; probabilities are not Path-A entry rules.",
    }


def run_p4_light(root: Path | None = None) -> dict[str, Any]:
    from lab.ml.labels import (
        daily_signal_rows,
        load_daily_bars,
        load_lsp_events,
        lsp_reversal_rows,
    )

    root = root or ROOT
    events = load_lsp_events(root, "15m")
    lsp_rows = lsp_reversal_rows(events)
    lsp = train_binary_task(lsp_rows, task="lsp_reversal")

    daily = load_daily_bars("CF", root=root)
    trend_rows, break_rows = daily_signal_rows(daily) if daily else ([], [])
    trend = train_binary_task(trend_rows, task="trend_fail")
    brk = train_binary_task(break_rows, task="breakout_continue")

    return {
        "ok": True,
        "schema": "cta-p4-light-v1",
        "status": "Research",
        "live_trading": False,
        "tasks": {
            "lsp_reversal": lsp,
            "trend_fail": trend,
            "breakout_continue": brk,
        },
        "sample_counts": {
            "lsp_events": len(events),
            "lsp_rows": len(lsp_rows),
            "trend_rows": len(trend_rows),
            "breakout_rows": len(break_rows),
            "daily_bars": len(daily),
        },
    }


def save_p4_light(payload: dict[str, Any], root: Path | None = None) -> str:
    root = root or ROOT
    out = root / "lab" / "research" / "ml" / "p4_light_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out.relative_to(root))
