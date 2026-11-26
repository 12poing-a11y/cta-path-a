# -*- coding: utf-8 -*-
"""Official daily data pipeline: paths and fixed settings.

Decisions (磊, 2026-11-26): store outside the repo at D:\\AI\\data\\official\\; repo holds code + hash manifests only;
weekly backup; Playwright pinned; seed from archive/R8/raw_contract after hash verification; alert = local file + Windows
notification; daily summaries are not committed to main.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R8_DIR = ROOT / "archive" / "R8"
if str(R8_DIR) not in sys.path:  # parsers + product/exchange table live in the R8 fetch code (reused, not copied)
    sys.path.insert(0, str(R8_DIR))

STORE = Path(os.environ.get("CTA_OFFICIAL_STORE", r"D:\AI\data\official"))
RAW = STORE / "raw"                 # raw/{shfe,czce,dce}/{YYYYMMDD}.gz + raw/MANIFEST_{ex}.json (R8 layout, reused by contract_loader)
REVISIONS = STORE / "revisions"     # changed content for an already-stored day: kept beside the original, never overwrites it
REPORTS = STORE / "reports"         # daily validation reports (not committed)
ALERTS = STORE / "alerts"           # ALERT_{date}.md
DERIVED = STORE / "derived"         # official main-contract map per day
LOGS = STORE / "logs"
STATE = STORE / "state.json"        # normal-day streak for the shadow start gate
BACKUP_ROOT = STORE.parent / "official_backup"   # weekly backup target (outside the store)
SEED_RAW = R8_DIR / "raw_contract"  # R8 raw library (seed; left untouched)
HASH_EXPORT = ROOT / "official_pipeline" / "manifest_repo"  # repo-side hash manifests only

# 27 universe products -> exchange (same table as the R8 loader)
from contract_loader import EXCH, CODE_EX  # noqa: E402  (archive/R8/contract_loader.py)

PRODUCTS = sorted(CODE_EX)
EXCHANGES = ("shfe", "czce", "dce")
REQUIRED_EXCHANGES_PER_DAY = EXCHANGES  # a trading day is complete only when all three are stored

SHFE_URL = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{ymd}.dat"
CZCE_URL = "http://www.czce.com.cn/cn/DFSStaticFiles/Future/{y}/{ymd}/FutureDataDaily.txt"
DCE_PAGE = "http://www.dce.com.cn/"
DCE_API = "/dcereport/publicweb/dailystat/dayQuotes"

MIN_BODY_BYTES = 500
RETRY_ATTEMPTS = 4
NORMAL_STREAK_REQUIRED = 5          # shadow start gate (PREREG_SHADOW_300K.md §7)
PRICE_JUMP_INFO = 0.10              # |close / presettle - 1| above this is listed (info), not failed
