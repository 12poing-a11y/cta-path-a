# -*- coding: utf-8 -*-
"""One-shot TqSdk connectivity probe. Creds via TQ_USER/TQ_PASS or .env.tqsdk only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tqsdk_client import (  # noqa: E402
    fetch_daily_bars,
    fetch_option_chain_snapshot,
    load_credentials,
    to_tq_main,
    to_tq_symbol,
)


def main() -> int:
    creds = load_credentials(root=ROOT)
    if not creds:
        print(
            "未找到账号。请设置环境变量 TQ_USER / TQ_PASS，"
            "或写入仓库根目录 .env.tqsdk（已 gitignore）：\n"
            "  TQ_USER=你的快期账号\n"
            "  TQ_PASS=你的快期密码"
        )
        return 2

    print(f"账号: {creds[0][:2]}***{creds[0][-2:] if len(creds[0]) > 4 else ''}")
    print(f"映射: CF2701 → {to_tq_symbol('CF2701')}  |  主力 CF → {to_tq_main('CF')}")

    bars, src = fetch_daily_bars("CF2701", length=30, root=ROOT)
    print(f"\n[日线] source={src}  bars={len(bars)}")
    if bars:
        print("  first:", json.dumps(bars[0], ensure_ascii=False))
        print("  last :", json.dumps(bars[-1], ensure_ascii=False))

    main_bars, main_src = fetch_daily_bars("CF", length=10, main=True, root=ROOT)
    print(f"\n[主力] source={main_src}  bars={len(main_bars)}")
    if main_bars:
        print("  last :", json.dumps(main_bars[-1], ensure_ascii=False))

    for und in ("CF2701", "P2701"):
        print(f"\n[期权链] {und} (OI + OPTION_IMPV) …")
        snap = fetch_option_chain_snapshot(und, root=ROOT, max_options=40)
        rows = snap.get("rows") or []
        with_oi = sum(1 for r in rows if (r.get("持仓量") or 0) > 0)
        with_iv = sum(1 for r in rows if r.get("隐含波动率") is not None)
        print(
            f"  asof={snap.get('asof')}  und={snap.get('underlying_symbol')}  "
            f"last={snap.get('underlying_last')}  rows={len(rows)}  "
            f"OI>0={with_oi}  IV={with_iv}"
        )
        if snap.get("notes"):
            print("  notes:", "; ".join(str(n) for n in snap["notes"][:8]))
        for r in rows[:3]:
            print(
                "  sample:",
                r.get("合约代码"),
                "side=",
                r.get("期权类型"),
                "K=",
                r.get("行权价"),
                "OI=",
                r.get("持仓量"),
                "IV%=",
                r.get("隐含波动率"),
            )
    return 0 if bars else 1


if __name__ == "__main__":
    raise SystemExit(main())
