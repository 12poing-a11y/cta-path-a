# -*- coding: utf-8 -*-
"""Fetch and cache futures minute bars (15m / 60m).

Primary: Sina via ``akshare.futures_zh_minute_sina``.
Backup / cross-check: East Money ``push2his`` K-line API (klt=15/60).

Uses the front-month (highest OI) contract from local ``.cache/sina`` month
files, or continuous ``{CODE}0`` when months are missing. Batch entry point:
``refresh_universe_minutes`` (wired from ``daily_update`` / GitHub Actions).
Soft-fails on network / empty responses; never fabricates bars.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent
CACHE_DIR = REPO_ROOT / ".cache" / "akshare" / "minute"
PERIODS = ("15", "60")
# Long enough that a same-day ``git pull`` of CI caches still counts as fresh.
TTL_SEC = 18 * 3600

# East Money market id (qhweb / push2his secid prefix).
_EM_MKT = {"SHFE": "113", "INE": "142", "DCE": "114", "CZCE": "115", "CFFEX": "8"}
_EM_KLT = {"15": "15", "60": "60"}
_EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _latest_sina_day(root: Path) -> Path | None:
    sina = root / ".cache" / "sina"
    if not sina.is_dir():
        return None
    days = sorted([p for p in sina.iterdir() if p.is_dir() and p.name[:4].isdigit()], reverse=True)
    return days[0] if days else None


def resolve_dominant_contract(root: Path, code: str) -> dict[str, Any] | None:
    """Pick local month file with highest last-bar open interest (exclude CODE0)."""
    code = str(code or "").upper()
    day = _latest_sina_day(root)
    if day is None:
        return None
    best: tuple[float, str, str, Path] | None = None
    for path in day.glob(f"{code}*.json"):
        stem = path.stem.upper()
        if stem == f"{code}0":
            continue
        if not stem.startswith(code) or len(stem) <= len(code):
            continue
        # Require month digits after the root (avoid P matching PP*.json).
        rest = stem[len(code) :]
        if not rest[:1].isdigit():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list) or not rows:
            continue
        last = rows[-1] if isinstance(rows[-1], dict) else {}
        oi = float(last.get("open_interest") or 0)
        bar_date = str(last.get("date") or "")[:10]
        if best is None or oi > best[0]:
            best = (oi, stem, bar_date, path)
    if best is None:
        return None
    oi, stem, bar_date, path = best
    return {
        "symbol": stem,
        "code": code,
        "oi": oi,
        "bar_date": bar_date,
        "source": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
    }


def _cache_path(root: Path, symbol: str, period: str, *, source: str = "sina") -> Path:
    folder = root / ".cache" / "akshare" / "minute"
    folder.mkdir(parents=True, exist_ok=True)
    tag = "em" if source == "em" else "sina"
    return folder / f"{symbol.upper()}_{period}_{tag}.json"


def _http_get(url: str, params: dict[str, Any], *, timeout: int = 20) -> dict[str, Any]:
    """GET JSON; prefer direct connect (EM is often broken by local HTTP_PROXY)."""
    last_exc: Exception | None = None
    attempts = (
        # Empty string disables proxy for that scheme in requests.
        {"trust_env": False, "proxies": {"http": "", "https": ""}},
        {"trust_env": True, "proxies": None},
    )
    for opts in attempts:
        try:
            session = requests.Session()
            session.trust_env = bool(opts["trust_env"])
            kwargs: dict[str, Any] = {"params": params, "timeout": timeout}
            if opts["proxies"] is not None:
                kwargs["proxies"] = opts["proxies"]
            resp = session.get(url, **kwargs)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    raise RuntimeError(str(last_exc) if last_exc else "HTTP failed")


def em_contract_symbol(symbol: str, exchange: str) -> str:
    """Map Sina-style CF2701 → EM contract code (CZCE uses 3-digit YMM)."""
    symbol = str(symbol or "").upper()
    exchange = str(exchange or "").upper()
    match = re.match(r"^([A-Z]+)(\d{3,4})$", symbol)
    if not match:
        return symbol
    root, yymm = match.group(1), match.group(2)
    if exchange == "CZCE" and len(yymm) == 4:
        return f"{root}{yymm[1:]}"
    return f"{root}{yymm}"


def em_secid(symbol: str, exchange: str) -> str | None:
    mkt = _EM_MKT.get(str(exchange or "").upper())
    if not mkt:
        return None
    return f"{mkt}.{em_contract_symbol(symbol, exchange)}"


def exchange_for_code(root: Path, code: str) -> str:
    code = str(code or "").upper()
    try:
        from desk.seat_board import universe_rows

        for row in universe_rows(root):
            if row.get("code") == code:
                return str(row.get("exchange") or "DCE")
    except Exception:  # noqa: BLE001
        pass
    return "DCE"


def _load_cache(path: Path, *, ttl: int = TTL_SEC) -> list[dict] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    fetched = float(payload.get("fetched_at") or 0)
    if ttl > 0 and fetched and (time.time() - fetched) > ttl:
        return None
    rows = payload.get("bars")
    return rows if isinstance(rows, list) and rows else None


def _save_cache(path: Path, symbol: str, period: str, bars: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": symbol,
        "period": period,
        "fetched_at": time.time(),
        "n": len(bars),
        "bars": bars,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def fetch_minute_bars_sina(
    symbol: str,
    period: str = "15",
    *,
    root: Path | None = None,
    force: bool = False,
) -> tuple[list[dict], str]:
    """Sina minute bars via akshare. Soft-fail → ([], reason)."""
    root = root or REPO_ROOT
    symbol = str(symbol or "").upper()
    period = str(period or "15")
    if period not in PERIODS:
        return [], f"不支持的周期 {period}（仅 15 / 60）"
    if not symbol:
        return [], "无合约代码"
    path = _cache_path(root, symbol, period, source="sina")
    if not force:
        cached = _load_cache(path)
        if cached is not None:
            return cached, f"sina-cache {path.name}"
    try:
        import akshare as ak
    except ImportError:
        return [], "未安装 akshare"
    try:
        frame = ak.futures_zh_minute_sina(symbol=symbol, period=period)
    except Exception as exc:  # noqa: BLE001
        stale = _load_cache(path, ttl=0)
        if stale:
            return stale, f"sina 失败，用旧缓存：{exc}"
        return [], f"sina 失败：{exc}"
    if frame is None or getattr(frame, "empty", True):
        stale = _load_cache(path, ttl=0)
        if stale:
            return stale, "sina 空响应，用旧缓存"
        return [], "sina 空响应"
    bars: list[dict] = []
    for _, row in frame.iterrows():
        dt = str(row.get("datetime") or "")
        close = row.get("close")
        if not dt or close is None:
            continue
        bars.append(
            {
                "datetime": dt,
                "date": dt[:10],
                "open": float(row.get("open") or close),
                "high": float(row.get("high") or close),
                "low": float(row.get("low") or close),
                "close": float(close),
                "volume": float(row.get("volume") or 0),
                "hold": float(row.get("hold") or 0),
                "source": "sina",
            }
        )
    if not bars:
        return [], "sina 无有效分钟行"
    _save_cache(path, symbol, period, bars)
    return bars, f"sina {symbol} {period}m n={len(bars)}"


def fetch_minute_bars_em(
    symbol: str,
    exchange: str,
    period: str = "15",
    *,
    root: Path | None = None,
    force: bool = False,
    limit: int = 1023,
) -> tuple[list[dict], str]:
    """East Money minute bars (backup / verify). Soft-fail → ([], reason)."""
    root = root or REPO_ROOT
    symbol = str(symbol or "").upper()
    period = str(period or "15")
    if period not in PERIODS:
        return [], f"不支持的周期 {period}（仅 15 / 60）"
    secid = em_secid(symbol, exchange)
    if not secid:
        return [], f"东财无交易所映射 {exchange}"
    em_sym = em_contract_symbol(symbol, exchange)
    path = _cache_path(root, f"{exchange}_{em_sym}", period, source="em")
    if not force:
        cached = _load_cache(path)
        if cached is not None:
            return cached, f"em-cache {path.name}"
    params = {
        "secid": secid,
        "klt": _EM_KLT[period],
        "fqt": "1",
        "lmt": str(max(50, min(int(limit), 5000))),
        "end": "20500000",
        "iscca": "1",
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "forcect": "1",
    }
    try:
        payload = _http_get(_EM_URL, params)
    except Exception as exc:  # noqa: BLE001
        stale = _load_cache(path, ttl=0)
        if stale:
            return stale, f"东财失败，用旧缓存：{exc}"
        return [], f"东财失败：{exc}"
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        stale = _load_cache(path, ttl=0)
        if stale:
            return stale, "东财空响应，用旧缓存"
        return [], "东财空响应"
    klines = data.get("klines") or []
    bars: list[dict] = []
    for item in klines:
        parts = str(item).split(",")
        if len(parts) < 6:
            continue
        dt = parts[0].strip()
        try:
            open_, close, high, low = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            volume = float(parts[5])
        except ValueError:
            continue
        hold = 0.0
        if len(parts) > 12:
            try:
                hold = float(parts[12])
            except ValueError:
                hold = 0.0
        # EM field order: time, open, close, high, low, volume, ...
        bars.append(
            {
                "datetime": dt if " " in dt else f"{dt} 00:00:00",
                "date": dt[:10],
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "hold": hold,
                "source": "em",
            }
        )
    if not bars:
        return [], f"东财无 K 线 secid={secid}"
    _save_cache(path, em_sym, period, bars)
    name = data.get("name") or em_sym
    return bars, f"em {name} {secid} {period}m n={len(bars)}"


def fetch_minute_bars(
    symbol: str,
    period: str = "15",
    *,
    root: Path | None = None,
    force: bool = False,
    exchange: str | None = None,
) -> tuple[list[dict], str]:
    """Primary Sina, fallback East Money when Sina is empty."""
    root = root or REPO_ROOT
    bars, note = fetch_minute_bars_sina(symbol, period, root=root, force=force)
    if bars:
        return bars, note
    if not exchange:
        return bars, note
    em_bars, em_note = fetch_minute_bars_em(symbol, exchange, period, root=root, force=force)
    if em_bars:
        return em_bars, f"{note} → 改用东财：{em_note}"
    return [], f"{note}；{em_note}"


def verify_minute_vs_em(
    sina_bars: list[dict],
    em_bars: list[dict],
    *,
    last_n: int = 16,
) -> dict[str, Any]:
    """Cross-check recent closes/volumes between Sina and East Money."""
    if not sina_bars or not em_bars:
        return {
            "ok": False,
            "note": "一侧无数据，无法交叉验证",
            "overlap": 0,
        }
    sina = {str(r["datetime"])[:16]: r for r in sina_bars}
    em = {str(r["datetime"])[:16]: r for r in em_bars}
    keys = sorted(set(sina) & set(em))[-last_n:]
    if not keys:
        return {"ok": False, "note": "时间轴无重叠", "overlap": 0}
    close_diffs: list[float] = []
    vol_ratios: list[float] = []
    for key in keys:
        a, b = sina[key], em[key]
        ca, cb = float(a["close"]), float(b["close"])
        if ca > 0:
            close_diffs.append(abs(ca - cb) / ca)
        va, vb = float(a.get("volume") or 0), float(b.get("volume") or 0)
        base = max(va, vb, 1.0)
        vol_diffs.append(abs(va - vb) / base)
    med_c = float(pd.Series(close_diffs).median()) if close_diffs else None
    med_v = float(pd.Series(vol_diffs).median()) if vol_diffs else None
    # Price within 0.3%, volume median relative gap under 35% → pass.
    ok = med_c is not None and med_c <= 0.003 and med_v is not None and med_v <= 0.35
    return {
        "ok": ok,
        "overlap": len(keys),
        "median_close_rel": None if med_c is None else round(med_c, 5),
        "median_volume_rel": None if med_v is None else round(med_v, 4),
        "last_key": keys[-1],
        "sina_last_vol": float(sina[keys[-1]].get("volume") or 0),
        "em_last_vol": float(em[keys[-1]].get("volume") or 0),
        "note": "东财交叉验证通过" if ok else "东财与新浪量价偏差偏大，仅作参考",
    }


def ensure_minute_for_code(
    root: Path,
    code: str,
    period: str = "15",
    *,
    force: bool = False,
    verify_em: bool = True,
) -> dict[str, Any]:
    """Resolve dominant contract; Sina first, East Money backup + optional verify.

    Falls back to continuous ``{CODE}0`` when month files are missing (CI / fresh clone).
    """
    code = str(code or "").upper()
    period = str(period or "15")
    dom = resolve_dominant_contract(root, code)
    if not dom:
        dom = {
            "symbol": f"{code}0",
            "code": code,
            "oi": None,
            "bar_date": "",
            "source": "continuous_fallback",
        }
    exchange = exchange_for_code(root, code)
    sina_bars, sina_note = fetch_minute_bars_sina(dom["symbol"], period, root=root, force=force)
    em_bars, em_note = ([], "")
    if verify_em or not sina_bars:
        em_bars, em_note = fetch_minute_bars_em(
            dom["symbol"], exchange, period, root=root, force=force
        )
    source = "sina"
    bars = sina_bars
    note = sina_note
    if not bars and em_bars:
        bars = em_bars
        source = "em"
        note = f"sina 不可用，改用东财：{em_note}"
    verify = None
    if sina_bars and em_bars:
        verify = verify_minute_vs_em(sina_bars, em_bars)
        note = f"{note}；{verify.get('note')}"
    elif em_note and source == "sina":
        note = f"{note}；东财备选：{em_note}"
    return {
        "ok": bool(bars),
        "code": code,
        "period": period,
        "symbol": dom["symbol"],
        "exchange": exchange,
        "oi": dom.get("oi"),
        "bars": bars,
        "source": source,
        "note": note,
        "contract_source": dom.get("source"),
        "verify": verify,
        "em_symbol": em_contract_symbol(dom["symbol"], exchange),
    }


def minute_frame(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["datetime", "date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
    return df.reset_index(drop=True)


def refresh_universe_minutes(
    root: Path,
    codes: list[str],
    *,
    periods: tuple[str, ...] = PERIODS,
    force: bool = True,
    verify_em: bool = False,
) -> dict[str, Any]:
    """Batch-pull 15m/60m for Path-A codes into ``.cache/akshare/minute``.

    Intended for ``daily_update`` / GitHub Actions so locals can ``git pull`` the cache.
    """
    root = Path(root)
    summary: dict[str, Any] = {
        "ok": 0,
        "fail": 0,
        "periods": list(periods),
        "rows": [],
    }
    for code in codes:
        code = str(code or "").upper()
        if not code:
            continue
        for period in periods:
            pack = ensure_minute_for_code(
                root, code, period, force=force, verify_em=verify_em
            )
            n = len(pack.get("bars") or [])
            row = {
                "code": code,
                "period": period,
                "ok": bool(pack.get("ok")),
                "n": n,
                "symbol": pack.get("symbol"),
                "source": pack.get("source"),
                "note": str(pack.get("note") or "")[:160],
            }
            summary["rows"].append(row)
            if pack.get("ok") and n > 0:
                summary["ok"] += 1
                print(f"  [minute] {code} {period}m ok n={n} src={pack.get('source')} {pack.get('symbol')}")
            else:
                summary["fail"] += 1
                print(f"  [minute] {code} {period}m FAIL {pack.get('note')}")
    return summary
