# -*- coding: utf-8 -*-
"""CTA L1 Path-A daily paper update for China commodity futures."""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ifind_call import call, active_slot  # noqa: E402
from position_rules import (  # noqa: E402
    apply_portfolio_caps,
    compound_equity,
    risk_budget_yuan,
)

TZ = ZoneInfo("Asia/Shanghai")
EQUITY_STATE_PATH = ROOT / "equity_state.json"


def _load_universe():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    equity_base = float(cfg.get("equity", 200_000))
    compound = bool(cfg.get("equity_compound", True))
    risk_pct = float(cfg.get("risk_pct", 1.5))
    l1_mult = float(cfg.get("l1_mult", 1.0))
    max_positions = int(cfg.get("max_positions", 3))
    max_gross_pct = float(cfg.get("max_gross_exposure_pct", 50))
    symbols = cfg.get("symbols") or []
    return equity_base, compound, risk_pct, l1_mult, max_positions, max_gross_pct, symbols


def _load_live_equity(equity_base: float) -> tuple[float, dict]:
    """Paper equity from equity_state.json (updated by weekly / prior days)."""
    state = {
        "equity_base": equity_base,
        "equity": equity_base,
        "peak": equity_base,
        "asof": None,
        "source": "universe",
    }
    if EQUITY_STATE_PATH.exists():
        try:
            raw = json.loads(EQUITY_STATE_PATH.read_text(encoding="utf-8"))
            state.update(raw if isinstance(raw, dict) else {})
        except Exception:
            pass
    live = float(state.get("equity") or equity_base)
    if live <= 0:
        live = equity_base
    state["equity"] = live
    state["equity_base"] = equity_base
    return live, state


EQUITY_BASE, EQUITY_COMPOUND, RISK_PCT, L1_MULT, MAX_POSITIONS, MAX_GROSS_PCT, UNIVERSE = (
    _load_universe()
)
LIVE_EQUITY, _EQUITY_STATE = _load_live_equity(EQUITY_BASE)
EQUITY = compound_equity(LIVE_EQUITY, EQUITY_BASE, EQUITY_COMPOUND)
L1_RISK = risk_budget_yuan(EQUITY, RISK_PCT, L1_MULT)


def _answer_text(res: dict) -> str:
    if not res.get("ok"):
        raise RuntimeError(json.dumps(res, ensure_ascii=False)[:500])
    text = res["data"]["result"]["content"][0]["text"]
    try:
        payload = json.loads(text)
        return payload.get("data", {}).get("answer", text)
    except Exception:
        return text


def _parse_md_table(ans: str):
    rows = []
    for line in ans.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def _to_float(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "—", "NA", "N/A"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _looks_like_yyyymmdd(n: float | None) -> bool:
    """Reject compact trade dates (e.g. 20260916) mistaken for prices/ATR."""
    if n is None:
        return False
    if abs(n - round(n)) > 1e-9:
        return False
    v = int(round(n))
    if not (20000101 <= v <= 20991231):
        return False
    mm, dd = (v // 100) % 100, v % 100
    return 1 <= mm <= 12 and 1 <= dd <= 31


def _price_num(x) -> float | None:
    n = _to_float(x)
    if n is None or _looks_like_yyyymmdd(n):
        return None
    # futures settlement prices are almost never this huge as a single tick
    if abs(n) >= 5_000_000:
        return None
    return n


def _fetch_snapshot(code: str, name: str) -> dict:
    q = (
        f"{name}主力合约最新交易日收盘价、近20日涨跌幅%、近60日涨跌幅%、"
        f"以及最近30个交易日的日收盘价与最高价最低价列表（用于ATR）"
    )
    ans = _answer_text(call("future", "future_quotes", {"query": q}))
    rows = _parse_md_table(ans)

    close = r20 = r60 = None
    # Prefer a summary row with percent returns
    for cells in rows:
        joined = " ".join(cells)
        if code.upper() in joined.upper() or name in joined or "ZL." in joined:
            nums = [_price_num(c) for c in cells]
            nums = [n for n in nums if n is not None]
            if len(nums) >= 1:
                # close: price-like, not a compact YYYYMMDD, typically > ~50 for most contracts
                for n in nums:
                    if abs(n) > 50:
                        close = n
                        break
                pcts = [n for n in nums if abs(n) < 80]
                if len(pcts) >= 2:
                    r20, r60 = pcts[0], pcts[1]
                elif len(pcts) == 1:
                    r20 = pcts[0]

    # Parse OHLC history from markdown / numbered lines
    hist = []
    for line in ans.splitlines():
        m = re.search(
            r"(20\d{2}[-/]?\d{1,2}[-/]?\d{1,2}).{0,40}?(\d+\.?\d*).{0,20}?(\d+\.?\d*).{0,20}?(\d+\.?\d*)",
            line,
        )
        if not m:
            continue
        d = m.group(1)
        a, b, c = _price_num(m.group(2)), _price_num(m.group(3)), _price_num(m.group(4))
        vals = [v for v in (a, b, c) if v is not None]
        if len(vals) >= 3:
            high, low, cl = vals[0], vals[1], vals[2]
            if high < low:
                high, low = low, high
            hist.append({"date": d, "high": high, "low": low, "close": cl})
        elif len(vals) == 1:
            hist.append({"date": d, "high": vals[0], "low": vals[0], "close": vals[0]})

    hist = sorted(hist, key=lambda x: x["date"])[-30:]
    if hist and (close is None or _looks_like_yyyymmdd(close)):
        close = hist[-1]["close"]

    atr = None
    if len(hist) >= 15:
        trs = []
        for i in range(1, len(hist)):
            h, l, pc = hist[i]["high"], hist[i]["low"], hist[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[-14:]) / 14.0
        if atr is not None and _looks_like_yyyymmdd(atr):
            atr = None

    # fallback dedicated ATR query
    if atr is None:
        ans2 = _answer_text(
            call("future", "future_quotes", {"query": f"{name}主力近20日真实波幅ATR14"})
        )
        for m in re.finditer(r"(\d+\.?\d*)", ans2):
            cand = _price_num(m.group(1))
            if cand is not None and cand > 0:
                atr = cand
                break

    if r20 is None or r60 is None:
        ans3 = _answer_text(
            call(
                "future",
                "future_quotes",
                {"query": f"{name}主力近20日涨跌幅和近60日涨跌幅百分比"},
            )
        )
        pcts = re.findall(r"(-?\d+\.?\d*)\s*%?", ans3)
        floats = [_to_float(p) for p in pcts]
        floats = [f for f in floats if f is not None and abs(f) < 100 and not _looks_like_yyyymmdd(f)]
        if len(floats) >= 2:
            r20 = r20 if r20 is not None else floats[0]
            r60 = r60 if r60 is not None else floats[1]

    if close is not None and _looks_like_yyyymmdd(close):
        close = None
    return {"close": close, "r20": r20, "r60": r60, "atr": atr, "raw_preview": ans[:240]}


def _signal(u: dict, snap: dict, *, risk_budget: float) -> dict:
    close, atr, r20, r60 = snap.get("close"), snap.get("atr"), snap.get("r20"), snap.get("r60")
    risk_per_lot = (atr * u["mult"]) if atr is not None else None
    align = "冲突/不足"
    direction = "空仓"
    if r20 is not None and r60 is not None and r20 != 0 and r60 != 0:
        if (r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0):
            align = "同向"
            direction = "多" if r20 > 0 else "空"

    lots = 0
    if align == "同向" and risk_per_lot and risk_per_lot > 0:
        lots = int(math.floor(risk_budget / risk_per_lot))

    if align != "同向":
        action = "空仓（20日与60日不同向）"
    elif lots <= 0:
        action = f"有{direction}向，1.5%仍不足1手（每手约{risk_per_lot}）"
    else:
        action = f"候选：{direction}{lots}手（待Top{MAX_POSITIONS}/敞口≤{MAX_GROSS_PCT}%筛选）"

    today = datetime.now(TZ).strftime("%Y%m%d")
    return {
        "code": u["code"],
        "name": u["name"],
        "ticker": u["ticker"],
        "bucket": u["bucket"],
        "mult": u["mult"],
        "date": today,
        "close": close,
        "atr": round(atr, 2) if atr is not None else None,
        "risk_per_lot": round(risk_per_lot, 1) if risk_per_lot is not None else None,
        "r20": r20,
        "r60": r60,
        "align": align,
        "direction": direction if align == "同向" else "空仓",
        "lots_raw": lots,
        "lots_l1": lots,
        "lots_full": lots,
        "selected": False,
        "action": action,
    }


def is_weekday_cn() -> bool:
    return datetime.now(TZ).weekday() < 5


def _apply_caps(signals: list[dict], *, sizing_equity: float) -> dict:
    cands = []
    for s in signals:
        if s.get("align") != "同向":
            continue
        lots = int(s.get("lots_raw") or s.get("lots_l1") or 0)
        if lots <= 0 or not s.get("close"):
            continue
        cands.append(
            {
                "code": s["code"],
                "direction": s.get("direction"),
                "lots": lots,
                "close": s.get("close"),
                "mult": s.get("mult"),
                "r20": s.get("r20"),
                "r60": s.get("r60"),
                "atr": s.get("atr"),
            }
        )
    selected, meta = apply_portfolio_caps(
        cands,
        equity=sizing_equity,
        max_positions=MAX_POSITIONS,
        max_gross_exposure_pct=MAX_GROSS_PCT,
    )
    by_code = {c["code"]: c for c in selected}
    for s in signals:
        code = s.get("code")
        if code in by_code:
            lots = int(by_code[code]["lots"])
            s["lots_l1"] = lots
            s["lots_full"] = lots
            s["selected"] = True
            s["action"] = f"路径A记账：记{s.get('direction')}{lots}手（Top{MAX_POSITIONS}·敞口≤{MAX_GROSS_PCT}%·不下单）"
        else:
            raw = int(s.get("lots_raw") or 0)
            if s.get("align") == "同向" and raw > 0:
                s["lots_l1"] = 0
                s["lots_full"] = 0
                s["selected"] = False
                s["action"] = f"有信号但未入选（限{MAX_POSITIONS}品种/总仓≤{MAX_GROSS_PCT}%）"
            else:
                s["selected"] = False
    return meta


def main():
    now = datetime.now(TZ)
    live, state = _load_live_equity(EQUITY_BASE)
    sizing_eq = compound_equity(live, EQUITY_BASE, EQUITY_COMPOUND)
    risk_budget = risk_budget_yuan(sizing_eq, RISK_PCT, L1_MULT)
    print(
        f"[cta] start {now.isoformat()} equity_base={EQUITY_BASE} live={live} "
        f"sizing={sizing_eq} compound={EQUITY_COMPOUND} risk={risk_budget} "
        f"max_pos={MAX_POSITIONS} max_gross={MAX_GROSS_PCT}% ifind={active_slot()}"
    )
    if not is_weekday_cn():
        print("[cta] skip: weekend")
        out = {"asof": now.strftime("%Y%m%d"), "skipped": "weekend"}
        (ROOT / "l1_report_risk15.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0

    signals = []
    for u in UNIVERSE:
        print(f"[cta] fetch {u['code']}...")
        try:
            snap = _fetch_snapshot(u["code"], u["name"])
            sig = _signal(u, snap, risk_budget=risk_budget)
            signals.append(sig)
            print(
                f"  {u['code']} close={sig['close']} r20={sig['r20']} r60={sig['r60']} "
                f"atr={sig['atr']} lots={sig['lots_l1']} {sig['direction']}"
            )
        except Exception as e:
            signals.append(
                {
                    "code": u["code"],
                    "name": u["name"],
                    "error": str(e)[:300],
                    "lots_l1": 0,
                    "lots_raw": 0,
                    "selected": False,
                    "direction": "空仓",
                    "action": f"拉取失败: {e}",
                }
            )
            print(f"  ERR {u['code']}: {e}")

    port_meta = _apply_caps(signals, sizing_equity=sizing_eq)
    port_meta["sizing_equity"] = round(sizing_eq, 2)
    port_meta["equity_compound"] = EQUITY_COMPOUND
    print(
        f"[cta] portfolio selected={port_meta.get('selected')} "
        f"gross={port_meta.get('gross_after')} ({port_meta.get('gross_pct')}%) "
        f"scale={port_meta.get('scale')}"
    )

    report = {
        "asof": now.strftime("%Y%m%d"),
        "updated_at": now.isoformat(),
        "equity_base": EQUITY_BASE,
        "equity": sizing_eq,
        "equity_live": live,
        "equity_compound": EQUITY_COMPOUND,
        "risk_pct": RISK_PCT,
        "l1_mult": L1_MULT,
        "l1_risk_yuan": risk_budget,
        "max_positions": MAX_POSITIONS,
        "max_gross_exposure_pct": MAX_GROSS_PCT,
        "ifind_slot": active_slot(),
        "portfolio": port_meta,
        "equity_state": {
            "asof": state.get("asof"),
            "source": state.get("source"),
            "peak": state.get("peak"),
        },
        "signals": signals,
    }
    path = ROOT / "l1_report_risk15.json"
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(blob, encoding="utf-8")
    (ROOT / "l1_report.json").write_text(blob, encoding="utf-8")
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    (arch / f"l1_report_{report['asof']}.json").write_text(blob, encoding="utf-8")
    print(f"[cta] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
