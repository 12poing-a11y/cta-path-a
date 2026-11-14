# CTA Path-A 研究台 · 完整功能说明（评估用）

**仓库**：`cta-path-a`  
**性质**：中国商品期货 CTA 纸面验证 + Streamlit 研究台  
**边界**：只记账、不下单；研究层与正式层隔离  
**说明日期**：2026-11-15  
**用途**：供第三方评估能力边界、数据口径、正式/影子分层，不构成投资建议

---

## 1. 一句话定位

在固定规则下，对国内商品主力连续做 **日频 Path-A 纸面交易**，用 **GitHub Actions 工作日 15:30** 自动拉数、出信号、可选写 Notion；本机 Streamlit **研究台**叠加多策略对照、席位/情绪/期权/实验室等观察页。任何 Research / Shadow 模块 **默认不得改正式开仓参数**。

---

## 2. 三层架构

| 层 | 职责 | 可否改正式仓 |
|----|------|--------------|
| **正式 Path-A** | L1 信号、组合帽、`paper_book` 模拟仓、周/年回测 KPI | 是（唯一执行口径） |
| **研究台 Desk** | 可视化、对照、旁路提示、实验室只读面板 | 否（只读展示） |
| **Shadow / Lab** | 情绪、LSP、ML、消融、影子归因、NPD 等 | 否（不计分、不进 `paper_book`） |

**正式参数 SSOT**

- `universe.json`：品种池、权益、风险%、组合上限、动量门槛、旁路开关  
- `execution_rules.json`：止损 **0.8×ATR**、止盈 **2R**；历史档位进 `archived_params`  
- `entry_filter=seats`：席位只确认/拦住 20/60 同向信号，**不开反向单**

---

## 3. 正式策略规则（Path-A / L1）

1. **信号**：主力近 20 日与近 60 日收益同向 → 顺势；否则空仓；门槛默认 `|r20|≥4%`、`|r60|≥6%`  
2. **仓位**：`lots = floor(风险预算 / (ATR14 × 合约乘数))`；权益默认 ¥20 万、单笔风险 2%  
3. **组合**：最多 **3** 品种；总名义 ≤ 权益 **50%**；板块去重（`max_per_bucket=1`）；组合风险帽  
4. **入场过滤**：机构 → 外资 → 与「家人」对面反向；大商所无会员排名时可放行（有专用旁路）  
5. **成交口径（正式回测）**：T 日收盘算信号，**T+1 开盘成交**（`fill_price=next_open`）；席位/升贴水可见性滞后 1 个交易日  
6. **平仓**：止盈 `target` / 止损 `stop` / 趋势失效 `signal`  
7. **成本**：每边 1 跳滑点 + 客户手续费（毛/净并列）

**正式旁路（不改 ATR、不切 `entry_filter`）**

- 升贴水极端：`|近次月 gap|≥1%` → 升水禁开多 / 贴水禁开空  
- 实验室软边：截面分位与拟开仓严重逆向 → 决策观望（缺数放行）  
- 多维波动过高 → 观望（研究旁路）

**当前正式成绩（评估时请以此为准）**

- 产物：`historical_backtest_latest.json`（`schema_version=cta-backtest-v13-tradability`）  
- 须与 `lab/research/validation/formal_scorecard_latest.json` 同次对齐  
- 窗口示例（seats / next_open，约 2025-12-23→2026-11-13，**混价锁死后**）：净约 **+5.0%**、净回撤约 **3.3%**、结论 **「继续L1」**  
- 混价污染旧成绩（−7.6%/DD20.5%）已否决；PBO 等为 Research 诊断，**不单独晋级**  
- 价格：合约成交与管理同基础；基差>3% 强制连续代理（`fill_series=mixed` / historical_roll）

---

## 4. 行情与席位数据

| 类型 | 主源 | 补洞顺序 | 备注 |
|------|------|----------|------|
| 日线（连续） | 新浪 `{CODE}0` | TqSdk → iFinD | 腾讯商品日 K **已弃用** |
| 精确合约 / 换月 | 新浪合约日 K | TqSdk → 扶摇 Fuyao（可选） | 无 Key 软跳过 |
| 会员持仓 | 东财 → 新浪 | 上期/郑商 txt、DCE zip | 标签用机构席，不用家人席冒充 |
| 分钟 15m/60m | AkShare | — | 技术/图表 |
| 期权 IV | AkShare 郑商所结算等 | — | Gamma / vol engine |

**重要口径**：信号、影子归因、多数回测默认基于 **主力连续合约**（`price_basis=continuous` / `CODE0`），不是评估人误以为的「全程真实交割月成交」。正式历史回测已尽量叠 front-month，缺口仍可能 continuous 代理。

---

## 5. 自动化（GitHub Actions）

| Workflow | 时间（北京） | 作用 |
|----------|--------------|------|
| CTA Daily | 工作日 ~15:30 | 拉数 → L1 报告 → paper 滚仓 → 技术分/情绪影子/仓单/vol/composite/影子归因 → 可选 Notion → commit 缓存 |
| CTA Weekly Backtest | 周六 ~09:00 | 周度回测 |
| CTA Historical Backtest | 周日 / 手动 | 一年正式回测 |
| Gamma 日采（可选） | 见 workflow | IV/Gamma 墙 |
| CI | PR/push | pytest 等 |

手机可只靠 Actions + Notion「交易参照」页；详见 `MOBILE.md`。  
Cron 可能延迟；国内假日仍可能触发。

**Secrets（评估环境依赖）**

| Secret | 角色 |
|--------|------|
| `TQ_USER` / `TQ_PASS` | 免费源不足时第一补洞 |
| `IFIND_AUTH_TOKEN` (+ backup) | 最终兜底日线 |
| `NOTION_TOKEN` | 信号 / 交易参照 / 流水 |
| `FUYAO_API_KEY` | 精确合约可选补洞 |

---

## 6. 研究台页面清单（Streamlit）

启动：`pip install -r requirements-desk.txt` → `streamlit run desk/app.py`  
导航 **仅渲染当前页**（避免全页重算）。

### 6.1 决策主路径（正式相关）

| 页面 | 功能 |
|------|------|
| **最终信号** | 纸面行动总表：建议开 / 持有 / 建议平 / 观望；综合日信号与模拟仓 |
| **日信号** | 全市场 L1 明细（方向、动量、席位、升贴水、手数、是否入选） |
| **决策** | 旁路与实验室 Gate 只读；升贴水 / 波动 / lab edge 等提示 |
| **席位板块** | 会员排名、机构净持仓变化、板块视图 |
| **技术分析** | 技术形态 / tech_score 快照 |
| **图表** | 品种 K 线与研究标注 |
| **概览对比** | 多策略净值/回撤叠加、健康度、本地代理模拟持仓、策略×指标消融表 |
| **状态评分** | 综合评分 / scoreboard；可挂实验室 Gate |

侧栏：**同步日报**（`git pull` Actions 产物；可选本机重跑 `daily_update`）；滚 `paper_book`。

### 6.2 结构 / 衍生品观察

| 页面 | 功能 |
|------|------|
| **情绪** | MDS+EHI 情绪袖套当日快照 + 行为金融旁路面板 |
| **期权机会** | 保护期权纸面机会（相对 paper 持仓或日信号候选） |
| **Gamma 结构** | Gamma 墙 / IV-OI 结构研究 |
| **套利观察** | 跨品种/期限等套利观察（研究） |
| **LSP 扫荡研究** | 流动性扫荡、真假突破条件概率 |
| **P4 轻量ML** | LightGBM/HistGBM 标签任务 OOS（Research only） |

### 6.3 影子 / 不计分（评估时务必标灰）

| 页面 | 功能 | 是否进正式仓 |
|------|------|--------------|
| **影子归因·品类胜率** | L1 同向 / 入选 / 情绪影子 → T+1/3/5 连续收盘回填；按策略×品类×品种胜率、平均收益、平均 R；样本 &lt;20 只展示不下结论 | 否 |
| **E1·情绪影子·不计分** | 历史情绪快照 vs 次日收益 | 否 |
| **E1·NPD影子·不计分** | 棉花新闻–价格背离进入日提醒 | 否 |

**明确不做 / 已搁置**

- 多时段盘中交易参照：交由外部观察（Grokbot/云电脑），本仓未合并  
- 预测归因 UI：后台或有产物，台面已搁置  
- 东证实盘条：不再挂自动抓取；归档在 `external/archive/`

---

## 7. 本地代理与观察袖套

命令：`python proxy_cta.py`  
产物：`external/strategies/proxy_*.json` + `desk/strategies/extra/`  
每条自带研究用 `final_positions` / `trade_log`，**与 Path-A `paper_book` 分离**。

| id | 说明 |
|----|------|
| `proxy_cwft` | 本地代理 · CWFT |
| `proxy_long_short_cwft` | 本地代理 · 多空 CWFT |
| `proxy_frontnext_st` | 本地代理 · 前后月 + ShortTrend |
| `proxy_observe_f_short_mom` | 观察袖套 · F+短动量（消融冒尖，建议帽 ≤10% 权益，影子） |

概览对比默认叠加：Path-A + 上述三代理（观察袖套可选手动加）。

挂新策略：产出含 `equity_curve` 的 JSON → `desk/strategies/extra/<id>.json` → 重启 Streamlit。

---

## 8. Notion / 手机交付

日报成功后可选同步：

- **日信号台账**（全市场明细）  
- **交易参照 brief**：当日建议开 / 持有 / 建议平 / 预警（评估人手机主看此页）  
- **建平仓流水** + 规则统计  

本地：`python notion_sync.py signals|brief|trades|annual`

---

## 9. 实验室与验证工具（Desk 外，评估相关）

| 模块 | 作用 | 晋级关系 |
|------|------|----------|
| `lab/` 因子面板 + IC/OOS | 日频因子与 Path-A 对照 | Gate 未过不改 `entry_filter` |
| `lab/validation` PSR/DSR/PBO/WF | 过拟合诊断 | 报告用，不单独晋级 |
| `scripts/strategy_indicator_ablation.py` | 策略×指标消融 | 研究 |
| `scripts/run_shadow_perf.py` | 影子归因台账 | 研究 |
| `historical_backtest.py` | 正式一年 KPI | 正式成绩唯一主源之一 |
| 数据质量双掩码 / 成本情景 | Base·Stress·Extreme | 见 `docs/UPGRADE_PLAN.md` |

升级阶段（摘要）：P0–P4 主路径与 A1–A3 已完成；正式结论仍为 **暂停**；A2 历史换月已做但覆盖非 100%。

---

## 10. 影子归因台账（新，评估关注点）

- 路径：`data/shadow_perf/ledger.jsonl` + `summary_latest.json`  
- 候选：Path-A 同向信号、Path-A 入选、情绪 MDS 影子多空  
- 归因：连续合约收盘 T+N 前瞻收益；有止损则算 R  
- 门槛：单格样本 **&lt;20** → 只展示、不下结论  
- 触发：日报 soft 步骤；可 `--backfill-history`  
- **不改** Path-A / `paper_book`

农产品等品类胜率同样基于 **连续合约** 回填，解读时勿当成实盘交割月成交统计。

---

## 11. 评估人建议检查清单

1. **边界**：能否清楚区分「正式暂停的 Path-A」与「影子/实验室热闹页面」？  
2. **KPI**：是否只认 `historical_backtest_latest.json` + formal scorecard，而不是 Desk 某页截图？  
3. **价格口径**：连续 vs 合约、next_open、mixed 缺口代理是否可接受？  
4. **席位数据**：东财/交易所覆盖与滞后 1 日是否可接受？  
5. **自动化**：无本机时 Actions + Notion 是否满足「每日可核验」？  
6. **依赖**：Tq / iFinD / Notion / Fuyao 缺省时的降级行为是否可接受？  
7. **治理**：Research 改参是否有人工闸门（Gate / scorecard / 不自动写 `execution_rules`）？  
8. **样本**：影子品类胜率样本量与「不下结论」规则是否足够防过读？

---

## 12. 明确非目标（当前版本）

- 实盘下单 / 券商柜台对接  
- 把 Shadow 胜率自动改正式参数  
- 多时段盘中 brief（外部观察中，未合并）  
- 东证等外部实盘曲线自动对齐为正式 KPI  
- 重型 ML（Transformer/RL）— 暂缓

---

## 13. 关键命令（复现）

```bash
pip install -r requirements.txt
pip install -r requirements-desk.txt
python daily_update.py
python paper_book.py
streamlit run desk/app.py
python lab/scripts/run_formal_scorecard.py   # 正式成绩对齐
python scripts/run_shadow_perf.py --backfill-history
python notion_sync.py brief
```

---

## 14. Disclaimer

研究与纸面验证用途，不构成投资建议。密钥勿提交仓库。评估结论应基于仓库内带 schema/版本戳的 JSON 报告，而非口头描述。
