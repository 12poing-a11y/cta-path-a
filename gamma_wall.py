# -*- coding: utf-8 -*-
"""Gamma Wall engine: free CZCE option EOD data + exact futures contract.

Call/put signs are display buckets only. OI does not identify dealer positioning.
"""
from __future__ import annotations
import argparse, json, math, re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "gamma_wall"
HISTORY = ROOT / "data" / "gamma_wall"

# V1 observation set: liquid CZCE option underlyings (exact-contract sina + option_hist_czce).
# Multipliers = futures/option contract size (tons per lot) per CZCE specs.
PRODUCTS: dict[str, dict[str, Any]] = {
    "CF": {"option_name": "棉花期权", "multiplier": 5.0, "label": "棉花"},
    "SR": {"option_name": "白糖期权", "multiplier": 10.0, "label": "白糖"},
    "MA": {"option_name": "甲醇期权", "multiplier": 10.0, "label": "甲醇"},
    "TA": {"option_name": "PTA期权", "multiplier": 5.0, "label": "PTA"},
    "SA": {"option_name": "纯碱期权", "multiplier": 20.0, "label": "纯碱"},
    "RM": {"option_name": "菜籽粕期权", "multiplier": 10.0, "label": "菜粕"},
    "OI": {"option_name": "菜籽油期权", "multiplier": 10.0, "label": "菜油"},
    "FG": {"option_name": "玻璃期权", "multiplier": 20.0, "label": "玻璃"},
}
MULTIPLIERS = {k: float(v["multiplier"]) for k, v in PRODUCTS.items()}
CZCE_NAMES = {k: str(v["option_name"]) for k, v in PRODUCTS.items()}
# Near-month observation contracts (YYYYMM last 4 digits); desk may switch later.
OBSERVE_MONTH = "2701"


def supported_contracts(month: str = OBSERVE_MONTH, *, root: Path | None = None) -> list[str]:
    """Futures codes with option chains only, e.g. CF2701.

    Intersects PRODUCTS (option-capable CZCE set) with Path-A universe when
    universe.json is present. Varieties without option data are never listed.
    """
    m = str(month).strip()
    if not re.fullmatch(r"\d{4}", m):
        raise ValueError("month 须为四位年月，例如 2701")
    products = list(PRODUCTS)
    uni_path = (root or ROOT) / "universe.json"
    if uni_path.is_file():
        try:
            uni = json.loads(uni_path.read_text(encoding="utf-8"))
            codes = {
                str(s.get("code") or "").upper()
                for s in (uni.get("symbols") or [])
                if isinstance(s, dict)
            }
            if codes:
                # Keep option-capable products that are in the trading universe first;
                # still allow other PRODUCTS (e.g. RM/OI) after, marked via UI label.
                in_uni = [p for p in products if p in codes]
                extra = [p for p in products if p not in codes]
                products = in_uni + extra
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return [f"{p}{m}" for p in products]


def _num(v: Any) -> float | None:
    try:
        if v is None or str(v).strip().lower() in {"", "-", "nan", "none", "null"}: return None
        x = float(str(v).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError): return None


def czce_option_month(futures_contract: str) -> str:
    """CF2701 -> CF701; CZCE option codes use one-digit year + two-digit month."""
    m = re.fullmatch(r"([A-Za-z]+)(\d{4})", futures_contract.strip())
    if not m: raise ValueError("期货合约必须为品种+四位年月，例如 CF2701")
    product, yymm = m.group(1).upper(), m.group(2)
    return f"{product}{int(yymm[:2]) % 10}{yymm[2:]}"


def black76_gamma(futures: float, strike: float, years: float, rate: float, iv: float) -> float:
    if min(futures, strike, years, iv) <= 0: raise ValueError("F、K、T、IV 必须大于 0")
    vol_t = iv * math.sqrt(years)
    d1 = (math.log(futures / strike) + 0.5 * iv * iv * years) / vol_t
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return math.exp(-rate * years) * pdf / (futures * vol_t)


def _contract_side(code: str, product_month: str):
    text = str(code or "").upper().replace("-", "").replace(" ", "")
    m = re.fullmatch(re.escape(product_month) + r"([CP])(\d+(?:\.\d+)?)", text)
    return (m.group(1), float(m.group(2))) if m else None


def calculate_gamma_rows(option_rows, *, product_month, futures_price, expiry, asof, multiplier, rate=0.02):
    """Call side positive / put side negative is a visualization convention only."""
    days = (date.fromisoformat(expiry) - date.fromisoformat(asof[:10])).days
    if days <= 0: raise ValueError("到期日必须晚于快照日期")
    t, agg = days / 365.0, {}
    for row in option_rows:
        parsed = _contract_side(str(row.get("合约代码") or row.get("合约") or ""), product_month)
        if not parsed: continue
        side, strike = parsed
        oi = _num(row.get("空盘量"))
        if oi is None: oi = _num(row.get("持仓量"))
        iv = _num(row.get("隐含波动率"))
        if iv is not None and iv > 3: iv /= 100.0
        if oi is None or oi <= 0 or iv is None or not (0.005 <= iv <= 5): continue
        gamma = black76_gamma(futures_price, strike, t, rate, iv)
        gex = gamma * oi * multiplier * futures_price * futures_price * 0.01
        b = agg.setdefault(strike, {"call_gex":0.0,"put_gex":0.0,"call_oi":0.0,"put_oi":0.0})
        key = "call" if side == "C" else "put"
        b[f"{key}_gex"] += gex
        b[f"{key}_oi"] += oi
    return [{"strike":k,"call_gex":v["call_gex"],"put_gex":-v["put_gex"],
             "gross_gex":v["call_gex"]+v["put_gex"],"call_oi":v["call_oi"],"put_oi":v["put_oi"]}
            for k,v in sorted(agg.items())]


def assess_data_quality(option_rows, matching_rows, gamma_rows, futures_date, asof):
    """Fail closed on stale underlying, thin strike coverage or weak IV/OI coverage."""
    total = len(matching_rows)
    valid = len(gamma_rows)
    valid_contracts = 0
    for row in matching_rows:
        oi = _num(row.get("空盘量"))
        if oi is None: oi = _num(row.get("持仓量"))
        iv = _num(row.get("隐含波动率"))
        if iv is not None and iv > 3: iv /= 100.0
        if oi is not None and oi > 0 and iv is not None and 0.005 <= iv <= 5:
            valid_contracts += 1
    coverage = valid_contracts / total if total else 0.0
    issues = []
    if futures_date != asof: issues.append(f"期货行情日期不一致：{futures_date or '缺失'} != {asof}")
    if total == 0: issues.append("期权表中没有匹配的目标系列")
    if valid < 5: issues.append(f"有效行权价不足5档：{valid}")
    if total and coverage < 0.60: issues.append(f"有效行权价覆盖率低于60%：{coverage:.1%}")
    status = "PASS" if not issues else "REJECT"
    return {"status":status,"issues":issues,"option_rows_total":len(option_rows),
        "matching_contracts":total,"valid_strikes":valid,"valid_contracts":valid_contracts,"valid_contract_coverage":round(coverage,4),
        "underlying_date":futures_date,"option_date":asof,"dealer_sign_known":False}


def resolve_snapshot_asof(trade_date: str | None = None, *, now=None) -> str:
    """Snapshot trade date: explicit override, else latest closed weekday session.

    Before 15:00 Asia/Shanghai the calendar day is not used — that would request
    a bar that does not exist yet. Still never relabel another day's settle as today.
    """
    if trade_date:
        asof = str(trade_date).strip()[:10]
        date.fromisoformat(asof)
        return asof
    from market_data import latest_expected_session_date

    return latest_expected_session_date(now).isoformat()


def _fetch_czce_day(product, trade_date):
    import akshare as ak
    return ak.option_hist_czce(symbol=CZCE_NAMES[product], trade_date=trade_date.replace("-", ""))


def _normalize_fut_row(row: dict) -> dict:
    """Unify Sina/AkShare and Fuyao exact-contract rows for snapshot pricing."""
    d = str(row.get("date") or "")[:10]
    out = dict(row)
    out["date"] = d
    if out.get("hold") is None and out.get("open_interest") is not None:
        out["hold"] = out.get("open_interest")
    if out.get("settle") is None and out.get("close") is not None:
        out["settle"] = out.get("close")
    return out


def _load_exact_contract_daily(
    contract: str, *, root: Path, refresh: bool = True, need_date: str | None = None
) -> list[dict]:
    """Exact-contract daily: Sina → Fuyao → TqSdk gap-fill — never CF0 / continuous."""
    raw = root / ".cache" / "gamma_wall" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    fp = raw / f"{contract}_daily.json"
    fut_rows: list[dict] = []
    if fp.exists():
        try:
            cached = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                fut_rows = cached
            elif isinstance(cached, dict) and isinstance(cached.get("rows"), list):
                fut_rows = cached["rows"]
        except (OSError, json.JSONDecodeError):
            fut_rows = []
    if not refresh and fut_rows and (
        need_date is None or any(str(r.get("date", ""))[:10] == need_date for r in fut_rows)
    ):
        return [_normalize_fut_row(r) for r in fut_rows if str(r.get("date") or "")]

    from market_data import load_exact_contract_bars

    bars, meta = load_exact_contract_bars(
        contract, need_date=need_date, root=root, use_cache=False
    )
    by_date = {str(r.get("date", ""))[:10]: _normalize_fut_row(r) for r in fut_rows if r.get("date")}
    for b in bars:
        by_date[str(b.get("date", ""))[:10]] = _normalize_fut_row(b)
    fut_rows = [by_date[k] for k in sorted(by_date) if k]
    fp.write_text(
        json.dumps({"rows": fut_rows, "meta": meta}, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    return fut_rows


def _row_on_date(rows: list[dict], asof: str) -> dict | None:
    return next((r for r in reversed(rows) if str(r.get("date", ""))[:10] == asof), None)


def fetch_snapshot(contract, *, expiry, trade_date=None, rate=0.02, root=None):
    """Fetch one CZCE option daily table + exact futures contract daily history."""
    root = root or ROOT
    contract = contract.upper()
    m = re.fullmatch(r"([A-Z]+)(\d{4})", contract)
    if not m or m.group(1) not in PRODUCTS:
        allow = "、".join(supported_contracts())
        raise ValueError(f"当前仅支持郑商所观察品种：{allow}")
    product = m.group(1)
    asof = resolve_snapshot_asof(trade_date)
    if date.fromisoformat(expiry) <= date.fromisoformat(asof):
        raise ValueError("到期日必须晚于快照日期；请核实郑商所规则后再计算")
    month = czce_option_month(contract)

    fut_rows = _load_exact_contract_daily(
        contract, root=root, refresh=True, need_date=asof
    )
    frow = _row_on_date(fut_rows, asof)
    if frow is None:
        last = str(fut_rows[-1].get("date", ""))[:10] if fut_rows else "无"
        raise RuntimeError(
            f"新浪/扶摇/天勤均未返回 {contract} 在 {asof} 的单合约日线（最新有 {last}）；"
            "日盘未收/未结算前请改快照日为已收盘交易日；禁止用主连或前一日价格替代。"
        )
    futures_date = str(frow.get("date", ""))[:10]
    futures_price = _num(frow.get("settle")) or _num(frow.get("close"))
    if futures_price is None or futures_price <= 0:
        raise RuntimeError("目标期货结算价/收盘价缺失或非正数")

    raw = root / ".cache" / "gamma_wall" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    op = raw / f"{product}_{asof}.json"
    if op.exists():
        option_rows = json.loads(op.read_text(encoding="utf-8"))
        if not option_rows:
            op.unlink(missing_ok=True)
            option_rows = []
    else:
        option_rows = []
    if not option_rows:
        frame = _fetch_czce_day(product, asof)
        option_rows = frame.to_dict("records")
        if not option_rows:
            raise RuntimeError(f"郑商所期权日行情在 {asof} 无返回行；勿用其他日期期权表顶替")
        op.write_text(json.dumps(option_rows, ensure_ascii=False, default=str), encoding="utf-8")

    matching = [
        r for r in option_rows if _contract_side(str(r.get("合约代码") or r.get("合约") or ""), month)
    ]
    rows = calculate_gamma_rows(
        matching,
        product_month=month,
        futures_price=futures_price,
        expiry=expiry,
        asof=asof,
        multiplier=MULTIPLIERS[product],
        rate=rate,
    )
    quality = assess_data_quality(option_rows, matching, rows, futures_date, asof)
    if quality["status"] != "PASS":
        raise RuntimeError("数据质量校验未通过，未保存快照：" + "；".join(quality["issues"]))
    structure = build_gamma_structure(rows, futures_price=futures_price)
    call_wall = structure["call_wall"]
    put_wall = structure["put_wall"]
    snap = {
        "schema_version": 3,
        "source": "AKShare CZCE option + Sina/Fuyao exact futures contract",
        "asof": asof,
        "contract": contract,
        "option_month": month,
        "expiry": expiry,
        "futures_price": futures_price,
        "rate": rate,
        "multiplier": MULTIPLIERS[product],
        "rows": rows,
        "call_wall": call_wall["strike"],
        "put_wall": put_wall["strike"],
        "call_wall_gex": call_wall["call_gex"],
        "put_wall_gex": abs(put_wall["put_gex"]),
        "gamma_flip": structure["gamma_flip"],
        "net_gex": structure["net_gex"],
        "cum_net_gex": structure["cum_net_gex"],
        "gex_model": structure["gex_model"],
        "data_quality": quality,
        "disclaimer": (
            "Call/Put 两侧柱体是分类展示，不代表 dealer 净 Gamma 正负；"
            "OI 无法识别持仓方方向。Gamma Flip / Net GEX 为情景累计（Call+−Put），须标注假设。"
        ),
    }
    outdir = root / "data" / "gamma_wall" / contract
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / f"{asof}.json"
    target.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def build_gamma_structure(rows: list[dict], *, futures_price: float | None = None) -> dict[str, Any]:
    """Derive walls, scenario net GEX and first zero-cross Gamma Flip along strikes.

    Convention: call_gex >= 0, put_gex <= 0 (display buckets). Scenario net at a
    strike is call_gex + put_gex. Flip is the first strike where cumulative net
    crosses from negative to non-negative (low→high). Not a dealer identity.
    """
    if not rows:
        raise ValueError("无有效行权价，无法构建 Gamma 结构")
    ordered = sorted(rows, key=lambda r: float(r["strike"]))
    call_wall = max(ordered, key=lambda r: float(r["call_gex"]))
    put_wall = min(ordered, key=lambda r: float(r["put_gex"]))
    cum = 0.0
    curve: list[dict[str, float]] = []
    flip: float | None = None
    prev = None
    for r in ordered:
        net = float(r["call_gex"]) + float(r["put_gex"])
        prev_cum = cum
        cum += net
        curve.append(
            {
                "strike": float(r["strike"]),
                "net_gex": net,
                "cum_net_gex": cum,
                "call_gex": float(r["call_gex"]),
                "put_gex": float(r["put_gex"]),
            }
        )
        if flip is None and prev is not None and prev_cum < 0 <= cum:
            # Linear interpolate between previous and current strike.
            span = cum - prev_cum
            w = (-prev_cum / span) if span else 1.0
            flip = float(prev["strike"]) + w * (float(r["strike"]) - float(prev["strike"]))
        prev = r
    return {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": None if flip is None else round(flip, 2),
        "net_gex": round(cum, 6),
        "cum_net_gex": curve,
        "futures_price": futures_price,
        "gex_model": "scenario_call_positive_put_negative",
    }


def demo_gamma_snapshot(*, contract: str = "CF2701") -> dict[str, Any]:
    """Synthetic layout sample — not live market data."""
    futures = 16000.0
    strikes = list(range(14800, 17201, 200))
    rows = []
    for k in strikes:
        # Peaked call exposure above spot, put exposure below — illustrative only.
        call = max(0.0, 180.0 - abs(k - 16400) * 0.35)
        put = max(0.0, 160.0 - abs(k - 15400) * 0.30)
        rows.append(
            {
                "strike": float(k),
                "call_gex": call,
                "put_gex": -put,
                "gross_gex": call + put,
                "call_oi": call,
                "put_oi": put,
            }
        )
    structure = build_gamma_structure(rows, futures_price=futures)
    return {
        "schema_version": 3,
        "demo": True,
        "source": "synthetic style demo — not market data",
        "asof": "DEMO",
        "contract": contract,
        "option_month": czce_option_month(contract) if contract[-4:].isdigit() else "DEMO",
        "expiry": "DEMO",
        "futures_price": futures,
        "rows": rows,
        "call_wall": structure["call_wall"]["strike"],
        "put_wall": structure["put_wall"]["strike"],
        "call_wall_gex": structure["call_wall"]["call_gex"],
        "put_wall_gex": abs(structure["put_wall"]["put_gex"]),
        "gamma_flip": structure["gamma_flip"],
        "net_gex": structure["net_gex"],
        "cum_net_gex": structure["cum_net_gex"],
        "gex_model": structure["gex_model"],
        "data_quality": {
            "status": "DEMO",
            "valid_strikes": len(rows),
            "valid_contract_coverage": 1.0,
            "issues": ["样式示意，禁止用于交易"],
        },
        "disclaimer": "虚构示意数据。正式版须用真实期权链；OI 不能证明 dealer 方向。",
    }


def load_history(contract, *, root=None):
    folder = (root or ROOT) / "data" / "gamma_wall" / contract.upper()
    rows = []
    if folder.exists():
        for p in sorted(folder.glob("*.json")):
            try:
                item = json.loads(p.read_text(encoding="utf-8"))
                if item.get("data_quality", {}).get("status") == "PASS":
                    rows.append(item)
            except (OSError, json.JSONDecodeError):
                pass
    return rows


def migration_rows(contract, window=20, *, root=None):
    if window not in {5, 10, 20, 30, 60}:
        raise ValueError("window 仅支持 5/10/20/30/60")
    history = load_history(contract, root=root)[-window:]
    if not history:
        return []
    base = history[0]
    out = []
    for s in history:
        structure = None
        if s.get("cum_net_gex") is None and s.get("rows"):
            try:
                structure = build_gamma_structure(s["rows"], futures_price=s.get("futures_price"))
            except ValueError:
                structure = None
        flip = s.get("gamma_flip")
        net = s.get("net_gex")
        if structure:
            flip = structure["gamma_flip"] if flip is None else flip
            net = structure["net_gex"] if net is None else net
        fp = float(s["futures_price"])
        cw, pw = float(s["call_wall"]), float(s["put_wall"])
        out.append(
            {
                "date": s["asof"],
                "futures_price": fp,
                "call_wall": cw,
                "put_wall": pw,
                "gamma_flip": flip,
                "net_gex": net,
                "call_wall_move": cw - float(base["call_wall"]),
                "put_wall_move": pw - float(base["put_wall"]),
                "call_dist_pct": round((cw - fp) / fp * 100, 3) if fp else None,
                "put_dist_pct": round((pw - fp) / fp * 100, 3) if fp else None,
                "call_wall_gex": s.get("call_wall_gex"),
                "put_wall_gex": s.get("put_wall_gex"),
                "observations": len(history),
            }
        )
    return out


def main():
    p=argparse.ArgumentParser(description="Build free-source commodity Gamma Wall snapshot")
    p.add_argument("--contract",default="CF2701")
    p.add_argument("--expiry",required=True,help="经交易所规则核实的期权到期/最后交易日 YYYY-MM-DD")
    p.add_argument("--date",default=None,help="交易日 YYYY-MM-DD，默认今天")
    p.add_argument("--rate",type=float,default=0.02)
    a=p.parse_args()
    result=fetch_snapshot(a.contract,expiry=a.expiry,trade_date=a.date,rate=a.rate)
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))


if __name__=="__main__": main()
