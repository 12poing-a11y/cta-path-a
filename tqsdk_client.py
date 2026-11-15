# -*- coding: utf-8 -*-
"""TianQin TqSdk client — futures bars + option chain (OI + IV + Bid/Ask).

Auth from TQ_USER/TQ_PASS env, or repo-local .env.tqsdk (gitignored).
Uses 快期账户 via TqAuth (行情); no futures-broker login required for market data.

Capability note vs Gamma Wall:
- Quote exposes open_interest (OI) natively.
- Best bid/ask via bid_price1/ask_price1 (F1 research snapshots).
- Implied vol is *computed* via tqsdk.ta.OPTION_IMPV (BS), not exchange settlement IV.
  Prefer exchange IV (AkShare CZCE) when both exist; TqSdk fills gaps / non-CZCE.
Missing credentials soft-fail (empty results) so CI/daily jobs never break.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ_SH = ZoneInfo("Asia/Shanghai")

# Path-A product letter → TqSdk exchange prefix
EXCHANGE_OF: dict[str, str] = {}
for _p in (
    "CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "HC", "SS", "BU", "RU", "SP", "AO", "BR",
):
    EXCHANGE_OF[_p] = "SHFE"
for _p in ("SC", "NR", "LU", "BC"):
    EXCHANGE_OF[_p] = "INE"
for _p in (
    "A", "B", "M", "Y", "P", "C", "CS", "JD", "L", "V", "PP", "J", "JM", "I", "EG", "EB", "PG", "LH",
):
    EXCHANGE_OF[_p] = "DCE"
for _p in (
    "CF", "SR", "MA", "TA", "SA", "RM", "OI", "FG", "PF", "SH", "UR", "AP", "CJ", "PK", "PX", "SM", "SF", "ZC",
):
    EXCHANGE_OF[_p] = "CZCE"
for _p in ("IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"):
    EXCHANGE_OF[_p] = "CFFEX"


def load_credentials(*, root: Path | None = None) -> tuple[str, str] | None:
    """Return (user, password) or None if unset."""
    user = (os.environ.get("TQ_USER") or os.environ.get("TQSDK_USER") or "").strip()
    password = (os.environ.get("TQ_PASS") or os.environ.get("TQSDK_PASS") or "").strip()
    if user and password:
        return user, password
    base = Path(root or ROOT)
    for name in (".env.tqsdk", ".env"):
        path = base / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        got: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            key = k.strip().upper()
            val = v.strip().strip('"').strip("'")
            if key in {"TQ_USER", "TQSDK_USER", "TQ_PASS", "TQSDK_PASS"} and val:
                got[key] = val
        u = got.get("TQ_USER") or got.get("TQSDK_USER") or ""
        p = got.get("TQ_PASS") or got.get("TQSDK_PASS") or ""
        if u and p:
            return u, p
    return None


def _split_contract(contract: str) -> tuple[str, str]:
    """CF2701 / CF701 → (CF, 2701-or-701 digits)."""
    import re

    m = re.fullmatch(r"([A-Za-z]+)(\d{3,4})", str(contract or "").strip())
    if not m:
        raise ValueError(f"合约须为品种+年月，例如 CF2701 / CF701，收到: {contract!r}")
    return m.group(1).upper(), m.group(2)


def to_tq_symbol(contract: str) -> str:
    """Path-A delivery month → TqSdk symbol, e.g. CF2701 → CZCE.CF701, RB2510 → SHFE.rb2510."""
    product, yymm = _split_contract(contract)
    exch = EXCHANGE_OF.get(product)
    if not exch:
        raise ValueError(f"未知品种交易所映射: {product}")
    if exch == "CZCE":
        # Zhengzhou: one-digit year + MM (CF2701 → CF701)
        if len(yymm) == 4:
            yymm = f"{int(yymm[:2]) % 10}{yymm[2:]}"
        return f"CZCE.{product}{yymm}"
    if exch == "CFFEX":
        return f"CFFEX.{product}{yymm}"
    # SHFE / INE / DCE: lowercase product + YYYYMM-style (usually 4-digit YYMM)
    if len(yymm) == 3:
        # Rare; pad year decade if caller passed 3-digit — prefer 4-digit upstream
        yymm = f"2{yymm}" if int(yymm[0]) >= 5 else f"1{yymm}"
    return f"{exch}.{product.lower()}{yymm}"


def to_tq_main(code: str) -> str:
    """Continuous/main: CF → KQ.m@CZCE.CF."""
    product = str(code or "").strip().upper()
    # Strip accidental month digits
    import re

    m = re.match(r"^([A-Z]+)", product)
    product = m.group(1) if m else product
    exch = EXCHANGE_OF.get(product)
    if not exch:
        raise ValueError(f"未知品种: {code}")
    return f"KQ.m@{exch}.{product if exch == 'CZCE' else product.lower()}"


@contextmanager
def open_api(*, root: Path | None = None) -> Iterator[Any]:
    """Yield a connected TqApi or raise RuntimeError if credentials missing."""
    creds = load_credentials(root=root)
    if not creds:
        raise RuntimeError(
            "未配置天勤账号。请设置 TQ_USER/TQ_PASS，或写入 .env.tqsdk（已 gitignore）。"
        )
    from tqsdk import TqApi, TqAuth

    api = TqApi(auth=TqAuth(creds[0], creds[1]))
    try:
        yield api
    finally:
        try:
            api.close()
        except Exception:
            pass


def _iso_from_ns(ns: Any) -> str | None:
    try:
        # TqSdk datetime is ns since epoch (Beijing wall for daily bars)
        sec = int(ns) / 1e9
        dt = datetime.fromtimestamp(sec, tz=TZ_SH)
        return dt.date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def klines_to_bars(klines) -> list[dict]:
    """Convert get_kline_serial DataFrame → Path-A bar dicts."""
    out: list[dict] = []
    if klines is None or getattr(klines, "empty", True):
        return out
    for _, row in klines.iterrows():
        d = _iso_from_ns(row.get("datetime"))
        if not d:
            continue
        try:
            o = float(row["open"])
            h = float(row["high"])
            low = float(row["low"])
            c = float(row["close"])
        except (TypeError, ValueError, KeyError):
            continue
        if c <= 0 or low <= 0 or h < low:
            continue
        bar: dict[str, Any] = {
            "date": d,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "volume": float(row.get("volume") or 0),
        }
        oi = row.get("close_oi")
        if oi is None or (isinstance(oi, float) and oi != oi):
            oi = row.get("open_oi")
        try:
            if oi is not None and float(oi) == float(oi):
                bar["oi"] = float(oi)
        except (TypeError, ValueError):
            pass
        out.append(bar)
    out.sort(key=lambda b: b["date"])
    return out


def fetch_daily_bars(
    contract: str,
    *,
    length: int = 300,
    main: bool = False,
    root: Path | None = None,
) -> tuple[list[dict], str]:
    """Pull daily OHLC(+OI). Returns (bars, source_tag). Soft-empty without creds."""
    if not load_credentials(root=root):
        return [], "tqsdk:no-auth"
    try:
        symbol = to_tq_main(contract) if main else to_tq_symbol(contract)
    except ValueError as e:
        return [], f"tqsdk:bad-symbol:{e}"
    try:
        with open_api(root=root) as api:
            kl = api.get_kline_serial(symbol, 86400, data_length=min(max(int(length), 2), 8000))
            # One wait so serial is populated
            api.wait_update(deadline=datetime.now(tz=TZ_SH).timestamp() + 8)
            bars = klines_to_bars(kl)
            return bars, f"tqsdk:{symbol}"
    except Exception as e:  # noqa: BLE001 — soft-fail for desk/CI
        return [], f"tqsdk:error:{type(e).__name__}:{e}"


def _finite_px(value: Any) -> float | None:
    try:
        if value is None:
            return None
        x = float(value)
        if x != x or x <= 0:  # NaN or non-positive
            return None
        return x
    except (TypeError, ValueError):
        return None


def quote_bid_ask(oq: Any) -> tuple[float | None, float | None]:
    """Extract best bid/ask from a Tq quote-like object.

    Tries common TqSdk attribute names; returns (None, None) when absent.
    """
    bid = None
    ask = None
    for name in ("bid_price1", "bid_price", "bid"):
        bid = _finite_px(getattr(oq, name, None))
        if bid is not None:
            break
    for name in ("ask_price1", "ask_price", "ask"):
        ask = _finite_px(getattr(oq, name, None))
        if ask is not None:
            break
    # Some feeds expose parallel arrays
    if bid is None:
        arr = getattr(oq, "bid_price", None)
        if isinstance(arr, (list, tuple)) and arr:
            bid = _finite_px(arr[0])
    if ask is None:
        arr = getattr(oq, "ask_price", None)
        if isinstance(arr, (list, tuple)) and arr:
            ask = _finite_px(arr[0])
    return bid, ask


def fetch_option_chain_snapshot(
    underlying_contract: str,
    *,
    root: Path | None = None,
    rate: float = 0.025,
    max_options: int = 120,
    compute_iv: bool = True,
    overall_deadline_s: float = 90.0,
) -> dict[str, Any]:
    """Live option chain for a futures delivery month: OI + Bid/Ask (+ optional IV).

    ``compute_iv=False`` skips per-leg kline/OPTION_IMPV (fast path for daily Bid/Ask
    accumulation). ``overall_deadline_s`` caps wall time; returns partial rows + note.

    Soft-empty without auth.
    """
    empty = {
        "underlying": underlying_contract,
        "asof": None,
        "rows": [],
        "source": "tqsdk",
        "notes": [],
        "bid_ask_coverage": 0.0,
        "n_with_bid_ask": 0,
    }
    if not load_credentials(root=root):
        empty["notes"].append("no-auth")
        return empty
    try:
        und_sym = to_tq_symbol(underlying_contract)
    except ValueError as e:
        empty["notes"].append(str(e))
        return empty

    OPTION_IMPV = None
    if compute_iv:
        try:
            from tqsdk.ta import OPTION_IMPV as _OPTION_IMPV

            OPTION_IMPV = _OPTION_IMPV
        except ImportError:
            empty["notes"].append("OPTION_IMPV unavailable")
            compute_iv = False

    notes: list[str] = []
    rows: list[dict] = []
    asof: str | None = None
    t0 = datetime.now(tz=TZ_SH).timestamp()
    deadline_abs = t0 + max(5.0, float(overall_deadline_s))

    def _time_left() -> float:
        return deadline_abs - datetime.now(tz=TZ_SH).timestamp()

    try:
        with open_api(root=root) as api:
            und_q = api.get_quote(und_sym)
            wait0 = min(8.0, max(1.0, _time_left()))
            api.wait_update(deadline=datetime.now(tz=TZ_SH).timestamp() + wait0)
            if _time_left() <= 0:
                empty["notes"].append("deadline_before_query_options")
                return empty
            try:
                options = list(api.query_options(underlying_symbol=und_sym, expired=False) or [])
            except Exception as e:  # noqa: BLE001
                empty["notes"].append(f"query_options:{type(e).__name__}:{e}")
                return empty
            if not options:
                empty["notes"].append("no-options")
                return empty
            if len(options) > max_options:
                notes.append(f"truncated_options:{len(options)}->{max_options}")
                options = options[:max_options]

            und_last = float(getattr(und_q, "last_price", 0) or getattr(und_q, "pre_close", 0) or 0)

            # Fast path: subscribe quotes once, single wait, then read Bid/Ask (no IV).
            if not compute_iv:
                try:
                    quote_map = api.get_quote(*options) if len(options) > 1 else {options[0]: api.get_quote(options[0])}
                    # get_quote(*syms) may return a list/tuple of quotes aligned with symbols
                    if isinstance(quote_map, (list, tuple)):
                        q_by = {sym: quote_map[i] for i, sym in enumerate(options) if i < len(quote_map)}
                    elif hasattr(quote_map, "items") and not hasattr(quote_map, "strike_price"):
                        q_by = dict(quote_map)
                    else:
                        # single quote object
                        q_by = {options[0]: quote_map}
                    wait_b = min(12.0, max(1.0, _time_left()))
                    api.wait_update(deadline=datetime.now(tz=TZ_SH).timestamp() + wait_b)
                except Exception as e:  # noqa: BLE001
                    notes.append(f"batch_quote:{type(e).__name__}:{e}")
                    q_by = {}
                    for sym in options:
                        if _time_left() <= 0:
                            notes.append("deadline_partial")
                            break
                        try:
                            q_by[sym] = api.get_quote(sym)
                        except Exception:
                            continue
                    if q_by and _time_left() > 0:
                        api.wait_update(
                            deadline=datetime.now(tz=TZ_SH).timestamp() + min(8.0, _time_left())
                        )

                for opt_sym in options:
                    if _time_left() <= 0:
                        notes.append("deadline_partial")
                        break
                    oq = q_by.get(opt_sym)
                    if oq is None:
                        try:
                            oq = api.get_quote(opt_sym)
                        except Exception as e:  # noqa: BLE001
                            notes.append(f"opt-skip:{opt_sym}:{type(e).__name__}")
                            continue
                    try:
                        oi = getattr(oq, "open_interest", None)
                        try:
                            oi_f = float(oi) if oi is not None else None
                        except (TypeError, ValueError):
                            oi_f = None
                        strike = getattr(oq, "strike_price", None)
                        opt_class = str(getattr(oq, "option_class", "") or "").upper()
                        side = "C" if opt_class.startswith("C") else ("P" if opt_class.startswith("P") else "")
                        expire = getattr(oq, "expire_datetime", None) or getattr(
                            oq, "last_exercise_datetime", None
                        )
                        exp_s = None
                        if expire:
                            exp_s = (
                                _iso_from_ns(int(expire) * 1_000_000_000)
                                if int(expire) < 1e12
                                else _iso_from_ns(expire)
                            )
                        last = _finite_px(getattr(oq, "last_price", None))
                        bid, ask = quote_bid_ask(oq)
                        rows.append(
                            {
                                "合约代码": opt_sym.split(".", 1)[-1],
                                "tq_symbol": opt_sym,
                                "期权类型": side,
                                "行权价": float(strike) if strike is not None else None,
                                "持仓量": oi_f,
                                "空盘量": oi_f,
                                "隐含波动率": None,
                                "最新价": last,
                                "今收盘": last,
                                "今结算": last,
                                "买价": bid,
                                "卖价": ask,
                                "bid": bid,
                                "ask": ask,
                                "到期日": exp_s,
                                "iv_source": None,
                                "quote_source": "tqsdk_live_fast",
                            }
                        )
                    except Exception as e:  # noqa: BLE001
                        notes.append(f"opt-skip:{opt_sym}:{type(e).__name__}")
                        continue
            else:
                for opt_sym in options:
                    if _time_left() <= 0:
                        notes.append("deadline_partial")
                        break
                    try:
                        oq = api.get_quote(opt_sym)
                        api.wait_update(
                            deadline=datetime.now(tz=TZ_SH).timestamp()
                            + min(3.0, max(0.5, _time_left()))
                        )
                        oi = getattr(oq, "open_interest", None)
                        try:
                            oi_f = float(oi) if oi is not None else None
                        except (TypeError, ValueError):
                            oi_f = None
                        strike = getattr(oq, "strike_price", None)
                        opt_class = str(getattr(oq, "option_class", "") or "").upper()
                        side = "C" if opt_class.startswith("C") else ("P" if opt_class.startswith("P") else "")
                        iv = None
                        try:
                            if OPTION_IMPV is not None and _time_left() > 2:
                                kl = api.get_kline_serial([opt_sym, und_sym], 86400, data_length=5)
                                api.wait_update(
                                    deadline=datetime.now(tz=TZ_SH).timestamp()
                                    + min(3.0, max(0.5, _time_left()))
                                )
                                impv = OPTION_IMPV(kl, oq, rate)
                                raw = float(impv["impv"].iloc[-1])
                                if raw == raw and raw > 0:
                                    iv = raw
                        except Exception:
                            iv = None
                        expire = getattr(oq, "expire_datetime", None) or getattr(
                            oq, "last_exercise_datetime", None
                        )
                        exp_s = None
                        if expire:
                            exp_s = (
                                _iso_from_ns(int(expire) * 1_000_000_000)
                                if int(expire) < 1e12
                                else _iso_from_ns(expire)
                            )
                        last = _finite_px(getattr(oq, "last_price", None))
                        bid, ask = quote_bid_ask(oq)
                        rows.append(
                            {
                                "合约代码": opt_sym.split(".", 1)[-1],
                                "tq_symbol": opt_sym,
                                "期权类型": side,
                                "行权价": float(strike) if strike is not None else None,
                                "持仓量": oi_f,
                                "空盘量": oi_f,
                                "隐含波动率": (iv * 100.0) if iv is not None else None,
                                "最新价": last,
                                "今收盘": last,
                                "今结算": last,
                                "买价": bid,
                                "卖价": ask,
                                "bid": bid,
                                "ask": ask,
                                "到期日": exp_s,
                                "iv_source": "tqsdk.OPTION_IMPV" if iv is not None else None,
                                "quote_source": "tqsdk_live",
                            }
                        )
                    except Exception as e:  # noqa: BLE001
                        notes.append(f"opt-skip:{opt_sym}:{type(e).__name__}")
                        continue

            asof = date.today().isoformat()
            try:
                dt_ns = getattr(und_q, "datetime", None)
                if dt_ns:
                    asof = _iso_from_ns(dt_ns) or asof
            except Exception:
                pass

            n_ba = sum(
                1 for r in rows if r.get("bid") is not None and r.get("ask") is not None
            )
            if n_ba == 0:
                notes.append("no_bid_ask_on_quotes")
            return {
                "underlying": underlying_contract,
                "underlying_symbol": und_sym,
                "underlying_last": und_last,
                "asof": asof,
                "rows": rows,
                "source": "tqsdk",
                "notes": notes,
                "bid_ask_coverage": round(n_ba / len(rows), 4) if rows else 0.0,
                "n_with_bid_ask": n_ba,
                "compute_iv": compute_iv,
                "elapsed_s": round(datetime.now(tz=TZ_SH).timestamp() - t0, 2),
            }
    except Exception as e:  # noqa: BLE001
        empty["notes"].append(f"error:{type(e).__name__}:{e}")
        return empty
