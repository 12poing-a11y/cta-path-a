# -*- coding: utf-8 -*-
"""A/B validate multi-scale vol bypass on Path-A seats (paper).

Compares seats+carry (baseline) vs same + vol expand entry block.
Writes ``lab/research/oos/vol_bypass_validate_latest.json``.
Decision: adopt into live desk config only if applicability is high.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from historical_backtest import _fetch_pack, _load_cfg, simulate  # noqa: E402
from path_a_filters import carry_bypass_cfg  # noqa: E402
from vol_factor_combo import vol_bypass_cfg  # noqa: E402

OUT = ROOT / "lab" / "research" / "oos" / "vol_bypass_validate_latest.json"

# Same spirit as prior seats window + longer OOS.
WINDOWS = (
    ("recent_year", "2025-11-27", None),
    ("oos_2022", "2022-01-01", None),
)


def _slice_pack(pack, start: str, end: str | None):
    series, errors, sources = pack
    out = {}
    for code, s in series.items():
        hist = [
            h
            for h in (s.get("hist") or [])
            if h.get("date")
            and h["date"] >= start
            and (end is None or h["date"] <= end)
        ]
        if len(hist) < 80:
            continue
        meta = dict(s.get("meta") or {})
        out[code] = {"hist": hist, "meta": meta}
    return out, errors, sources


def _kpi(one: dict) -> dict:
    ret = one.get("ret_pct")
    dd = one.get("max_dd_pct")
    calmar = None
    if isinstance(ret, (int, float)) and isinstance(dd, (int, float)) and dd > 0:
        calmar = round(float(ret) / float(dd), 3)
    return {
        "ok": bool(one.get("ok")),
        "start": one.get("start"),
        "end": one.get("end"),
        "ret_pct": ret,
        "max_dd_pct": dd,
        "calmar": calmar,
        "trade_win_rate": one.get("trade_win_rate"),
        "closed_trades": one.get("closed_trades"),
        "vol_bypass_counts": one.get("vol_bypass_counts") or {},
        "blocks_vol": sum((one.get("vol_bypass_counts") or {}).values()),
    }


def _applicable(base: dict, with_vol: dict) -> dict:
    """High applicability: DD down and calmar up, or DD down with ret not much worse."""
    if not base.get("ok") or not with_vol.get("ok"):
        return {"adopt": False, "reason": "回测未成功", "score": 0}
    br, bd, bc = base["ret_pct"], base["max_dd_pct"], base.get("calmar")
    vr, vd, vc = with_vol["ret_pct"], with_vol["max_dd_pct"], with_vol.get("calmar")
    triggers = int(with_vol.get("blocks_vol") or 0)
    if triggers < 5:
        return {"adopt": False, "reason": f"触发过少({triggers})，样本不足", "score": 0}
    votes = 0
    notes = []
    if vd is not None and bd is not None and vd < bd:
        votes += 1
        notes.append(f"回撤改善 {bd}->{vd}")
    if vc is not None and bc is not None and vc > bc:
        votes += 1
        notes.append(f"Calmar改善 {bc}->{vc}")
    if vr is not None and br is not None and vr >= br * 0.85:
        votes += 1
        notes.append(f"收益可接受 {br}->{vr}")
    # High: ≥2 votes and DD improved; Medium: calmar up only → soft keep desk observe
    adopt = votes >= 2 and (vd is not None and bd is not None and vd <= bd)
    level = "高" if adopt and votes >= 3 else ("中" if votes >= 2 else "低")
    return {
        "adopt": adopt,
        "level": level,
        "score": votes,
        "triggers": triggers,
        "reason": "；".join(notes) or "无改善",
    }


def main() -> int:
    p = _load_cfg()
    pack = _fetch_pack(p["cfg"]["symbols"])
    carry = carry_bypass_cfg(p.get("carry_bypass") or p["cfg"].get("carry_bypass"))
    # Stress-test entry hard-block (action=block). Desk default remains observe-only.
    vol_on = vol_bypass_cfg(
        {
            **(p.get("vol_bypass") or p["cfg"].get("vol_bypass") or {}),
            "enabled": True,
            "action": "block",
        }
    )
    vol_off = dict(vol_on)
    vol_off["enabled"] = False

    windows = []
    adopt_any = False
    for name, start, end in WINDOWS:
        sliced = _slice_pack(pack, start, end)
        if len(sliced[0]) < 8:
            windows.append({"window": name, "ok": False, "error": "品种不足"})
            continue
        print(f"[vol-val] window={name} codes={len(sliced[0])} {start}→{end or 'latest'}")
        base = simulate(
            p["cfg"]["symbols"],
            p["equity0"],
            compound=p["compound"],
            risk_pct=p["risk_pct"],
            l1_mult=p["l1_mult"],
            max_positions=p["max_positions"],
            max_gross_pct=p["max_gross_pct"],
            max_port_risk=p["max_port_risk"],
            max_per_bucket=p["max_per_bucket"],
            min_r20=p["min_r20"],
            min_r60=p["min_r60"],
            min_lots=p.get("min_lots") or 0,
            option_hedge=False,
            reward_rr=float(p["reward_rr"]),
            stop_atr_mult=float(p["stop_atr_mult"]),
            mode="seats",
            pack=sliced,
            carry_bypass=carry,
            vol_bypass=vol_off,
        )
        treated = simulate(
            p["cfg"]["symbols"],
            p["equity0"],
            compound=p["compound"],
            risk_pct=p["risk_pct"],
            l1_mult=p["l1_mult"],
            max_positions=p["max_positions"],
            max_gross_pct=p["max_gross_pct"],
            max_port_risk=p["max_port_risk"],
            max_per_bucket=p["max_per_bucket"],
            min_r20=p["min_r20"],
            min_r60=p["min_r60"],
            min_lots=p.get("min_lots") or 0,
            option_hedge=False,
            reward_rr=float(p["reward_rr"]),
            stop_atr_mult=float(p["stop_atr_mult"]),
            mode="seats",
            pack=sliced,
            carry_bypass=carry,
            vol_bypass=vol_on,
        )
        kb, kt = _kpi(base), _kpi(treated)
        gate = _applicable(kb, kt)
        if gate.get("adopt"):
            adopt_any = True
        print(
            f"  base ret={kb.get('ret_pct')} dd={kb.get('max_dd_pct')} calmar={kb.get('calmar')}"
        )
        print(
            f"  +vol  ret={kt.get('ret_pct')} dd={kt.get('max_dd_pct')} calmar={kt.get('calmar')} "
            f"blocks={kt.get('blocks_vol')} → {gate}"
        )
        windows.append(
            {
                "window": name,
                "start": start,
                "end": end,
                "baseline": kb,
                "with_vol_bypass": kt,
                "applicability": gate,
            }
        )

    # Prefer recent_year for desk adopt; oos_2022 as confirmation.
    recent = next((w for w in windows if w.get("window") == "recent_year"), None)
    oos = next((w for w in windows if w.get("window") == "oos_2022"), None)
    adopt = bool((recent or {}).get("applicability", {}).get("adopt"))
    if adopt and oos and oos.get("applicability", {}).get("level") == "低":
        adopt = False
        decision = "不适用：近一年改善但长窗 OOS 适用性低，保持决策软旁路、不升入场硬拦"
    elif adopt:
        decision = "适用性高：并入回测入场旁路（与决策 observe 一致），配置保持 enabled"
    else:
        decision = "适用性不足：不升入场硬拦；研究台决策软旁路可保留标注"

    report = {
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "factor": "multidim_vol_factor_combo",
        "module": "vol_factor_combo.py",
        "mode": "seats + carry_bypass ± vol_bypass",
        "windows": windows,
        "adopt_entry_bypass": adopt,
        "decision_zh": decision,
        "hint": (
            "适用性门槛：近一年触发≥5，回撤不恶化，且至少两项改善"
            "（回撤↓ / Calmar↑ / 收益≥基准85%）。"
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = ROOT / "lab" / "research" / "runs" / f"vol_bypass_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run.mkdir(parents=True, exist_ok=True)
    (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[vol-val] wrote {OUT}")
    print(f"[vol-val] DECISION adopt_entry={adopt} — {decision}")
    return 0 if report.get("windows") else 1


if __name__ == "__main__":
    raise SystemExit(main())
