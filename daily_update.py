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
from ifind_call import call  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")


def _load_universe():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    equity = float(cfg.get("equity", 200_000))
    risk_pct = float(cfg.get("risk_pct", 1.5))
    l1_mult = float(cfg.get("l1_mult", 1.0))
    symbols = cfg.get("symbols") or []
    return equity, risk_pct, l1_mult, symbols


EQUITY, RISK_PCT, L1_MULT, UNIVERSE = _load_universe()
L1_RISK = EQUITY * RISK_PCT / 100.0 * L1_MULT


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
            nums = [_to_float(c) for c in cells]
            nums = [n for n in nums if n is not None]
            if len(nums) >= 1:
                # heuristic: close often largest absolute among price-like, returns small
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
        d, a, b, c = m.group(1), _to_float(m.group(2)), _to_float(m.group(3)), _to_float(m.group(4))
        if a is None:
            continue
        # treat as date, close[, high, low] or date high low close
        vals = [a, b, c]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 3:
            # assume high, low, close if close-like last
            high, low, cl = vals[0], vals[1], vals[2]
            if high < low:
                high, low = low, high
            hist.append({"date": d, "high": high, "low": low, "close": cl})
        elif len(vals) == 1:
            hist.append({"date": d, "high": vals[0], "low": vals[0], "close": vals[0]})

    hist = sorted(hist, key=lambda x: x["date"])[-30:]
    if hist and close is None:
        close = hist[-1]["close"]

    atr = None
    if len(hist) >= 15:
        trs = []
        for i in range(1, len(hist)):
            h, l, pc = hist[i]["high"], hist[i]["low"], hist[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[-14:]) / 14.0

    # fallback dedicated ATR query
    if atr is None:
        ans2 = _answer_text(
            call("future", "future_quotes", {"query": f"{name}主力近20日真实波幅ATR14"})
        )
        m = re.search(r"(\d+\.?\d*)", ans2)
        if m:
            atr = _to_float(m.group(1))

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
        floats = [f for f in floats if f is not None and abs(f) < 100]
        if len(floats) >= 2:
            r20 = r20 if r20 is not None else floats[0]
            r60 = r60 if r60 is not None else floats[1]

    return {"close": close, "r20": r20, "r60": r60, "atr": atr, "raw_preview": ans[:240]}


def _signal(u: dict, snap: dict) -> dict:
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
        lots = int(math.floor(L1_RISK / risk_per_lot))

    if align != "同向":
        action = "空仓（20日与60日不同向）"
    elif lots <= 0:
        action = f"有{direction}向，1.5%仍不足1手（每手约{risk_per_lot}）"
    else:
        action = f"路径A记账：记{direction}{lots}手（不下单）"

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
        "lots_l1": lots,
        "lots_full": lots,
        "action": action,
    }


def is_weekday_cn() -> bool:
    return datetime.now(TZ).weekday() < 5


def main():
    now = datetime.now(TZ)
    print(f"[cta] start {now.isoformat()} risk={L1_RISK}")
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
            sig = _signal(u, snap)
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
                    "direction": "空仓",
                    "action": f"拉取失败: {e}",
                }
            )
            print(f"  ERR {u['code']}: {e}")

    report = {
        "asof": now.strftime("%Y%m%d"),
        "updated_at": now.isoformat(),
        "equity": EQUITY,
        "risk_pct": RISK_PCT,
        "l1_mult": L1_MULT,
        "l1_risk_yuan": L1_RISK,
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
