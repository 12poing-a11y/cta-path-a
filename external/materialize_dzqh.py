# -*- coding: utf-8 -*-
"""Materialize 东证周报 catalog into KPI JSON + validation-archive desk specs.

Does **not** activate the research desk. Paste-only sources stay under
``external/archive`` for later verification against local proxies / Path-A.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "external" / "dzqh_weekly_latest.json"
OUT_DIR = ROOT / "external" / "strategies"
ARCHIVE_SPECS = ROOT / "external" / "archive" / "desk_specs"


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_SPECS.mkdir(parents=True, exist_ok=True)
    asof = catalog.get("asof")
    source = catalog.get("source")
    archived_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for row in catalog.get("strategies") or []:
        if row.get("placeholder"):
            continue
        if row.get("ret_ann_pct") is None and row.get("sharpe") is None and row.get("max_dd_pct") is None:
            continue
        sid = str(row["id"])
        is_placeholder = bool(row.get("placeholder")) or (
            row.get("ret_ann_pct") is None
            and row.get("sharpe") is None
            and row.get("calmar") is None
            and row.get("max_dd_pct") is None
        )
        payload = {
            "ok": not is_placeholder,
            "strategy": sid,
            "name": row.get("name"),
            "family": row.get("family"),
            "menu": row.get("menu"),
            "description": row.get("description"),
            "track_source": source,
            "asof": asof,
            "ret_ann_pct": row.get("ret_ann_pct"),
            "ret_pct": row.get("ret_ann_pct"),
            "sharpe": row.get("sharpe"),
            "calmar": row.get("calmar"),
            "max_dd_pct": row.get("max_dd_pct"),
            "week_ret_pct": row.get("week_ret_pct"),
            "ytd_ret_pct": row.get("ytd_ret_pct"),
            "ret_since_publish_ann_pct": row.get("ret_since_publish_ann_pct"),
            "sharpe_since_publish": row.get("sharpe_since_publish"),
            "max_dd_since_publish_pct": row.get("max_dd_since_publish_pct"),
            "publish_start": row.get("publish_start"),
            "sample_out_start": row.get("sample_out_start"),
            "leverage": row.get("leverage"),
            "disclaimer": catalog.get("disclaimer"),
            "placeholder": is_placeholder,
            "desk_active": False,
            "validation_archive": True,
            "summary": (
                f"{row.get('name')} 跟踪 asof={asof} "
                f"ann={row.get('ret_ann_pct')} sharpe={row.get('sharpe')} "
                f"dd={row.get('max_dd_pct')}"
                + (" · 占位待填 KPI" if is_placeholder else "")
                + " · 验证归档（不进研究台）"
            ),
        }
        if payload.get("calmar") is None:
            ret = payload.get("ret_ann_pct")
            dd = payload.get("max_dd_pct")
            if isinstance(ret, (int, float)) and isinstance(dd, (int, float)) and dd > 0:
                payload["calmar"] = round(float(ret) / float(dd), 3)

        curve_rel = Path("external") / "strategies" / f"{sid}.json"
        out_path = ROOT / curve_rel
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        tags = list(row.get("tags") or ["external", "dzqh"])
        for t in ("validation_archive", "unstable_source"):
            if t not in tags:
                tags.append(t)
        extra = {
            "id": sid,
            "name": row.get("name"),
            "description": row.get("description") or "",
            "curve_file": str(curve_rel).replace("\\", "/"),
            "tags": tags,
            "placeholder": is_placeholder,
            "desk_active": False,
            "archive_reason": (
                "不能长期稳定自动获取（依赖用户粘贴东证周报 KPI）；"
                "退出研究台展示，保留供后期对照验证。"
            ),
            "archived_at": archived_at,
        }
        (ARCHIVE_SPECS / f"{sid}.json").write_text(
            json.dumps(extra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[dzqh-archive] {sid} -> {curve_rel} + archive/desk_specs/")


if __name__ == "__main__":
    main()
