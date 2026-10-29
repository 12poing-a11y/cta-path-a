# -*- coding: utf-8 -*-
"""Option IV confirmation for futures Donchian-style breakouts (paper research).

Uses exchange-published implied vol when available (SHFE ``option_vol_shfe``,
CZCE ``option_hist_czce``). Breakouts with rising front-month IV are tagged
``true_candidate``; flat/falling IV → ``false_suspect``. Not a live order gate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# Path-A codes with listed commodity options we can pull daily IV for.
CODE_TO_OPTION: dict[str, tuple[str, str]] = {
    "RU": ("shfe", "天胶期权"),
    "AG": ("shfe", "白银期权"),
    "RB": ("shfe", "螺纹钢期权"),
    "AU": ("shfe", "黄金期权"),
    "CU": ("shfe", "铜期权"),
    "AL": ("shfe", "铝期权"),
    "MA": ("czce", "甲醇期权"),
    "TA": ("czce", "PTA期权"),
    "SR": ("czce", "白糖期权"),
    "CF": ("czce", "棉花期权"),
    "RM": ("czce", "菜籽粕期权"),
}


def iv_breakout_cfg(raw: dict | None = None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    action = str(src.get("action") or "annotate").strip().lower()
    if action not in ("annotate", "observe", "off"):
        action = "annotate"
    try:
        delta_iv = float(src.get("delta_iv_min") if src.get("delta_iv_min") is not None else 0.005)
    except (TypeError, ValueError):
        delta_iv = 0.005
    try:
        window = int(src.get("breakout_window") or 20)
    except (TypeError, ValueError):
        window = 20
    try:
        hold = int(src.get("hold_days") or 5)
    except (TypeError, ValueError):
        hold = 5
    return {
        "enabled": bool(src.get("enabled", True)),
        "action": action,
        "delta_iv_min": max(0.0, delta_iv),
        "breakout_window": max(5, window),
        "hold_days": max(1, hold),
        "note": str(src.get("note") or ""),
    }


def _cache_dir(root: Path) -> Path:
    return Path(root) / ".cache" / "akshare" / "option_iv"


def _ymd(text: str) -> str:
    return str(text or "").replace("-", "")[:8]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Any | None:
    if not path.is_file() or path.stat().st_size < 2:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def option_meta(code: str) -> tuple[str, str] | None:
    code = str(code or "").upper()
    return CODE_TO_OPTION.get(code)


def _front_iv_from_shfe_frame(frame) -> dict[str, Any] | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    vol_col = "成交量" if "成交量" in frame.columns else None
    iv_col = "隐含波动率" if "隐含波动率" in frame.columns else None
    ser_col = "合约系列" if "合约系列" in frame.columns else frame.columns[0]
    if iv_col is None:
        return None
    best = None
    best_vol = -1.0
    for _, row in frame.iterrows():
        iv = _num(row.get(iv_col))
        if iv is None or iv <= 0:
            continue
        # SHFE publishes decimal (0.26); tolerate percent.
        if iv > 3.0:
            iv = iv / 100.0
        vol = _num(row.get(vol_col)) if vol_col else 0.0
        vol = vol or 0.0
        if vol > best_vol:
            best_vol = vol
            best = {
                "iv": round(float(iv), 6),
                "series": str(row.get(ser_col) or ""),
                "volume": float(vol),
                "source": "shfe",
            }
    return best


def _front_iv_from_czce_frame(frame) -> dict[str, Any] | None:
    """Volume-weighted IV of liquid CZCE legs (IV column is percent)."""
    if frame is None or getattr(frame, "empty", True):
        return None
    iv_col = "隐含波动率" if "隐含波动率" in frame.columns else None
    vol_col = "成交量(手)" if "成交量(手)" in frame.columns else (
        "成交量" if "成交量" in frame.columns else None
    )
    if iv_col is None or vol_col is None:
        return None
    w_sum = 0.0
    iv_sum = 0.0
    n = 0
    for _, row in frame.iterrows():
        iv = _num(row.get(iv_col))
        vol = _num(row.get(vol_col))
        if iv is None or vol is None or vol <= 0 or iv <= 0:
            continue
        # CZCE IV is typically percent (e.g. 22.5).
        if iv > 3.0:
            iv = iv / 100.0
        if iv < 0.02 or iv > 1.5:
            continue
        w_sum += vol
        iv_sum += iv * vol
        n += 1
    if w_sum <= 0 or n <= 0:
        return None
    return {
        "iv": round(iv_sum / w_sum, 6),
        "series": "czce_vw",
        "volume": float(w_sum),
        "n_legs": n,
        "source": "czce",
    }


def fetch_day_iv(
    root: Path,
    code: str,
    trade_date: str,
    *,
    use_cache: bool = True,
    refresh: bool = False,
) -> dict[str, Any] | None:
    """One session front IV for ``code``. Cached under .cache/akshare/option_iv."""
    meta = option_meta(code)
    if not meta:
        return None
    venue, product = meta
    ymd = _ymd(trade_date)
    if len(ymd) != 8:
        return None
    path = _cache_dir(root) / code.upper() / f"{ymd}.json"
    if use_cache and not refresh:
        cached = _read_json(path)
        if isinstance(cached, dict) and cached.get("iv") is not None:
            return cached
        if isinstance(cached, dict) and cached.get("missing"):
            return None
    try:
        import akshare as ak
    except ImportError:
        return None
    payload: dict[str, Any] | None = None
    try:
        if venue == "shfe":
            frame = ak.option_vol_shfe(symbol=product, trade_date=ymd)
            payload = _front_iv_from_shfe_frame(frame)
        elif venue == "czce":
            frame = ak.option_hist_czce(symbol=product, trade_date=ymd)
            payload = _front_iv_from_czce_frame(frame)
    except Exception as exc:  # noqa: BLE001
        _write_json(
            path,
            {
                "missing": True,
                "code": code.upper(),
                "date": ymd,
                "error": f"{type(exc).__name__}:{str(exc)[:160]}",
            },
        )
        return None
    if not payload:
        _write_json(path, {"missing": True, "code": code.upper(), "date": ymd})
        return None
    out = {
        "code": code.upper(),
        "date": ymd,
        "product": product,
        "venue": venue,
        **payload,
    }
    _write_json(path, out)
    return out


def load_iv_series(
    root: Path,
    code: str,
    dates: list[str],
    *,
    refresh: bool = False,
    max_fetch: int = 120,
) -> dict[str, float]:
    """Map yyyymmdd → IV for requested dates (network only for cache misses)."""
    out: dict[str, float] = {}
    fetched = 0
    for day in dates:
        ymd = _ymd(day)
        path = _cache_dir(root) / code.upper() / f"{ymd}.json"
        cached = _read_json(path) if path.is_file() else None
        if (
            not refresh
            and isinstance(cached, dict)
            and cached.get("iv") is not None
        ):
            out[ymd] = float(cached["iv"])
            continue
        if isinstance(cached, dict) and cached.get("missing") and not refresh:
            continue
        if fetched >= max_fetch:
            continue
        row = fetch_day_iv(root, code, ymd, use_cache=True, refresh=refresh)
        fetched += 1
        if row and row.get("iv") is not None:
            out[ymd] = float(row["iv"])
    return out


def detect_breakouts(
    bars: list[dict],
    *,
    window: int = 20,
) -> list[dict[str, Any]]:
    """Prior-window Donchian breakouts on close (no same-bar peek)."""
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    dates: list[str] = []
    for row in bars or []:
        try:
            c = float(row["close"])
            h = float(row.get("high") if row.get("high") is not None else c)
            low = float(row.get("low") if row.get("low") is not None else c)
        except (KeyError, TypeError, ValueError):
            continue
        if c <= 0:
            continue
        closes.append(c)
        highs.append(h)
        lows.append(low)
        dates.append(str(row.get("date") or ""))
    n = len(closes)
    events: list[dict[str, Any]] = []
    for i in range(window, n):
        prior_high = max(highs[i - window : i])
        prior_low = min(lows[i - window : i])
        side = 0
        level = None
        if closes[i] > prior_high:
            side = 1
            level = prior_high
        elif closes[i] < prior_low:
            side = -1
            level = prior_low
        if side == 0 or level is None:
            continue
        events.append(
            {
                "i": i,
                "date": dates[i],
                "side": side,
                "level": level,
                "close": closes[i],
                "window": window,
            }
        )
    return events


def classify_breakout_iv(
    *,
    iv_today: float | None,
    iv_prev: float | None,
    delta_iv_min: float = 0.005,
) -> dict[str, Any]:
    """IV expansion on breakout day → true_candidate; else false_suspect."""
    if iv_today is None or iv_prev is None:
        return {
            "tag": "iv_missing",
            "delta_iv": None,
            "iv": iv_today,
            "iv_prev": iv_prev,
            "confirmed": None,
        }
    delta = float(iv_today) - float(iv_prev)
    if delta >= float(delta_iv_min):
        tag = "true_candidate"
        confirmed = True
    elif delta <= -float(delta_iv_min):
        tag = "false_suspect"
        confirmed = False
    else:
        tag = "iv_flat"
        confirmed = False
    return {
        "tag": tag,
        "delta_iv": round(delta, 6),
        "iv": round(float(iv_today), 6),
        "iv_prev": round(float(iv_prev), 6),
        "confirmed": confirmed,
    }


def breakout_held(
    bars: list[dict],
    event: dict[str, Any],
    *,
    hold_days: int = 5,
) -> dict[str, Any]:
    """Did price stay on the breakout side of ``level`` after ``hold_days``?"""
    i = int(event["i"])
    side = int(event["side"])
    level = float(event["level"])
    closes = []
    for row in bars:
        try:
            closes.append(float(row["close"]))
        except (KeyError, TypeError, ValueError):
            closes.append(float("nan"))
    j = i + hold_days
    if j >= len(closes) or math.isnan(closes[j]):
        return {"ok": False, "held": None, "fwd_ret": None, "end_close": None}
    end = closes[j]
    held = (end > level) if side > 0 else (end < level)
    start = float(event["close"])
    fwd = (end / start - 1.0) * side  # signed in breakout direction
    return {
        "ok": True,
        "held": bool(held),
        "fwd_ret": round(fwd, 6),
        "end_close": end,
        "end_date": str((bars[j] or {}).get("date") or ""),
    }


def annotate_breakouts_with_iv(
    bars: list[dict],
    iv_by_date: dict[str, float],
    *,
    window: int = 20,
    delta_iv_min: float = 0.005,
    hold_days: int = 5,
) -> list[dict[str, Any]]:
    """Merge Donchian breakouts with IV tags + forward hold outcome."""
    events = detect_breakouts(bars, window=window)
    # date → previous trading date present in bars
    bar_dates = [_ymd(str(r.get("date") or "")) for r in bars]
    prev_map: dict[str, str] = {}
    last = ""
    for d in bar_dates:
        if len(d) == 8:
            if last:
                prev_map[d] = last
            last = d
    out: list[dict[str, Any]] = []
    for ev in events:
        ymd = _ymd(ev["date"])
        prev = prev_map.get(ymd)
        iv_t = iv_by_date.get(ymd)
        iv_p = iv_by_date.get(prev) if prev else None
        tag = classify_breakout_iv(
            iv_today=iv_t, iv_prev=iv_p, delta_iv_min=delta_iv_min
        )
        outcome = breakout_held(bars, ev, hold_days=hold_days)
        out.append({**ev, **tag, **outcome, "date_ymd": ymd})
    return out


def summarize_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _bucket(name: str, pred) -> dict[str, Any]:
        subset = [r for r in rows if pred(r) and r.get("ok")]
        if not subset:
            return {"n": 0, "hold_rate": None, "avg_fwd": None}
        holds = [1.0 for r in subset if r.get("held")]
        fwds = [float(r["fwd_ret"]) for r in subset if r.get("fwd_ret") is not None]
        return {
            "n": len(subset),
            "hold_rate": round(sum(1 for r in subset if r.get("held")) / len(subset), 4),
            "avg_fwd": round(sum(fwds) / len(fwds), 6) if fwds else None,
            "holds": len(holds),
        }

    return {
        "all": _bucket("all", lambda r: True),
        "iv_confirmed": _bucket(
            "iv_confirmed", lambda r: r.get("tag") == "true_candidate"
        ),
        "iv_flat": _bucket("iv_flat", lambda r: r.get("tag") == "iv_flat"),
        "iv_suspect": _bucket(
            "iv_suspect", lambda r: r.get("tag") == "false_suspect"
        ),
        "iv_missing": _bucket("iv_missing", lambda r: r.get("tag") == "iv_missing"),
    }


def validate_code(
    root: Path,
    code: str,
    bars: list[dict],
    *,
    cfg: dict | None = None,
    lookback_bars: int = 160,
    refresh_iv: bool = False,
) -> dict[str, Any]:
    """End-to-end paper validation for one code."""
    conf = iv_breakout_cfg(cfg)
    code = str(code or "").upper()
    meta = option_meta(code)
    if not meta:
        return {"ok": False, "code": code, "error": "no_listed_option_map"}
    use = bars[-lookback_bars:] if lookback_bars and len(bars) > lookback_bars else bars
    events = detect_breakouts(use, window=int(conf["breakout_window"]))
    # Only pull IV for breakout sessions + prior bar (keeps first-run network light).
    bar_ymds = [_ymd(str(r.get("date") or "")) for r in use]
    prev_of: dict[str, str] = {}
    last = ""
    for d in bar_ymds:
        if len(d) == 8:
            if last:
                prev_of[d] = last
            last = d
    need: list[str] = []
    seen: set[str] = set()
    for ev in events:
        ymd = _ymd(ev["date"])
        for d in (ymd, prev_of.get(ymd, "")):
            if len(d) == 8 and d not in seen:
                seen.add(d)
                need.append(d)
    iv_map = load_iv_series(
        root,
        code,
        need,
        refresh=refresh_iv,
        max_fetch=max(40, len(need) + 5),
    )
    rows = annotate_breakouts_with_iv(
        use,
        iv_map,
        window=int(conf["breakout_window"]),
        delta_iv_min=float(conf["delta_iv_min"]),
        hold_days=int(conf["hold_days"]),
    )
    summary = summarize_validation(rows)
    return {
        "ok": True,
        "code": code,
        "product": meta[1],
        "venue": meta[0],
        "live_trading": False,
        "cfg": conf,
        "bars_n": len(use),
        "iv_days": len(iv_map),
        "iv_fetch_dates": len(need),
        "breakouts_n": len(rows),
        "summary": summary,
        "recent": rows[-8:],
    }


def iv_decision_gate(
    tag: str | None,
    *,
    enabled: bool,
    action: str = "annotate",
) -> dict[str, Any]:
    """Soft desk gate: observe only when action=observe and tag is false_suspect/flat."""
    out = {
        "enabled": bool(enabled),
        "action": action,
        "tag": tag or "iv_missing",
        "force_observe": False,
        "note": "",
    }
    if not enabled or action == "off":
        out["note"] = "旁路关闭"
        return out
    if action == "annotate":
        out["note"] = f"IV突破标注={out['tag']}"
        return out
    if action == "observe" and out["tag"] in ("false_suspect", "iv_flat"):
        out["force_observe"] = True
        out["note"] = "突破日隐含波动未扩张 → 决策降观望（假突破嫌疑）"
    elif out["tag"] == "true_candidate":
        out["note"] = "突破日隐含波动扩张 → 真突破候选"
    else:
        out["note"] = f"IV标签={out['tag']}"
    return out


def main() -> None:
    import argparse

    from desk.regime_board import load_local_bars

    p = argparse.ArgumentParser(description="IV breakout validation (paper)")
    p.add_argument(
        "--codes",
        default="RU,AG,RB,MA,TA",
        help="comma-separated Path-A codes",
    )
    p.add_argument("--lookback", type=int, default=120)
    p.add_argument("--refresh-iv", action="store_true")
    p.add_argument(
        "--out",
        default="lab/research/oos/iv_breakout_validate_latest.json",
    )
    args = p.parse_args()
    root = ROOT
    codes = [c.strip().upper() for c in str(args.codes).split(",") if c.strip()]
    reports = []
    for code in codes:
        bars, source = load_local_bars(root, code)
        print(f"[iv] {code} bars={len(bars)} source={source}")
        if len(bars) < 40:
            reports.append({"ok": False, "code": code, "error": "bars_short"})
            continue
        pack = validate_code(
            root,
            code,
            bars,
            lookback_bars=int(args.lookback),
            refresh_iv=bool(args.refresh_iv),
        )
        s = pack.get("summary") or {}
        print(
            f"  breakouts={pack.get('breakouts_n')} iv_days={pack.get('iv_days')} "
            f"all_hold={((s.get('all') or {}).get('hold_rate'))} "
            f"iv_ok_hold={((s.get('iv_confirmed') or {}).get('hold_rate'))} "
            f"suspect_hold={((s.get('iv_suspect') or {}).get('hold_rate'))}"
        )
        reports.append(pack)
    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "live_trading": False,
        "codes": codes,
        "reports": reports,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[iv] wrote {out_path}")


if __name__ == "__main__":
    main()
