# -*- coding: utf-8 -*-
"""TianQin TqSdk client — futures bars + option chain (OI + computed IV).

Auth from TQ_USER/TQ_PASS env, or repo-local .env.tqsdk (gitignored).
Uses 快期账户 via TqAuth (行情); no futures-broker login required for market data.

Capability note vs Gamma Wall:
- Quote exposes open_interest (OI) natively.
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


def fetch_option_chain_snapshot(
    underlying_contract: str,
    *,
    root: Path | None = None,
    rate: float = 0.025,
    max_options: int = 120,
) -> dict[str, Any]:
    """Live option chain for a futures delivery month: OI + OPTION_IMPV.

    Returns dict with keys: underlying, asof, rows (list), source, notes.
    Soft-empty without auth.
    """
    empty = {
        "underlying": underlying_contract,
        "asof": None,
        "rows": [],
        "source": "tqsdk",
        "notes": [],
    }
    if not load_credentials(root=root):
        empty["notes"].append("no-auth")
        return empty
    try:
        und_sym = to_tq_symbol(underlying_contract)
    except ValueError as e:
        empty["notes"].append(str(e))
        return empty

    try:
        from tqsdk.ta import OPTION_IMPV
    except ImportError:
        empty["notes"].append("OPTION_IMPV unavailable")
        return empty

    notes: list[str] = []
    rows: list[dict] = []
    asof: str | None = None
    try:
        with open_api(root=root) as api:
            und_q = api.get_quote(und_sym)
            api.wait_update(deadline=datetime.now(tz=TZ_SH).timestamp() + 8)
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
            for opt_sym in options:
                try:
                    oq = api.get_quote(opt_sym)
                    api.wait_update(deadline=datetime.now(tz=TZ_SH).timestamp() + 3)
                    oi = getattr(oq, "open_interest", None)
                    try:
                        oi_f = float(oi) if oi is not None else None
                    except (TypeError, ValueError):
                        oi_f = None
                    strike = getattr(oq, "strike_price", None)
                    opt_class = str(getattr(oq, "option_class", "") or "").upper()
                    # C/CALL → C, P/PUT → P
                    side = "C" if opt_class.startswith("C") else ("P" if opt_class.startswith("P") else "")
                    iv = None
                    try:
                        kl = api.get_kline_serial([opt_sym, und_sym], 86400, data_length=5)
                        api.wait_update(deadline=datetime.now(tz=TZ_SH).timestamp() + 3)
                        impv = OPTION_IMPV(kl, oq, rate)
                        raw = float(impv["impv"].iloc[-1])
                        if raw == raw and raw > 0:
                            iv = raw  # fraction
                    except Exception:
                        iv = None
                    expire = getattr(oq, "expire_datetime", None) or getattr(oq, "last_exercise_datetime", None)
                    exp_s = None
                    if expire:
                        exp_s = _iso_from_ns(int(expire) * 1_000_000_000) if int(expire) < 1e12 else _iso_from_ns(expire)
                    rows.append(
                        {
                            "合约代码": opt_sym.split(".", 1)[-1],
                            "tq_symbol": opt_sym,
                            "期权类型": side,
                            "行权价": float(strike) if strike is not None else None,
                            "持仓量": oi_f,
                            "空盘量": oi_f,
                            "隐含波动率": (iv * 100.0) if iv is not None else None,  # percent, CZCE-style
                            "最新价": float(getattr(oq, "last_price", 0) or 0) or None,
                            "到期日": exp_s,
                            "iv_source": "tqsdk.OPTION_IMPV",
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

            return {
                "underlying": underlying_contract,
                "underlying_symbol": und_sym,
                "underlying_last": und_last,
                "asof": asof,
                "rows": rows,
                "source": "tqsdk",
                "notes": notes,
            }
    except Exception as e:  # noqa: BLE001
        empty["notes"].append(f"error:{type(e).__name__}:{e}")
        return empty
