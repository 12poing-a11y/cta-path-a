# -*- coding: utf-8 -*-
"""One-shot Fuyao (同花顺扶摇) connectivity probe. Key via env / .env.fuyao only."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://fuyao.aicubes.cn"
ROOT = Path(__file__).resolve().parents[1]


def _load_key() -> str:
    key = (os.environ.get("FUYAO_API_KEY") or os.environ.get("API_KEY") or "").strip()
    if key:
        return key
    for name in (".env.fuyao", ".env"):
        path = ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() in {"FUYAO_API_KEY", "API_KEY"} and v.strip():
                return v.strip().strip('"').strip("'")
    raise SystemExit(
        "未找到 Key。请设置环境变量 FUYAO_API_KEY，或写入仓库根目录 .env.fuyao（已 gitignore）。"
    )


def get(path: str, key: str, **params) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"X-api-key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return {"http": resp.status, "url": url, "body": body}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw[:500]}
        return {"http": e.code, "url": url, "body": body}


def summarize(label: str, result: dict) -> None:
    body = result.get("body") or {}
    code = body.get("code")
    msg = body.get("message")
    data = body.get("data")
    n = None
    sample = None
    if isinstance(data, dict):
        items = data.get("item")
        if isinstance(items, list):
            n = len(items)
            if items:
                sample = items[-1]
        elif data.get("thscode"):
            n = "obj"
            sample = data
    print(f"[{label}] http={result.get('http')} code={code} msg={msg} items={n}")
    if code not in (0, None):
        print("  detail:", json.dumps(body, ensure_ascii=False)[:420])
    elif sample is not None:
        print("  sample:", json.dumps(sample, ensure_ascii=False)[:320])


def main() -> int:
    key = _load_key()
    print(f"key_loaded=yes len={len(key)} prefix={key[:4]}…")

    # Resolve thscode via meta search (param name is q).
    search = get("/api/meta/tickers/search", key, q="CF2701", limit=10)
    summarize("meta_search_CF2701", search)
    thscodes: list[str] = []
    items = ((search.get("body") or {}).get("data") or {}).get("item") or []
    for it in items:
        code = str(it.get("thscode") or "")
        if code:
            thscodes.append(code)
            print(f"  hit: {code} | {it.get('name')} | {it.get('asset_type')}")

    if not thscodes:
        # Broader queries / exchange filter.
        for q, exch in (("棉花", "CZCE"), ("CF", "CZCE"), ("CF2701", None)):
            params = {"q": q, "limit": 15}
            if exch:
                params["exchange"] = exch
            r = get("/api/meta/tickers/search", key, **params)
            summarize(f"meta_search_{q}_{exch or 'any'}", r)
            for it in ((r.get("body") or {}).get("data") or {}).get("item") or []:
                code = str(it.get("thscode") or "")
                if code and code not in thscodes:
                    thscodes.append(code)
                    print(f"  hit: {code} | {it.get('name')} | {it.get('asset_type')}")

    # Try known suffix variants + search hits.
    candidates = list(
        dict.fromkeys(
            thscodes
            + [
                "CF2701.CZC",
                "CF2701.CZCE",
                "CF701.CZC",
                "CF2701.ZCE",
            ]
        )
    )
    ok = 0
    picked = None
    for ths in candidates[:12]:
        r = get("/api/futures/prices/daily", key, thscode=ths)
        summarize(f"futures_daily_{ths}", r)
        if (r.get("body") or {}).get("code") == 0:
            ok += 1
            picked = ths
            break

    if picked:
        r = get("/api/futures/calendar/trading-schedule", key, thscode=picked)
        summarize(f"futures_calendar_{picked}", r)
        if (r.get("body") or {}).get("code") == 0:
            ok += 1

    r = get("/api/options/varieties/list", key, limit=20)
    summarize("options_varieties", r)
    if (r.get("body") or {}).get("code") == 0:
        ok += 1
        # Find cotton option variety if present.
        for it in ((r.get("body") or {}).get("data") or {}).get("item") or []:
            name = str(it.get("name") or "")
            if "棉花" in name or str(it.get("variety_code") or "") in {"CF", "CFO"}:
                print("  cotton_variety:", json.dumps(it, ensure_ascii=False)[:280])

    # Option contract list / one daily bar if we can find a thscode.
    opt_search = get("/api/meta/tickers/search", key, q="CF701C", limit=10)
    summarize("meta_search_option_CF701C", opt_search)
    for it in ((opt_search.get("body") or {}).get("data") or {}).get("item") or []:
        code = str(it.get("thscode") or "")
        if not code:
            continue
        print(f"  opt_hit: {code} | {it.get('name')} | {it.get('asset_type')}")
        od = get("/api/options/prices/daily", key, thscode=code)
        summarize(f"options_daily_{code}", od)
        if (od.get("body") or {}).get("code") == 0:
            ok += 1
        break

    print(f"ok_calls={ok} picked_futures={picked}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
