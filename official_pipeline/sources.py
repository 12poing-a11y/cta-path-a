# -*- coding: utf-8 -*-
"""Fetchers. SHFE / CZCE: plain HTTP (verified in R8). DCE: real Chrome via Playwright (scripted requests get HTTP 412).

Each fetcher returns (status, body, url):
  status 'ok' with body bytes, or 'not_published' (404 / empty), or 'http<code>', 'error', 'format_unverified'.
"""
from __future__ import annotations

import time
import warnings
from typing import Iterable

from . import config as C

warnings.filterwarnings("ignore")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def http_url(ex: str, day: str) -> str:
    ymd = day.replace("-", "")
    if ex == "shfe":
        return C.SHFE_URL.format(ymd=ymd)
    if ex == "czce":
        return C.CZCE_URL.format(y=day[:4], ymd=ymd)
    raise ValueError(ex)


def fetch_http(ex: str, day: str, session=None) -> tuple[str, bytes | None, str]:
    import requests

    url = http_url(ex, day)
    s = session or requests
    last = ("error", None, url)
    for attempt in range(C.RETRY_ATTEMPTS):
        try:
            r = s.get(url, headers=UA, timeout=40)
            if r.status_code == 200 and len(r.content) > C.MIN_BODY_BYTES:
                return "ok", r.content, url
            if r.status_code == 404 or (r.status_code == 200 and len(r.content) <= C.MIN_BODY_BYTES):
                last = ("not_published", None, url)
            else:
                last = (f"http{r.status_code}", None, url)
        except Exception as e:  # noqa: BLE001
            last = ("error", None, url)
            last_err = repr(e)[:160]
            _ = last_err
        time.sleep(1.5 * (attempt + 1))
    return last


def save_response(ex: str, day: str, text: str) -> Path:
    """Verbatim response text of a 200 reply, outside the repo, overwritten only by a re-fetch of the same day."""
    p = C.STORE / "responses" / ex / f"{day.replace('-', '')}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


DCE_COLS = ["contractId", "open", "high", "low", "close", "lastClear", "clearPrice", "volumn", "openInterest", "turnover"]


def dce_response_to_body(text: str, day: str) -> bytes | None:
    """Canonical body (same bytes as archive/R8/ingest_dce.py: compact sorted JSON of {cols, rows}, universe varieties only)
    from one DCE dayQuotes JSON reply, verified on 2026-11-26 against a live reply:
    {"success": true, "code": 200, "msg": "操作成功", "data": [{"variety", "contractId", "open", ...}, ...]}.
    Returns None when the reply carries no universe rows (non-trading day -> 'not_published').
    Raises ValueError for any other shape (never guessed)."""
    import json

    from contract_loader import CODE_EX  # R8 product table (shared)

    j = json.loads(text)
    if not isinstance(j, dict) or j.get("success") is not True or not isinstance(j.get("data"), list):
        raise ValueError(f"dce reply not a success list: code={j.get('code') if isinstance(j, dict) else '?'}")
    if j["data"] and not all(k in j["data"][0] for k in DCE_COLS):
        raise ValueError("dce reply lacks expected columns: " + ",".join(k for k in DCE_COLS if k not in j["data"][0]))
    rows = []
    for r in j["data"]:
        cid = str(r.get("contractId", "")).upper()
        code = "".join(ch for ch in cid if ch.isalpha())
        if code not in CODE_EX or CODE_EX[code] != "dce":
            continue
        rows.append([r.get(c) for c in DCE_COLS])
    if not rows:
        return None
    return json.dumps({"cols": DCE_COLS, "rows": rows}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fetch_dce_days(days: Iterable[str]) -> dict[str, tuple[str, bytes | None, str]]:
    """Open Chrome (visible, minimised, automation flags removed), load the DCE site for a session, then POST each day
    same-origin. Every day returns its status; nothing is written on failure."""
    from playwright.sync_api import sync_playwright

    out: dict[str, tuple[str, bytes | None, str]] = {}
    days = list(days)
    if not days:
        return out
    js = """async ([url, payload]) => {
      const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      return {status: r.status, text: await r.text()};
    }"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=False,
            args=["--start-minimized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            page = browser.new_context(locale="zh-CN", viewport={"width": 1280, "height": 900}).new_page()
            page.goto(C.DCE_PAGE, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(6000)
            for d in days:
                payload = {"tradeDate": d.replace("-", ""), "varietyId": "all", "tradeType": "1"}
                try:
                    res = page.evaluate(js, [C.DCE_API, payload])
                except Exception:  # noqa: BLE001  (navigation / context loss / network)
                    out[d] = ("error", None, C.DCE_API)
                    continue
                if res["status"] != 200:
                    out[d] = (f"http{res['status']}", None, C.DCE_API)
                    continue
                save_response("dce", d, res["text"])  # verbatim reply kept outside the repo for audit
                try:
                    body = dce_response_to_body(res["text"], d)
                except ValueError as e:
                    out[d] = (f"format_unverified:{str(e)[:80]}", None, C.DCE_API)
                    continue
                out[d] = ("ok", body, C.DCE_API) if body is not None else ("not_published", None, C.DCE_API)
        finally:
            browser.close()
    return out
