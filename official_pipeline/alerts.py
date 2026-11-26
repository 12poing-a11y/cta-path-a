# -*- coding: utf-8 -*-
"""Alerts: a local file (always) plus a Windows notification (best effort; never raises)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import config as C
from .store import utc_now


def write_alert(day: str, reasons: list[str], details: list[str], *, root: Path | None = None) -> Path:
    d = Path(root or C.ALERTS)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"ALERT_{day}.md"
    lines = [f"# 官方数据管道告警 {day}", "", f"生成时间 (UTC): {utc_now()}", "", "## 原因", *[f"- {r}" for r in reasons],
             "", "## 细节", *[f"- {x}" for x in details], "",
             "只生成告警，不自动修复、不自动改任何研究口径。"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def notify(title: str, text: str) -> bool:
    script = Path(__file__).with_name("notify.ps1")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                            "-Title", title, "-Text", text[:200]], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False
