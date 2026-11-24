# -*- coding: utf-8 -*-
"""Render the README KPI block from a historical_backtest result JSON (R7a).

The block sits between ``<!-- KPI:BEGIN -->`` and ``<!-- KPI:END -->``; every number comes from the
result file, nothing is typed by hand.

usage:
  python scripts/render_readme_kpi.py --bt RESULT.json --out PREVIEW.md        # preview only
  python scripts/render_readme_kpi.py --bt RESULT.json --readme README.md      # replace the block in place
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- KPI:BEGIN -->"
END = "<!-- KPI:END -->"


def _f(x, nd=2, suffix=""):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return str(x)


def _pct_share(x):
    return "—" if x is None else f"{float(x) * 100:.1f}%"


def render_kpi_block(bt: dict) -> str:
    cv = bt.get("config_version") or {}
    rows = (bt.get("cost_scenario_contrast") or {}).get("rows") or {}
    base = rows.get("base") or {}
    stress = rows.get("stress") or {}
    val = bt.get("validation") or {}
    psr = (val.get("psr") or {}).get("psr")
    dsr = (val.get("dsr") or {}).get("dsr")
    pbo = (val.get("pbo") or {}).get("pbo")
    nt = bt.get("n_trials_assumed")
    exits = bt.get("exits") or {}
    lines = [
        BEGIN,
        f"正式 KPI（由 `scripts/render_readme_kpi.py` 从 `historical_backtest_latest.json` 生成，勿手改）："
        f"`schema_version={bt.get('schema_version')}`，{bt.get('entry_filter') or bt.get('mode')} / "
        f"{bt.get('fill_price')}，窗口 **{bt.get('start')}→{bt.get('end')}**（{bt.get('trade_days')} 个交易日），"
        f"`fill_series={bt.get('fill_series')}`，代码 `{cv.get('git_commit') or (bt.get('git_sha') or '')[:7]}`，"
        f"execution_rules `{str(cv.get('execution_rules_sha256') or bt.get('execution_rules_sha256') or '')[:12]}`。",
        "",
        "| 成本 | 净收益 | 毛收益 | 最大回撤 | 成本(元) | 交易 |",
        "|---|---|---|---|---|---|",
        f"| Base | {_f(base.get('ret_pct', bt.get('ret_pct')), 2, '%')} | "
        f"{_f(base.get('gross_ret_pct', bt.get('gross_ret_pct')), 2, '%')} | "
        f"{_f(base.get('max_dd_pct', bt.get('max_dd_pct')), 2, '%')} | {_f(base.get('cost_yuan', bt.get('cost_yuan')), 0)} | "
        f"{base.get('closed_trades', bt.get('closed_trades'))} |",
    ]
    if stress:
        lines.append(
            f"| Stress | {_f(stress.get('ret_pct'), 2, '%')} | {_f(stress.get('gross_ret_pct'), 2, '%')} | "
            f"{_f(stress.get('max_dd_pct'), 2, '%')} | {_f(stress.get('cost_yuan'), 0)} | {stress.get('closed_trades')} |"
        )
    lines += [
        "",
        f"胜率 {_f(bt.get('trade_win_rate'), 2, '%')}，期望 {_f(bt.get('expectancy_r'), 3)}R，"
        f"出场 止盈 {exits.get('target', 0)} / 止损 {exits.get('stop', 0)} / 信号 {exits.get('signal', 0)}，"
        f"proxy 入场占比 {_pct_share(bt.get('proxy_entry_share'))}，当日平仓占比 {_pct_share(bt.get('same_day_exit_share'))}。"
        f"验证（Research 诊断，不单独晋级）：PSR {_f(psr, 3)}，DSR {_f(dsr, 3)}（n_trials={nt}），PBO {_f(pbo, 3)}。"
        f"结论「{bt.get('conclusion')}」。",
        END,
    ]
    return "\n".join(lines) + "\n"


def replace_block(text: str, block: str) -> str:
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
    if not pat.search(text):
        raise SystemExit(f"README has no {BEGIN} … {END} block; insert the markers first")
    return pat.sub(lambda _m: block, text, count=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bt", default=str(ROOT / "historical_backtest_latest.json"))
    ap.add_argument("--out", default=None, help="write the block (preview) here")
    ap.add_argument("--readme", default=None, help="replace the marked block in this README in place")
    a = ap.parse_args(argv)
    bt = json.loads(Path(a.bt).read_text(encoding="utf-8"))
    block = render_kpi_block(bt)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(block, encoding="utf-8")
        print(f"[kpi] preview -> {a.out}")
    if a.readme:
        p = Path(a.readme)
        p.write_text(replace_block(p.read_text(encoding="utf-8"), block), encoding="utf-8")
        print(f"[kpi] README block replaced -> {p}")
    if not a.out and not a.readme:
        sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
