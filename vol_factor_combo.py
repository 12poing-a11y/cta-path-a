# -*- coding: utf-8 -*-
"""Multi-scale realized-vol proxy for Path-A research (not a full factor library).

Knowledge card: ``external/knowledge/multidim_vol_factor_card.json``.
Uses local continuous bars only: short / mid / long return std, then
short÷long as expansion ratio. Soft decision bypass — does not replace
20/60 + seats entry.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def vol_bypass_cfg(raw: dict | None = None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    action = str(src.get("action") or "observe").strip().lower()
    if action not in ("observe", "annotate", "off"):
        action = "observe"
    try:
        expand = float(src.get("expand_ratio") if src.get("expand_ratio") is not None else 1.6)
    except (TypeError, ValueError):
        expand = 1.6
    try:
        compress = float(
            src.get("compress_ratio") if src.get("compress_ratio") is not None else 0.7
        )
    except (TypeError, ValueError):
        compress = 0.7
    return {
        "enabled": bool(src.get("enabled")),
        "action": action,
        "expand_ratio": max(1.0, expand),
        "compress_ratio": min(1.0, max(0.0, compress)),
        "short_n": int(src.get("short_n") or 5),
        "mid_n": int(src.get("mid_n") or 20),
        "long_n": int(src.get("long_n") or 60),
        "note": str(src.get("note") or ""),
    }


def _std(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var)


def _ret_std(closes: list[float], end: int, n: int) -> float | None:
    """Sample std of 1-day returns over the last n bars ending at end (inclusive)."""
    if end < n or n < 2:
        return None
    rets: list[float] = []
    for i in range(end - n + 1, end + 1):
        prev = closes[i - 1]
        if prev is None or prev <= 0 or closes[i] is None:
            return None
        rets.append(closes[i] / prev - 1.0)
    return _std(rets)


def measure_vol_combo(
    bars: list[dict],
    *,
    short_n: int = 5,
    mid_n: int = 20,
    long_n: int = 60,
    expand_ratio: float = 1.6,
    compress_ratio: float = 0.7,
) -> dict[str, Any]:
    """Latest multi-scale vol snapshot. Empty bars → ok=False."""
    closes = []
    for row in bars or []:
        try:
            closes.append(float(row["close"]))
        except (KeyError, TypeError, ValueError):
            closes.append(None)  # type: ignore[arg-type]
    i = len(closes) - 1
    need = max(short_n, mid_n, long_n) + 1
    if i < need or any(c is None or c <= 0 for c in closes[i - need : i + 1]):
        return {
            "ok": False,
            "label": "样本不足",
            "regime": "unknown",
            "ratio": None,
            "vol_s": None,
            "vol_m": None,
            "vol_l": None,
        }
    # type: closes checked
    c = [float(x) for x in closes]
    vs = _ret_std(c, i, short_n)
    vm = _ret_std(c, i, mid_n)
    vl = _ret_std(c, i, long_n)
    if vs is None or vm is None or vl is None or vl <= 1e-12:
        return {
            "ok": False,
            "label": "波动率不可算",
            "regime": "unknown",
            "ratio": None,
            "vol_s": vs,
            "vol_m": vm,
            "vol_l": vl,
        }
    ratio = vs / vl
    if ratio >= expand_ratio:
        regime, label = "expand", f"高波扩张({ratio:.2f}×)"
    elif ratio <= compress_ratio:
        regime, label = "compress", f"低波压缩({ratio:.2f}×)"
    else:
        regime, label = "normal", f"波动常态({ratio:.2f}×)"
    day = str((bars[i] or {}).get("date") or "")
    return {
        "ok": True,
        "date": day,
        "label": label,
        "regime": regime,
        "ratio": round(ratio, 4),
        "vol_s": round(vs * 100.0, 4),
        "vol_m": round(vm * 100.0, 4),
        "vol_l": round(vl * 100.0, 4),
        "short_n": short_n,
        "mid_n": mid_n,
        "long_n": long_n,
        "expand_ratio": expand_ratio,
        "compress_ratio": compress_ratio,
    }


def vol_decision_gate(
    measure: dict[str, Any],
    *,
    enabled: bool,
    action: str = "observe",
) -> dict[str, Any]:
    """Soft gate for desk decision. expand+observe → force 观望."""
    out = {
        "enabled": bool(enabled),
        "action": action,
        "label": str((measure or {}).get("label") or "无读数"),
        "regime": str((measure or {}).get("regime") or "unknown"),
        "ratio": (measure or {}).get("ratio"),
        "vol_s": (measure or {}).get("vol_s"),
        "vol_m": (measure or {}).get("vol_m"),
        "vol_l": (measure or {}).get("vol_l"),
        "ok": bool((measure or {}).get("ok")),
        "force_observe": False,
        "note": "",
    }
    if not enabled or not out["ok"] or action in ("off", "annotate"):
        out["note"] = "仅标注" if action == "annotate" else ("旁路关闭" if not enabled else "")
        return out
    if out["regime"] == "expand" and action == "observe":
        out["force_observe"] = True
        out["note"] = "短窗波动相对长窗扩张，趋势追价风险升高 → 决策降观望"
    elif out["regime"] == "expand" and action == "block":
        out["force_observe"] = True
        out["note"] = "短窗波动相对长窗扩张 → 入场硬拦（仅 action=block）"
    elif out["regime"] == "compress":
        out["note"] = "低波压缩，趋势环境相对友好（不自动加仓）"
    return out


def vol_entry_block(
    hist: list[dict],
    i: int,
    *,
    enabled: bool,
    action: str = "observe",
    short_n: int = 5,
    mid_n: int = 20,
    long_n: int = 60,
    expand_ratio: float = 1.6,
    compress_ratio: float = 0.7,
) -> str | None:
    """Paper/backtest entry hard-skip — only when ``action=block``.

    Desk ``action=observe`` stays decision-only (force 观望), does not skip
    Path-A seats entries. Missing bars do not block.
    """
    if not enabled or action != "block":
        return None
    if i < 0 or not hist:
        return None
    measure = measure_vol_combo(
        hist[: i + 1],
        short_n=short_n,
        mid_n=mid_n,
        long_n=long_n,
        expand_ratio=expand_ratio,
        compress_ratio=compress_ratio,
    )
    if not measure.get("ok"):
        return None
    if measure.get("regime") == "expand":
        ratio = measure.get("ratio")
        return f"高波扩张禁开({ratio}×)" if ratio is not None else "高波扩张禁开"
    return None


def load_vol_for_code(root: Path, code: str, cfg: dict | None = None) -> dict[str, Any]:
    from desk.regime_board import load_local_bars

    conf = vol_bypass_cfg(cfg)
    bars, source = load_local_bars(root, code)
    measure = measure_vol_combo(
        bars,
        short_n=int(conf["short_n"]),
        mid_n=int(conf["mid_n"]),
        long_n=int(conf["long_n"]),
        expand_ratio=float(conf["expand_ratio"]),
        compress_ratio=float(conf["compress_ratio"]),
    )
    measure["source"] = source
    gate = vol_decision_gate(
        measure, enabled=bool(conf["enabled"]), action=str(conf["action"])
    )
    return {**measure, **{k: gate[k] for k in ("enabled", "action", "force_observe", "note")}}
