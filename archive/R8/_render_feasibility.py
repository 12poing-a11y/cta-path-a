# -*- coding: utf-8 -*-
"""Render archive/R8/LONG_FEASIBILITY_REPORT.md from the read-only feasibility JSONs + manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

R8 = Path(__file__).resolve().parent
RAW = R8 / "raw_contract"
res = json.loads((R8 / "feasibility_results.json").read_text(encoding="utf-8"))
diag = json.loads((R8 / "feasibility_diag.json").read_text(encoding="utf-8"))
extra = json.loads((R8 / "feasibility_extra.json").read_text(encoding="utf-8"))
mult = json.loads((R8 / "mult_daily_check.json").read_text(encoding="utf-8"))
uni = json.loads((R8.parents[1] / "universe.json").read_text(encoding="utf-8"))
meta = {u["code"]: u for u in uni["symbols"]}
ps, roll = res["per_symbol"], res["roll"]
xv = res["xval"]["fields"]; XP = res["xval"]["pairs_by_exchange"]

EXN = {"shfe": "上期所 SHFE（kx{date}.dat）", "czce": "郑商所 CZCE（FutureDataDaily.txt）", "dce": "大商所 DCE（官网日行情接口，经浏览器同源会话抓取）"}
man = {}
for ex in ("shfe", "czce", "dce"):
    m = json.loads((RAW / f"MANIFEST_{ex}.json").read_text(encoding="utf-8"))
    ok = {d: r for d, r in m.items() if r.get("status") == "ok"}
    agg = hashlib.sha256("\n".join(f"{d}:{ok[d]['sha256']}" for d in sorted(ok)).encode()).hexdigest()
    st = {}
    for r in m.values():
        st[r.get("status")] = st.get(r.get("status"), 0) + 1
    fu = sorted(r.get("fetched_utc", "") for r in m.values() if r.get("fetched_utc"))
    man[ex] = {"n": len(m), "status": st, "agg": agg, "first": fu[0] if fu else "", "last": fu[-1] if fu else "", "bytes": sum(r.get("bytes", 0) or 0 for r in ok.values())}

codes = sorted(meta)
SPEC_SEEN = {"I", "JM", "M", "P", "EG", "EB", "JD", "L", "V", "PP", "SR", "CF", "MA"}
L = []
w = L.append
w("# R8 长样本数据可行性报告（只读，未跑任何策略）")
w("")
w("> 分支 `r8-equity-filter`（本地）。范围：2016-01-04 → 2025-12-31，27 个品种。本报告只回答\"数据能不能撑起长样本\"；**未写附录 1、未实现入口、未跑任何回测**；正式层 / 规则锁 / `historical_backtest.yml` 未动。")
w("> 原始数据独立缓存于 `archive/R8/raw_contract/`（`.gz` 不入库，仅入库清单与哈希）；解析与分析脚本、结果 JSON 同目录。")
w("")
w("## 0. 结论速览（先给判定，再给证据）")
w("")
w("- **按你写死的标准，\"27 个全部满足\"不成立**，需要你决定（见 §8）。不满足点只有两处：")
w("  1. **FU（燃料油）**：默认起点 2016-01-04 时主力可确定占比仅 **79.77%**（2016–2018-06 是旧 180CST 合约，官方日成交量中位数仅 8–12 手，缓存里 450 个零成交 bar）。按你确认的缺口规则把起点移到零成交结束后 +60 根预热 = **2018-10-16**，占比 **99.89%**，达标。")
w("  2. **\"每个交易日都能确定主力\"的字面读法**：只有 SA 一个品种做到 0 天未识别；其余 26 个品种有 1–12 个未识别日（占比 ≤ 0.82%，EB 最多 12 天），主因是缓存连续序列在 9 个共同日期上的收盘价与任何官方合约都对不上（缓存毛刺 / 上游序列差异），不是官方逐合约数据缺失。按\"≥99% 容忍\"的读法 26/27 通过（FU 需移起点）。**字面读法与容忍读法请你二选一**。")
w("- **乘数**：2016–2025 唯一一次真实变更是 **FU：50 吨/手 → 10 吨/手，2018-07-16 生效**。数据反推（官方成交额）独立复现了这个台阶。FU 的有效起点 2018-10-16 晚于变更日，因此**样本内无需分段**；其余 26 个品种逐日反推乘数与 `universe.json` 一致（逐日比值落在 0.9958~1.0075 之内，仅 CF 在 2022-08-03 有 1 天偏离 2.5%）。")
w("- **缓存连续序列未复权**（简单拼接）；换月日跳空中位数 0.51 ATR14、P90 2.81、最大 17.34（JD），> 1 ATR 的有 417/1248 次（33%）。引擎的 R6c 用逐合约数据做无换月收益，所以长样本必须依赖本次抓到的逐合约数据。")
w("- **与本地逐合约 bar 交叉验证**：价格与 settle 基本逐位一致（共 51,507 对）；volume / OI 有 0.8–3.8% 的行存在差异且**方向一致（本地 ≤ 官方）**，不能算\"完全无偏差\"，见 §4。")
w("")
w("## 1. 数据源、抓取日期、文件哈希")
w("")
w("每个交易日一个交易所级文件，覆盖该所全部品种；按品种的归属见下表。哈希口径：SHFE/CZCE = 原始响应字节的 sha256；DCE = 浏览器抓取后保存的规范化 JSON 的 sha256（官网对脚本请求返回 412 JS 挑战，未绕过，采用真实浏览器会话同源请求）。逐文件哈希见 `raw_contract/MANIFEST_*.json`；此处给\"逐日哈希拼接的聚合 sha256\"。")
w("")
w("| 交易所 | 数据源 | 日文件数 / 状态 | 抓取时间(UTC) | 聚合 sha256 | 品种 |")
w("|---|---|---|---|---|---|")
for ex in ("shfe", "dce", "czce"):
    m = man[ex]
    syms = ", ".join(c for c in codes if ps[c]["exchange"] == ex)
    w(f"| {ex.upper()} | {EXN[ex]} | {m['n']} / {m['status']} | {m['first']} ~ {m['last']} | `{m['agg']}` | {syms} |")
w("")
w("- 所有品种一律来自交易所官网（第一优先），未使用 AKShare 等封装。每个品种的具体文件即该所的逐日文件（`raw_contract/<exchange>/<YYYYMMDD>.gz`），哈希见清单。")
w("- 日历：SHFE/CZCE 以 27 个缓存序列日期并集（2431 天）为主日历逐日抓取，各有 2 天返回 404（缓存日历中的幻影日 2017-01-02、2017-10-02，交易所当日无行情）；DCE 探测了 2016-01-01~2025-12-31 的全部工作日，179 天无行情（节假日，状态 empty）。官方有行情而缓存日历缺失的日期：" + ", ".join(res["official_trading_days_missing_from_cache_calendar"]) + "。")
w("- INE（能源中心）：本池无 INE 品种，未抓取。")
w("")
w("## 2. 预先写死的\"齐全\"标准与逐品种判定")
w("")
w("标准（看数据前已写死）：从起点（2016-01-01 或预热结束日）到 2025-12-31，同时满足 (a) 逐合约 OHLC+settle+volume+OI 齐全的交易日占比 ≥ 99%；(b) 每个交易日都能按引擎换月规则确定主力；(c) 重叠区间交叉验证无系统性偏差。")
w("")
w("操作化：(a) = 引擎主力合约当日的官方行 OHLC>0、settle>0、volume、OI 均存在的日占比；(b) = 用引擎 `build_main_map`（同一 1 tick 匹配规则，候选合约由 `delivery_rules` 日历给出）在官方逐合约数据上重算，未识别日数；**字面读法 = 0 天未识别；容忍读法 = (a) 已含的 ≥ 99%**。")
w("")
w("| 品种 | 所 | 起点 | 窗口交易日 | (a) 主力行齐全占比 | (b) 未识别日 | 任一合约齐全占比 | (a) | (b)字面 |")
w("|---|---|---|---|---|---|---|---|---|")
fu_new = diag["FU"]
for c in codes:
    s = ps[c]
    a = s["main_row_complete_share"]
    a_ok = a >= 0.99
    mark_a = "✓" if a_ok else "✗"
    row_start, row_days, row_share, row_unid = s["start"], s["trading_days_in_window"], a, s["unidentified_n"]
    extra_note = ""
    if c == "FU":
        extra_note = f"（移起点至 {fu_new['start_after_60_warmup_bars']}：{fu_new['main_identified_from_new_start']}/{fu_new['days_from_new_start']} = {fu_new['share']*100:.2f}% ✓，未识别 {fu_new['days_from_new_start']-fu_new['main_identified_from_new_start']} 天）"
    w(f"| {c} | {s['exchange'].upper()} | {row_start} | {row_days} | {a*100:.2f}%{extra_note} | {row_unid} | {s['any_contract_complete_share']*100:.2f}% | {mark_a} | {'✓' if row_unid == 0 else '✗'} |")
w("")
w(f"- (a) 默认起点：26/27 通过（EB 最窄 99.18%）；FU 79.77% 不通过，按你确认的缺口规则（零成交结束后第一根有效 bar 2018-07-16 → +60 根 = 2018-10-16）后 99.89% 通过。")
w(f"- (b) 字面读法：仅 SA 通过；26 个品种有 1–12 个未识别日。未识别原因（去掉 FU，共 {diag['unidentified_total_excluding_FU']} 个品种日）：与最近官方合约收盘差 ≤3 tick {diag['unidentified_summary']['categories_excluding_FU']['<=3 ticks']}、3–20 tick {diag['unidentified_summary']['categories_excluding_FU']['3-20 ticks']}、> 20 tick {diag['unidentified_summary']['categories_excluding_FU']['>20 ticks']}。有 ≥5 个品种同日出现的共同日期：{', '.join(diag['unidentified_dates_shared_by_>=5_symbols'])}——说明主要是缓存连续序列自身在这些日子的毛刺，而非官方数据缺失。这些日子引擎会走既有的 fallback 路径（R6c `fallback` 标记）；长样本中 fallback 日占比已含在上面的未识别日数里。")
w("- 分年最低主力占比：2020/2021 年个别品种略低（P 2020 = 97.53%，EB 2020 = 97.94%，PP/L 2021 = 97.94%），但全期均 ≥ 99.18%（FU 另论）。")
w("- 日历与幻影日：缓存日历含 2 个无行情幻影日（2017-01-02、2017-10-02，已从窗口剔除）；2019-04-22 官方有行情但缓存缺失。")
w("")
w("## 3. 缓存主力连续序列：是否复权")
w("")
w("`.cache/history/{CODE}0.json`（新浪主力连续）**未复权，是简单拼接**：在引擎匹配日上，连续序列收盘价与当日主力合约自身收盘价逐 tick 对得上（99.5–100% 的日子），说明换月处没有做价差平移；换月日会出现原样的合约间价差跳空。因此跳空必须由引擎 R6c 的无换月收益（同合约前收计算 ret/tr/atr14）来消除，这依赖逐合约数据——本次抓取的官方逐合约数据正是它的输入。")
w("")
w("## 4. 与本地逐合约 bar 的交叉验证（2024-09-01 ~ 2025-12-31 重叠）")
w("")
w("| 所 | 配对数 | open 不一致 | high | low | close | settle | volume | OI |")
w("|---|---|---|---|---|---|---|---|---|")
for ex in ("shfe", "czce", "dce"):
    x = xv[ex]
    def cell(k):
        v = x[k]
        return f"{v['mismatch']}（最大绝对 {v['max_abs']:g}，最大相对 {v['max_rel']*100:.2f}%）"
    w(f"| {ex.upper()} | {XP[ex]} | " + " | ".join(cell(k) for k in ("open", "high", "low", "close", "settle", "volume", "oi")) + " |")
w("")
vo = diag["vol_oi_mismatch"]
w("- 官方独有/本地独有的合约-日：本地独有的合约-日 0 条，且 359 个在窗口内有 bar 的本地合约全部能在官方数据里找到；重叠区间内官方独有的合约-日 0 条；SHFE 另有 3 条 settle=0 不参与比较。")
w("- **价格与 settle**：SHFE/CZCE 的 OHLC、settle 除 2024-09-25 一天（BU2606 low/close、AU2510 close 共 3 行）外**逐位一致**；DCE 的 95 行价格不一致全部是**官方 open/high/low=0 的薄成交合约行**（官方成交量很小、1–200 手量级，但 OHLC 缺，例如 EB2510 2025-10-22；此时本地 bar 的 OHLC 是别处补出来的值）——这类行在引擎里因 OHLC>0 条件不会进入 bundle。DCE settle 零不一致。")
w("- **volume / OI**：不一致行占比 SHFE " + f"{vo['shfe:volume']['local_lower']/xv['shfe']['volume']['n']*100:.1f}%" + "，CZCE " + f"{vo['czce:volume']['local_lower']/xv['czce']['volume']['n']*100:.1f}%" + "，DCE " + f"{vo['dce:volume']['local_lower']/xv['dce']['volume']['n']*100:.2f}%" + "。volume **全部是本地 ≤ 官方（local_higher = 0）**，多数是 ±1 手、少数大偏差（最大相对 54–96%，集中在少数日期，如 2025-12-16/09-16/11-18），OI 两个方向都有。这是**单向偏差**，推测是本地快照在个别日抓取时刻早于交易所终值；量级小但方向一致，按字面\"无系统性偏差\"不能判通过。")
w("- 对策略的影响面（静态检索，非运行结果）：`historical_backtest.py` 中 bar 的 volume 仅在约 1182 行（climax 类）被读取，该文件未读取 `open_interest` 字段；`research/execution/contract_pack.py`、`research/data_quality/masks.py` 另有 volume/OI 用法，我没有逐一核对，附录 1 之前应再核。建议 **2016–2025 全部用官方数据、不与本地快照混用**（本地快照只服务 2026 窗口）；接缝处的差异集中在少数行（不一致行占比 ≤ 3.8%）。**是否接受请你决定**。")
w("")
w("## 5. 换月日数与跳空（ATR14 单位）")
w("")
rp = res["roll_pooled"]
w(f"定义：换月日 = 引擎主力合约相对前一日变化的日子（窗口内）；跳空 = 换月前一日新旧主力收盘价之差 / 前一日缓存序列 ATR14；两合约前一日均有成交 bar 才计入。汇总（{rp['roll_days_measured']} 次可测）：**中位数 {rp['median']:.2f} ATR，P90 {rp['p90']:.2f}，最大 {rp['max']:.2f}，> 1 ATR 共 {rp['gt_1atr']} 次（{rp['gt_1atr']/rp['roll_days_measured']*100:.0f}%），> 0.5 ATR 共 {rp['gt_0_5atr']} 次**。")
w("")
w("| 品种 | 换月日 | 可测 | 中位数 | P90 | 最大 | >1 ATR |")
w("|---|---|---|---|---|---|---|")
for c in codes:
    r = roll[c]
    f = lambda v: "-" if v is None else f"{v:.2f}"
    w(f"| {c} | {r['roll_days']} | {r['roll_days_with_gap_measured']} | {f(r['gap_atr14_median'])} | {f(r['gap_atr14_p90'])} | {f(r['gap_atr14_max'])} | {r['gap_gt_1atr']} |")
w("")
w("含义：未复权连续序列在换月日平均夹带约半个 ATR 的虚假跳空，P90 近 3 ATR（JD、RU、M 最严重）；长样本必须使用 R6c 无换月收益而不能直接用缓存连续收盘价。")
w("")
w("## 6. 乘数变更核对（2016–2025）")
w("")
w("方法：(1) 交易所公告检索；(2) **用交易所自己公布的成交额反推乘数**：隐含乘数 = 成交额 /（成交量 × 结算价）÷ `universe.json` 乘数。DCE/CZCE 用逐合约成交额汇总，SHFE 用 `o_curproduct` 品种级成交额（亿元，2016 起各年均有）。逐日检查（成交量 ≥ 2000 手的日子），结果见 `mult_daily_check.json`。")
w("")
w("| 品种 | universe 乘数 | 2016–2025 是否变更 | 变更日期 | 出处 | 逐日反推比值(min~max) | 偏差>2%的天数 | 检查天数 |")
w("|---|---|---|---|---|---|---|---|")
for c in codes:
    m = mult[c]
    if c == "FU":
        chg, dt, src = "**是：50 吨/手 → 10 吨/手**", "**2018-07-16**（保税380挂牌；旧180合约 2018-06-26 起终止交易）", "上期所 2018-06-26 公告《燃料油期货合约及业务细则修订》（[中证网](https://www.cs.com.cn/zzqh/201806/t20180627_5830035.html)、[期货日报转载](https://www.shfe.com.cn/content/2018-FU380/mtbd2.html)）"
    elif c == "AU":
        chg, dt, src = "否", "-", "上期所 2019-12-02 黄金合约修订案明确交易单位 1000 克/手（[新浪财经](https://finance.sina.cn/futuremarket/qsyw/2019-12-02/detail-iihnzahi4806231.d.html?vt=4)）；数据反推全程 1.000"
    else:
        chg, dt, src = "否（未检索到变更公告；数据反推未见台阶）", "-", ("现行规格表（DCE/CZCE 品种参数汇总）与 universe 乘数一致；另有数据反推" if c in SPEC_SEEN else "未检索到公告；仅数据反推")
    extra_fu = "（2016-01~2018-05 另测：品种级反推 = 50.0，2018-07-16 起 = 10.0，逐日复现台阶）" if c == "FU" else ""
    w(f"| {c} | {meta[c]['mult']:g} | {chg} | {dt} | {src} | {m['ratio_min']:.4f}~{m['ratio_max']:.4f}{extra_fu} | {m['days_dev_gt_2pct']} | {m['days_checked']}（{m['first']}~{m['last']}） |")
w("")
w("- **FU 分段规则对长样本的影响**：2016-01 ~ 2018-06 乘数 50（旧 180CST 合约，几乎零成交），2018-07-16 起 10。FU 有效起点 = 2018-10-16 > 变更日，**样本内全程 10，无需分段**。若你日后放宽 FU 起点才需要按日期分段。")
w("- CF 2022-08-03 有 1 天隐含乘数偏离 2.5%（成交额口径噪声，非变更）。其余品种逐日比值全部在 0.9958~1.0075 之内（最大偏离 0.75%，TA）。")
w("- **这一节的证据边界**：公告出处只对 FU、AU 逐条取得；其他 25 个品种我只检索到\"无变更\"的间接材料（现行规格表、DCE 2025-01-24 公告只改**交割单位**——J/JM/I 交割单位下调，**交易单位未变**；CZCE 白糖 2018-06-07 修订案交易单位仍 10 吨/手），**未逐品种通读 25 份合约修订史**。主证据是交易所自己公布的成交额 ÷（量×价）逐日检查，它对乘数台阶非常灵敏（FU 的 5 倍台阶被精确复现）。如果你要求逐品种出公告，需要追加一轮查证。")
w("")
w("## 7. 缺口处理相关统计（你确认的两处修改）")
w("")
sr = extra["settle_recovery"]
w(f"- **C 的品种池，上月末缺 settle 用上月末 close 替代**：2016–2025 共 {sr['eligible_symbol_months']} 个品种月，缓存 settle 缺失 **{sr['cache_settle_missing_symbol_months']} 个**（即会被 close 替代的品种月数）。其中 {sr['recoverable_from_official']} 个其实可从官方主力合约的 settle 直接补回；{len(sr['not_recoverable'])} 个补不回（均为 2019-04-30 的 " + ", ".join(x[0] for x in sr["not_recoverable"]) + "，当日主力未识别）。按你的指令仍用 close 替代；是否改成\"官方 settle 优先、close 兜底\"见 §8。")
w(f"- **零成交 bar 同时排除出指标计算**：缓存里 FU 在 2016–2018 有 {diag['FU']['cache_FU_zero_volume_bars_2016_2018']} 个零成交 bar（最后一个 {diag['FU']['last_zero_volume_bar_in_cache_excl_2017-01-02']}，2017-01-02 为幻影日）；FU 起点 = 零成交结束后第一根有效 bar（{diag['FU']['first_valid_bar_after']}）+ 60 根预热 = **{diag['FU']['start_after_60_warmup_bars']}**。官方 FU 品种日成交量中位数：2016 = 8 手、2017 = 12 手、2018 = 685,084 手。其余品种零成交日见 `feasibility_results.json`（`cache_zero_volume_days`，每品种 ≤ 3 天）。")
w("- 晚上市品种起点（上市 + 60 根预热）：" + "，".join(f"{c} {ps[c]['start']}" for c in codes if ps[c]["start"] != "2016-01-04") + "。")
w("- 费用 / 最小变动价位用当前值（已知偏差，披露）：历史上这些参数有过调整，会让早期样本的成本偏离真实；保证金不建模。")
w("")
w("## 8. 需要你决定的事项（我不会替你定）")
w("")
w("1. **\"每日可确定主力\"取字面读法还是 ≥99% 容忍读法？** 字面读法下仅 SA 一个品种过关，27 个\"齐全\"无法成立；容忍读法下 26/27 过关 + FU 移起点后过关 = 27/27。")
w("2. **FU**：接受起点 2018-10-16（样本较短 ≈ 7.2 年，之前整段排除）；还是剔除 FU？")
w("3. **volume/OI 单向偏差**：接受\"2016–2025 全用官方、不与本地混用\"？还是要求先补齐本地快照差异？")
w("4. **settle 缺失月**：保持你指定的\"上月末 close 替代\"（91 个品种月），还是改为\"官方 settle 优先、close 兜底\"（可少替代 87 个，仅 4 个仍用 close）？")
w("5. **乘数证据强度**：接受\"FU 有公告 + 其余数据反推无台阶\"，还是要逐品种公告出处（需追加一轮查证）？")
w("6. **整体降级**：若不接受以上任一点，是剔除个别品种，还是整个长样本降级为诊断用。")
w("")
w("## 9. 产物与边界")
w("")
w("- 清单与哈希：`archive/R8/raw_contract/MANIFEST_{shfe,czce,dce}.json`；原始 `.gz` 仅本地（`.git/info/exclude`），不入库。")
w("- 抓取与解析：`fetch_contract.py`、`ingest_dce.py`、`contract_loader.py`；分析：`analyze_feasibility.py`、`diag_feasibility.py`、`extra_feasibility.py`、`mult_daily_check.py`、`_fu_mult_check.py`；结果：`feasibility_results.json`、`feasibility_diag.json`、`feasibility_extra.json`、`mult_daily_check.json`。")
w("- 边界：未跑任何策略、未写 `paper_book`、未动正式层 / 规则锁 / `historical_backtest.yml`；未写附录 1；未实现入口；未跑长样本。")
(R8 / "LONG_FEASIBILITY_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("written", len(L), "lines")



