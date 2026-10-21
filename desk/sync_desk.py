# -*- coding: utf-8 -*-
"""Pull GitHub Actions daily reports into the local Streamlit desk.

Actions write remote l1_report.json / archive / Notion at 15:30 CST.
The desk only reads local disk; this helper pulls the repo (and optionally
re-runs daily_update.py for member+sina cache). No orders are placed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "cmd": cmd,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "cmd": cmd,
            "returncode": None,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
        }
    return {
        "ok": proc.returncode == 0,
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def git_repo_status(root: Path) -> dict:
    """Describe whether root is a git checkout usable for pull."""
    git_dir = root / ".git"
    if not git_dir.exists():
        return {
            "is_git": False,
            "has_remote": False,
            "branch": None,
            "message": "不是 git 仓库；无法 git pull，可改用「刷新本地缓存」跑 daily_update.py。",
        }
    head = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root, timeout=30)
    remote = _run(["git", "remote"], root, timeout=30)
    remotes = [line.strip() for line in (remote.get("stdout") or "").splitlines() if line.strip()]
    branch = (head.get("stdout") or "").strip() or None
    if not head.get("ok"):
        return {
            "is_git": True,
            "has_remote": bool(remotes),
            "branch": branch,
            "message": "git 仓库异常，无法解析分支。",
        }
    if not remotes:
        return {
            "is_git": True,
            "has_remote": False,
            "branch": branch,
            "message": "本地是 git 仓库但没有 remote；无法 pull，可改用 daily_update.py。",
        }
    return {
        "is_git": True,
        "has_remote": True,
        "branch": branch,
        "remotes": remotes,
        "message": f"git 仓库 · 分支 {branch} · remote {', '.join(remotes)}",
    }


def report_mtime_note(root: Path, now: datetime | None = None) -> dict:
    """Local l1_report.json mtime vs Shanghai calendar day (staleness hint)."""
    path = root / "l1_report.json"
    now = now or datetime.now(TZ)
    if not path.is_file():
        return {
            "exists": False,
            "path": str(path),
            "mtime": None,
            "asof": None,
            "stale": True,
            "note": "本地没有 l1_report.json。请「同步日报」或运行 daily_update.py。",
        }
    mtime = datetime.fromtimestamp(path.stat().st_mtime, TZ)
    asof = None
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            asof = str(payload.get("asof") or "") or None
    except Exception:
        asof = None
    today = now.strftime("%Y%m%d")
    asof_ymd = (asof or "").replace("-", "")
    # After 15:30 CST on a weekday, today's Actions run should exist; before that, yesterday is fine.
    after_cutoff = (now.hour, now.minute) >= (15, 30)
    expect = today if after_cutoff else None
    stale = False
    if expect and asof_ymd and asof_ymd < expect:
        stale = True
    elif expect and not asof_ymd and mtime.date() < now.date():
        stale = True
    elif mtime.date() < now.date() and after_cutoff:
        stale = True
    mtime_s = mtime.strftime("%Y-%m-%d %H:%M:%S %Z")
    if stale:
        note = (
            f"本地 l1_report.json 可能偏旧：mtime {mtime_s}"
            + (f" · asof {asof}" if asof else "")
            + "。15:30 后若 Actions 已跑完，点「同步日报」拉取。"
        )
    else:
        note = (
            f"本地 l1_report.json：mtime {mtime_s}"
            + (f" · asof {asof}" if asof else "")
            + "。"
        )
    return {
        "exists": True,
        "path": str(path),
        "mtime": mtime_s,
        "asof": asof,
        "stale": stale,
        "note": note,
    }


def sync_desk(
    root: Path,
    *,
    pull_git: bool = True,
    refresh_cache: bool = False,
    dry_run: bool = False,
) -> dict:
    """Pull remote reports and/or refresh local free-source cache.

    Default: git pull only (fast). refresh_cache runs ``python daily_update.py``
    (member + sina; can be slow / network). dry_run reports planned steps only.
    """
    root = Path(root)
    status = git_repo_status(root)
    mtime = report_mtime_note(root)
    steps: list[dict] = []
    messages: list[str] = [status["message"], mtime["note"]]

    if dry_run:
        if pull_git:
            if status.get("is_git") and status.get("has_remote"):
                steps.append({"step": "git_pull", "planned": True, "detail": "git pull --ff-only"})
            elif status.get("is_git"):
                steps.append(
                    {
                        "step": "git_pull",
                        "planned": False,
                        "detail": "跳过：无 remote",
                    }
                )
            else:
                steps.append(
                    {
                        "step": "git_pull",
                        "planned": False,
                        "detail": "跳过：不是 git 仓库",
                    }
                )
        if refresh_cache or (pull_git and not status.get("has_remote")):
            steps.append(
                {
                    "step": "daily_update",
                    "planned": True,
                    "detail": f"{sys.executable} daily_update.py",
                }
            )
        elif not pull_git and not refresh_cache:
            messages.append("未勾选任何同步项。")
        return {
            "ok": True,
            "dry_run": True,
            "git": status,
            "report": mtime,
            "steps": steps,
            "messages": messages,
        }

    ok = True
    pulled = False
    if pull_git:
        if status.get("is_git") and status.get("has_remote"):
            result = _run(["git", "pull", "--ff-only"], root, timeout=180)
            steps.append({"step": "git_pull", **result})
            if result["ok"]:
                pulled = True
                messages.append(result["stdout"] or "git pull 完成。")
            else:
                ok = False
                messages.append(
                    "git pull 失败："
                    + (result["stderr"] or result["stdout"] or f"code={result['returncode']}")
                )
                messages.append("可改勾「刷新本地缓存」用 daily_update.py 从免费源重建。")
        else:
            steps.append(
                {
                    "step": "git_pull",
                    "ok": False,
                    "skipped": True,
                    "detail": status["message"],
                }
            )
            messages.append(status["message"])
            if not refresh_cache:
                messages.append(
                    "已跳过 git pull。请勾选「刷新本地缓存」运行 daily_update.py，"
                    "或配置 remote 后再同步。"
                )

    # If git pull is unavailable, the UI still offers「刷新本地缓存」→ daily_update.py.
    # Do not auto-run the slow network path unless the user checked that box.
    if refresh_cache:
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        try:
            proc = subprocess.run(
                [sys.executable, "daily_update.py"],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                check=False,
                env=env,
            )
            result = {
                "ok": proc.returncode == 0,
                "cmd": [sys.executable, "daily_update.py"],
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "").strip()[-4000:],
                "stderr": (proc.stderr or "").strip()[-2000:],
            }
        except subprocess.TimeoutExpired:
            result = {
                "ok": False,
                "cmd": [sys.executable, "daily_update.py"],
                "returncode": None,
                "stdout": "",
                "stderr": "timeout after 900s",
            }
        steps.append({"step": "daily_update", **result})
        if result["ok"]:
            messages.append("daily_update.py 完成（日报 + 本地 member/sina 缓存）。")
        else:
            ok = False
            messages.append(
                "daily_update.py 失败："
                + (result["stderr"] or result["stdout"] or f"code={result['returncode']}")
            )

    mtime_after = report_mtime_note(root)
    messages.append(mtime_after["note"])
    return {
        "ok": ok,
        "dry_run": False,
        "git": status,
        "report": mtime_after,
        "steps": steps,
        "messages": messages,
        "ran_update": bool(refresh_cache),
        "pulled": pulled,
    }


def clear_streamlit_caches() -> None:
    """Best-effort clear of Streamlit cache_data / cache_resource."""
    try:
        import streamlit as st

        st.cache_data.clear()
        st.cache_resource.clear()
    except Exception:
        pass
