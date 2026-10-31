# -*- coding: utf-8 -*-
"""Pull GitHub Actions daily reports into the local Streamlit desk.

Actions at 15:30 CST commit l1_report / archive, full member ranks,
sina continuous CODE0, and 15m/60m minute caches. The desk only reads
local disk; this helper git-pulls (and optionally re-runs daily_update.py).
No orders are placed.
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


def _read_json(path: Path) -> dict | None:
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _norm_ymd(value: str | None) -> str:
    return str(value or "").replace("-", "")[:8]


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
    payload = _read_json(path) or {}
    asof = str(payload.get("asof") or "") or None
    today = now.strftime("%Y%m%d")
    asof_ymd = _norm_ymd(asof)
    # After 15:30 CST today's Actions run is *scheduled*; it may land hours late (10/30: 22:28) -> flag 待核, not '应已有'.
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
            + "。待核：Actions 预定 15:30，实际常延迟（10/30 至 22:28 才完成），"
            + "asof 早于今日不代表今日数据已到；可点「同步日报」重试拉取。数据只含日盘，不含夜盘。"
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


def book_freshness(root: Path, now: datetime | None = None) -> dict:
    """Single glance: l1 asof vs paper book vs backtest end vs equity_state."""
    now = now or datetime.now(TZ)
    root = Path(root)
    l1 = report_mtime_note(root, now=now)
    l1_ymd = _norm_ymd(l1.get("asof"))

    paper = _read_json(root / "paper_book_latest.json") or {}
    paper_ymd = _norm_ymd(paper.get("asof") or paper.get("asof_ymd"))
    paper_held = len(paper.get("positions") or {}) if paper.get("ok") else None

    bt = _read_json(root / "historical_backtest_latest.json") or {}
    bt_end = str(bt.get("end") or "") if bt else ""
    bt_ymd = _norm_ymd(bt_end)
    bt_held = (
        len(bt.get("final_positions") or {})
        if isinstance(bt.get("final_positions"), dict)
        else None
    )

    eq = _read_json(root / "equity_state.json") or {}
    eq_asof = str(eq.get("asof") or "") or None
    eq_path = root / "equity_state.json"
    eq_mtime = None
    if eq_path.is_file():
        eq_mtime = datetime.fromtimestamp(eq_path.stat().st_mtime, TZ).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )

    clocks_aligned = bool(l1_ymd and paper_ymd and l1_ymd == paper_ymd)
    book_behind = bool(l1_ymd and paper_ymd and paper_ymd < l1_ymd)
    book_missing = not bool(paper.get("ok"))
    stale = bool(l1.get("stale") or book_behind or book_missing)

    lines = [
        f"日信号 asof={l1.get('asof') or '—'}",
        f"模拟仓 asof={paper.get('asof') or '—'} · 持仓{paper_held if paper_held is not None else '—'}",
        f"回测期末 end={bt_end or '—'} · 期末持仓{bt_held if bt_held is not None else '—'}",
        f"equity_state asof={eq_asof or '—'} · mtime {eq_mtime or '—'}",
    ]
    if clocks_aligned:
        note = "时钟对齐：" + " · ".join(lines)
    elif book_missing:
        note = (
            "模拟仓缺失 paper_book_latest.json。同步日报后会自动刷新，"
            "或运行 python paper_book.py。 · "
            + " · ".join(lines)
        )
    elif book_behind:
        note = (
            f"模拟仓落后日信号（{paper.get('asof')} < {l1.get('asof')}）。"
            "请同步/刷新日报，或运行 python paper_book.py。 · "
            + " · ".join(lines)
        )
    else:
        note = "新鲜度：" + " · ".join(lines)

    return {
        "stale": stale,
        "aligned": clocks_aligned,
        "book_behind": book_behind,
        "book_missing": book_missing,
        "l1_asof": l1.get("asof"),
        "paper_asof": paper.get("asof"),
        "backtest_end": bt_end or None,
        "equity_asof": eq_asof,
        "equity_mtime": eq_mtime,
        "paper_held": paper_held,
        "backtest_held": bt_held,
        "l1": l1,
        "note": note,
        "lines": lines,
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
                steps.append(
                    {
                        "step": "git_pull",
                        "planned": True,
                        "detail": "git fetch origin main && git checkout origin/main -- l1_report.json l1_report_risk15.json archive",
                    }
                )
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
            fetch = _run(["git", "fetch", "origin", "main"], root, timeout=180)
            steps.append({"step": "git_fetch_main", **fetch})
            if not fetch["ok"]:
                ok = False
                messages.append(
                    "git fetch origin main 失败："
                    + (fetch["stderr"] or fetch["stdout"] or f"code={fetch['returncode']}")
                )
            else:
                checkout = _run(
                    [
                        "git",
                        "checkout",
                        "origin/main",
                        "--",
                        "l1_report.json",
                        "l1_report_risk15.json",
                        "archive",
                    ],
                    root,
                    timeout=60,
                )
                steps.append({"step": "git_checkout_reports", **checkout})
                if checkout["ok"]:
                    pulled = True
                    messages.append(
                        "已从 origin/main 取回日报（l1_report.json、l1_report_risk15.json、archive）。"
                        "日常任务只提交到 main，当前功能分支的 git pull 带不回这些文件。"
                    )
                else:
                    ok = False
                    messages.append(
                        "取出 main 日报失败："
                        + (checkout["stderr"] or checkout["stdout"] or f"code={checkout['returncode']}")
                    )
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

    # Roll simulated open book to latest l1 asof (desk/Notion shared source).
    paper_step: dict = {"step": "paper_book", "ok": False}
    try:
        from paper_book import refresh_paper_book

        paper_out = refresh_paper_book(root)
        paper_step.update(
            {
                "ok": bool(paper_out.get("ok")),
                "asof": paper_out.get("asof"),
                "held_n": paper_out.get("held_n"),
                "detail": paper_out.get("error") or paper_out.get("notes"),
            }
        )
        if paper_out.get("ok"):
            messages.append(
                f"模拟仓已刷新 asof={paper_out.get('asof')} · "
                f"持仓{paper_out.get('held_n')} · "
                f"新开{paper_out.get('opened_n')} · 平仓{paper_out.get('closed_n')}。"
            )
        else:
            messages.append("模拟仓刷新跳过：" + str(paper_out.get("error") or "unknown"))
    except Exception as exc:
        paper_step["stderr"] = str(exc)[:300]
        messages.append(f"模拟仓刷新异常：{exc}")
    steps.append(paper_step)

    mtime_after = report_mtime_note(root)
    fresh = book_freshness(root)
    messages.append(mtime_after["note"])
    messages.append(fresh["note"])
    return {
        "ok": ok,
        "dry_run": False,
        "git": status,
        "report": mtime_after,
        "freshness": fresh,
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
