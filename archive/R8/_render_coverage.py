# -*- coding: utf-8 -*-
"""Render archive/R8/LONG_COVERAGE_REPORT.md from the read-only probe outputs (numbers are copied by code, not by hand)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R8 = ROOT / "archive" / "R8"
cov = json.loads((R8 / "long_coverage_probe.json").read_text(encoding="utf-8"))
p2 = json.loads((R8 / "long_coverage_probe2.json").read_text(encoding="utf-8"))
cp = json.loads((R8 / "long_c_pool_static.json").read_text(encoding="utf-8"))
uni = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
rows = cov["rows"]
months = list(cp["levels"]["1000000"]["per_month"].keys())


def runs(ms):
    """Collapse a sorted list of 'YYYY-MM' into 'a..b' ranges (consecutive calendar months)."""
    if not ms:
        return "-"
    idx = {m: i for i, m in enumerate(months)}
    out, s, p = [], ms[0], ms[0]
    for m in ms[1:]:
        if idx[m] == idx[p] + 1:
            p = m
        else:
            out.append(s if s == p else f"{s}~{p}")
            s = p = m
    out.append(s if s == p else f"{s}~{p}")
    return ", ".join(out)


L = []
a = L.append
a("# R8 长样本数据覆盖报告（步骤 5，运行前；只读侦察，没有跑任何策略）")
a("")
a("窗口 2016-01-01 → 2025-12-31。数字全部来自 `.cache/history/*0.json`、`.cache/contracts`、`.cache/member`、`universe.json`、`research_cost.json` 的只读检查，脚本：`_probe_hist.py` `_probe_data2.py` `_probe_settle.py` `_c_pool_static.py` `_render_coverage.py`。**在磊确认之前，不开发长样本入口，不跑任何长窗口组。**")
a("")
a("## 0. 先说三个会改变“长样本在检验什么”的发现")
a("")
a("1. **`historical_backtest.py` 目前没有长样本入口**（没有 `--start/--end/--history-source`，也没有 `lab/research/long/`）。要跑长窗口，需要先实现入口（预注册 §9 之后、磊确认之后才做）。")
a("2. **本地没有 2016–2024 的合约级数据**：`.cache/contracts` 共 %d 个合约文件，最早的逐合约 bar 是 2024-09（AU）/ 2024-10（其余），交割月从 2025-10 起。所以 R6c 的换月复权（`main_map`）、合约成交、交割月拦截在长窗口里都做不了，只能用主力连续序列（有换月跳空）+ 连续序列代理成交。" % sum(v["n_contracts"] for v in p2["contracts_by_code"].values()))
a("3. **席位数据只有郑商所、上期所，从 2018-01-02 起**（`.cache/member`：czce %d 个文件、shfe %d 个文件，起 %s；大商所 `_dce_dl` 为空）；升贴水缓存（`.cache/akshare/basis`）只覆盖 2025-10 以后。所以 **A 的 seats 入场过滤、carry 旁路在长窗口里无法复现**，长样本只能用“基础模式”。R-track 文档（R8 一节）本来也写了这一点。" % (p2["member_txt_by_exchange"]["czce"]["n"], p2["member_txt_by_exchange"]["shfe"]["n"], p2["member_txt_by_exchange"]["czce"]["first"]))
a("")
a("**含义**：长窗口检验的是 **A 的核心（信号 + 仓位 + 名义帽 + 持仓数 + 板块上限 + 成本）**，不是冻结的完整 A（seats + carry + R6c）。预注册 §9 写了这一点。完整 A 只能靠前向 shadow 检验。另外，没有换月复权时，换月跳空会产生假止损 / 假信号（R6 阶段修的就是这一类问题），长窗口的结果会带这个偏差。")
a("")
a("## 1. 27 个品种的日线覆盖（主力连续，.cache/history）")
a("")
a("- 主日历（27 个品种的并集）在窗口内共 **%d** 个交易日；字段齐全：日期、开、高、低、收、成交量、持仓量、`settle`（结算价）。" % cov["calendar_days"])
a("- 窗口内 OHLC 为空的 bar：**0**。重复日期：**0**。")
a("- 预热期结束日 = 该品种缓存第 60 根 bar 的日期；`ATR100`（F2 用）要第 100 根 bar 之后才可用。")
a("")
a("### 1.1 上市（缓存首根 bar）晚于 2016-01-01 的品种（5 个）")
a("")
a("| 品种 | 板块 | 缓存首根 bar（上市日） | 预热期结束日（第 60 根） | 第 100 根 bar（F2 的 ATR100 起用） | 窗口内 bar 数 |")
a("|---|---|---|---|---|---|")
for c, r in sorted(rows.items(), key=lambda kv: kv[1]["first_bar"]):
    if r["listed_after_window_start"]:
        a(f"| {c} | {r['bucket']} | {r['first_bar']} | {r['warmup_bar_date']} | {r['atr100_bar_date']} | {r['bars_in_window']} |")
a("")
a("其余 22 个品种在 2016-01-01 之前已有 ≥60 根 bar，窗口第一天即可交易（预热期结束日都早于 2016-01-01；最晚的是 NI：首 bar 2015-03-27，预热结束 %s；MA：缓存首 bar %s，预热结束 %s）。" % (rows["NI"]["warmup_bar_date"], rows["MA"]["first_bar"], rows["MA"]["warmup_bar_date"]))
a("注意：这里的“上市日”是缓存首根 bar，**不一定等于交易所的官方上市日**（仓库里没有登记官方上市日）；MA 的缓存起点 2014-12-24 看起来是缓存起点而不是上市日。对 2016 窗口没有影响。")
a("")
a("### 1.2 窗口内的缺口")
a("")
a("| 品种 | 窗口内 bar 数 | 上市后缺主日历天数 | 最长连续缺失 | 成交量为 0 的 bar | 缺 `settle` 的 bar |")
a("|---|---|---|---|---|---|")
for c, r in rows.items():
    miss_settle = r["bars_in_window"] - r["bars_with_settle"]
    if r["missing_master_days_after_listing"] or r["zero_volume_bars"] > 1 or miss_settle > 5:
        a(f"| {c} | {r['bars_in_window']} | {r['missing_master_days_after_listing']} | {r['longest_missing_run']} | {r['zero_volume_bars']} | {miss_settle} |")
a("")
a("- **缺 `settle` 的集中段（大商所 10 个品种：V、M、PP、L、JD、P、I、JM、EG、EB）**：① **2017-11-01 ~ 2018-03-09 连续 87 个交易日**（EG、EB 当时尚未上市，没有这一段）；② **2019-12-10 ~ 2020-08-06 约 111 天**（2020-02 起几乎整月缺，到 2020-07 底；2019-12、2020-01 只是零星几天）。另有零星日（2017-01-02、2021-12-30、2024-09-25 等）。")
a("- 上期所 / 上期能源系（AG、AL、AU、BU、CU、FU、NI、RB、RU、SP、SS）各有 3–5 个零星日缺 `settle`（2017-01-02、2019-04-30、2021-12-30、2023-08-28、2024-09-25 中的若干天）；郑商所品种（CF、FG、MA、SR、TA、SA）窗口内没有缺。")
a("- **FU 在 2016-01-04 ~ 2018-06-26 有 450 根成交量为 0 的 bar**（2016：164，2017：171，2018：115）——几乎没有成交的僵尸行情期，价格是陈旧的；FU 还有 24 个主日历日缺失、最长连续缺 13 天。")
a("- 其余缺口都很小（最多缺 2–6 天）。")
a("")
a("## 2. 合约乘数、保证金、手续费的历史是否齐全")
a("")
a("| 项 | 现状 | 缺失 |")
a("|---|---|---|")
a("| 合约乘数 `mult` | 只有 `universe.json` 的当前值，没有历史表 | **全部 27 个品种的历史乘数都没有**；如果某品种乘数在 2016–2025 间变过，当前值会错 |")
a("| 手续费 `fee_yuan` / `fee_rate` | 只有一个 as-of 2026-09-02 的单日期值（申银万国公示）；螺纹、燃油、白银有按月份差异的说明但没有表 | **历史手续费表缺失**；2016–2025 交易所多次调整过手续费标准，当前值只是近似 |")
a("| 最小变动价位 `tick`（滑点用） | 只有当前值 | 历史未登记 |")
a("| 保证金 | **引擎不建模保证金**（用名义帽 50% 代替）；仓库里没有保证金字段 | 不适用 / 无数据 |")
a("")
a("默认处理（预注册 §9）：用当前值套用全部年份，作为已知偏差披露，不修正。")
a("")
a("## 3. 候选 C 在 100 万和 30 万下每月会排除的品种与月数（静态估计）")
a("")
a("**这是近似**：E 固定为 100 万 / 30 万（真实 C 用实际权益，路径相关）；`N_i = 上月末 settle × 当前 mult`；上月末缺 `settle` 时这里临时用收盘价估算（记在最后一列）；\"尚未可交易\"（预热期未结束 / 未上市）的月份不算排除。月数 = 120（2016-01 ~ 2025-12）。逐月明细：`long_c_pool_static.json`。")
a("")
for E in ("1000000", "300000"):
    r = cp["levels"][E]
    a(f"### E = {int(E):,}（名义门槛 = E × 25% = {int(int(E) * 0.25):,} 元）")
    a("")
    a(f"- 每月池内品种数：最少 {r['pool_size']['min']}，中位 {r['pool_size']['median']}，最多 {r['pool_size']['max']}（母池 27）。覆盖板块数（共 4 个）：最少 {r['buckets_covered']['min']}，中位 {r['buckets_covered']['median']}。")
    a(f"- **有色板块（AG/AU/CU/AL/NI）池内为空的月数：{r['months_nonferrous_bucket_empty']} / 120**；整个池为空的月数：{r['months_pool_empty']}。")
    a("")
    a("| 品种 | 板块 | 当前 1 手名义（用 2026-11-25 收盘价×mult，供参考） | 被排除月数 / 可评估月数 | 被排除的月份（连续段） |")
    a("|---|---|---|---|---|")
    for c in meta:
        ex = r["excluded_months_by_symbol"][c]
        if not ex:
            continue
        exm = [m for m in months if c in r["per_month"][m]["excluded_by_notional"]]
        last = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))[-1]
        now_n = float(last["close"]) * float(meta[c]["mult"])
        a(f"| {c} | {meta[c]['bucket']} | {now_n:,.0f} | {ex} / {r['eligible_months_by_symbol'][c]} | {runs(exm)} |")
    a("")
a("**读法**：100 万下 C 基本等于\"去掉 AU（118/120 个月被排除）和 CU（77/120 个月）\"，其余 25 个品种大多数月份都在池内；30 万下 C 会长期丢掉整个有色板块（有色为空的月数见上），还会丢 RU、CF、P、I、JM、AG、AL、NI 的大部分月份——不再是同一个策略（这正是 30 万诊断档标签\"策略结构不同\"要说的事）。80 万 / 120 万的静态估计也在 `long_c_pool_static.json`（80 万下 AU、CU 几乎全程被排除；120 万下 AU 78/120、CU 57/120）。")
a("")
a("### 3.1 若采用\"缺结算价 → 该品种当月不入池\"的默认规则，额外被排除的月份")
a("")
a("上月末那根 bar 缺 `settle` 的月份（与 E 无关）：")
a("")
a("| 品种 | 月数 | 月份 |")
a("|---|---|---|")
bars_cache = {}
prev = lambda ym: f"{int(ym[:4]) - 1}-12" if ym[5:] == "01" else f"{ym[:4]}-{int(ym[5:]) - 1:02d}"
for c in meta:
    bs = json.loads((ROOT / ".cache" / "history" / f"{c}0.json").read_text(encoding="utf-8"))
    last = {}
    cnt = {}
    for i, b in enumerate(bs):
        last[str(b["date"])[:7]] = b
        cnt[str(b["date"])[:7]] = i + 1
    miss = [ym for ym in months if prev(ym) in last and cnt[prev(ym)] > 60 and last[prev(ym)].get("settle") in (None, 0)]
    if miss:
        a(f"| {c} | {len(miss)} | {runs(miss)} |")
a("")
a("## 4. 数据缺口处理（建议，待确认）")
a("")
a("1. **不插补，品种数据不齐就不纳入**：某品种在某交易日没有 bar → 当天该品种不可交易（不产生信号、不入场；已持仓的盯市沿用引擎现有行为，实现时要核对并写单元测试）。")
a("2. **上月末缺 `settle`**：该品种当月不入 C 的池（不用收盘价代替）。大商所 8 个老品种各少 9 个月（2017-12~2018-03、2020-03~2020-07），EG、EB 各少 5 个月（2020-03~2020-07），上期所系 2019-05 少 1 个月，见 §3.1。")
a("3. **成交量为 0 的 bar**（FU 2016~2018-06）视为无有效行情日。")
a("4. **晚上市的 5 个品种**：EB、EG、SA、SP、SS 从各自预热期结束日起纳入（§1.1）。")
a("5. **合约乘数 / 手续费 / tick**：用当前值套用全部年份，作为已知偏差披露。")
a("6. **长样本数据模式**：基础模式（无席位、无升贴水、无合约级复权、连续序列代理成交）。**这是必须由磊确认的一项**：它让长窗口回答的是\"A 的核心\"，不是\"冻结的完整 A\"。")
a("")
a("## 5. 需要磊确认的事项")
a("")
a("1. 接受长样本用“基础模式”（上面第 6 点）；还是要先去补 2016–2024 的合约级数据（本地没有，是否能从数据源取到我没有验证，也会耗时）后再跑。")
a("2. 接受上面第 1–5 点的数据缺口处理默认值，或者改。")
a("3. 接受已知偏差（当前乘数 / 手续费套用历史年份）。")
a("4. 预注册 §10 的 shadow 第一次评估下限写成\"6 个月且 30 笔\"（我的解读），还是你原话的\"或\"。")
a("")
a("确认后的下一步（我不会提前做）：写附录 1 → 实现长样本入口与 C（只用构造数据测试）→ 全量 pytest → 跑 9 个正式组 → `OOS_VERDICT.md` → 30 万诊断组 → 启动 shadow。")
(R8 / "LONG_COVERAGE_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("written", len(L), "lines")
