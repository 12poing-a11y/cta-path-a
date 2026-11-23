# R14 期限结构（carry）独立袖套：细化方案

> 适用仓库：`D:\AI\cta-path-a`。本方案替换 `docs/UPGRADE_R_TRACK.md` 里 R14 的概要描述。
> 层级：**Research → Shadow**。在闸门通过并由磊签字之前，不写 `paper_book`、正式回测或 `execution_rules.json`。
> 前置：R6（复权）和 R8（长样本入口）完成后再开 K3 以后的步骤；K0–K2 可以和阶段 A 并行做，因为它们只碰数据层。

---

## 0. 为什么要先修数据：原型结果

我用项目现有的因子面板 `lab/data/factors/panel_daily.jsonl`（20 个主池品种，carry 从 2018 年起约 3.9 万条）先跑了一版原型，收益用复权近似后的主连计算，扣 1 跳滑点和手续费，回测区间 2019-01 到 2026-10：

| 方案 | 年化 | 最大回撤 | Sharpe | 正收益年份 |
|------|------|----------|--------|------------|
| K1 横截面 carry（原始 gap），周调仓 | −6.2% | −49.0% | −0.58 | 3/8 |
| K2 横截面 carry（按月份间隔年化） | −7.8% | −55.0% | −0.73 | 2/8 |
| K3 横截面基差动量 | −7.5% | −52.3% | −0.71 | 0/8 |
| K4 carry + 基差动量等权 | −8.5% | −57.2% | −0.82 | 2/8 |
| K5 时序 carry（年化 > 5% 才持仓） | −2.6% | −37.1% | −0.19 | 5/8 |
| 参照：27 品种 EWMAC 趋势 | +2.2% | −23.8% | 0.26 | 5/8 |

- 信号的预测力（横截面秩相关 IC，对未来 5 日收益）：carry 0.003（t≈0.2），基差动量 −0.018（t≈−1.4），基本是零。
- 与趋势的相关性：carry 和 EWMAC 趋势约 0.2，和 Path-A 约 0。**低相关这一点是对的**，只是收益没出来。

**这不能说明 carry 在国内无效**，因为面板的构造有 4 个缺陷，正好踩中了文献提醒过的坑（中国近月合约只占全市场持仓约 10%、成交约 3%，不能照搬近月做法，见 `docs/STRATEGY_EVIDENCE_REVIEW.md` 第三节）：

| 编号 | 缺陷 | 位置 | 证据 |
|------|------|------|------|
| D1 | 期限对用的是“到期最近的两个合约”，不是主力和次主力。近月常常是临近交割、没有流动性的合约 | `public_curve._build_one`：`alive` 按到期排序，取 `alive[0]`、`alive[1]` | 18.1% 的观测 \|gap\| > 5%；SA 39%、JD 33%、FG 30%、RU 22%、P 22% |
| D2 | 没有按两个合约的到期间隔年化，1 个月间隔（EB、FU、JD）和 4 个月间隔（MA、TA、SA）的品种混在一起排序 | `path_a_filters.carry_gap_pct` | 只是 `(next − front)/front × 100` |
| D3 | 基差动量跨合约切换计算：20 日前的 front 和今天的 front 可能是两个不同合约 | `lab/scripts/build_factor_panel._load_carry_rich` 第 77–87 行 | `f1/f0` 用的是按日期取的 front 价格序列 |
| D4 | 收益用主连计算。carry 的收益来自持有的合约向现货收敛和换月，主连（尤其是未复权的）没有正确体现 | R6 之前的全部回测 | 主连换月跳空，见 R6 |

另外有一个季节性问题：SA、FG、JD、RU 这类品种的月间价差很大一部分是季节性供需，不是风险溢价。所以方案里预先登记了一个去季节性的变体（S5）。

---

## 1. 目标与假设

- **假设 H1**：在主力和次主力这对可交易合约上，年化展期收益高（贴水）的品种，未来 1–4 周跑赢展期收益低（升水）的品种。
- **假设 H2**：按固定合约对计算的基差动量，对未来收益有正向预测力（Boons & Prado 的定义）。
- **用途**：一个和趋势低相关、独立的收益来源，用来降低组合回撤。它不替换 Path-A，也不作为 Path-A 的过滤器。

---

## 2. 刀序（K0–K7）

| 刀 | 名称 | 改动文件 | 依赖 | 产物 |
|----|------|----------|------|------|
| K0 | 分月合约历史日线库 | 新 `research/carry/contract_store.py`、`scripts/backfill_contract_history.py` | — | `.cache/contracts_hist/{SYM}.json` |
| K1 | 可交易期限曲线 | 新 `research/carry/curve.py` | K0 | `lab/data/carry/curve_{CODE}.parquet` 或 json |
| K2 | 持有合约收益指数 | 新 `research/carry/held_index.py` | K0、K1 | `lab/data/carry/held_{CODE}.json` |
| K3 | 信号（预登记 5 个） | 新 `research/carry/signals.py` | K1、K2 | 信号面板 |
| K4 | 袖套回测引擎 | 新 `research/carry/sleeve_bt.py` | K2、K3、R6 | `lab/research/carry/K4_*.json` |
| K5 | 整手与 20 万可行性 | `research/carry/sleeve_bt.py` | K4 | 整手对比表 |
| K6 | 验证与闸门 | `lab/validation/*`、`research/governance/experiment_registry.py` | K4、K5、R15 | `lab/research/carry/K6_gate.json` |
| K7 | Shadow 挂载与组合测试 | `external/strategies/`、`desk/strategies/extra/` | K6 过闸 | Desk 影子曲线 |

---

### K0 分月合约历史日线库

**目标**：每个品种从 2016 年起（拿不到就从最早可得年份起）所有上市月份的日线，字段包括 date、open、high、low、close、settle、volume、open_interest。

**改法**

1. 新建 `research/carry/contract_store.py`：
   - `list_contracts(code, start="2016-01", end=None)`：按 `public_curve.MONTHS` 生成合约代码；AU、CU、AL、NI、I、JM、SS 补全 12 个月。
   - `load_contract(sym)`：先读 `.cache/contracts_hist/{sym}.json`；没有缓存就按这个顺序取数：`market_data.fetch_sina_symbol(sym)` → `tqsdk_client`（需 `TQ_USER`）→ 跳过并记录。
   - 已到期的合约数据不会再变：写入后设 `final=true`，以后不再重复抓取。
2. 新建 `scripts/backfill_contract_history.py --codes ALL --start 2016-01`，输出覆盖报告 `lab/research/carry/K0_coverage.json`（每个品种的合约数、最早日期、缺失月份）。
3. `.gitignore` 增加 `.cache/contracts_hist/`，只提交覆盖报告。

**需要先核实**：郑商所的老合约在新浪上的代码格式。2020 年前的合约可能是 3 位，例如 `MA001`，而不是 `MA2001`。任选 `MA001`、`TA905`、`SR909` 各试一次，按结果在 `list_contracts` 里给郑商所品种加 3 位代码的回退。

**验收**：20 个主池品种中，≥ 16 个从 2019 年或更早开始连续覆盖；每个交易日至少有 2 个合约有成交量。

---

### K1 可交易期限曲线（修 D1、D2）

**规则**（固定写死，不调参）

- **可交易合约**：当日持仓量 ≥ 该品种全部合约持仓之和的 5%，并且距离交割月第一天 ≥ 20 个交易日。个人户不能持仓进入交割月，所以这条硬性排除近月。
- **主力**：可交易合约里持仓量最大的。
- **次主力**：到期晚于主力、持仓量 ≥ 全部持仓 5% 的合约里，到期最近的一个。找不到就当日记缺失。
- **年化展期收益**（正数表示贴水，做多有利）：

```python
import math

def roll_yield_ann(f_dom: float, f_next: float, t_dom: str, t_next: str) -> float | None:
    """t_*：最后交易日 'YYYY-MM-DD'，来自 configs/calendar/delivery_rules.json。"""
    from datetime import date
    if not f_dom or not f_next or f_dom <= 0 or f_next <= 0:
        return None
    days = (date.fromisoformat(t_next) - date.fromisoformat(t_dom)).days
    if days < 20:
        return None
    return math.log(f_dom / f_next) * 365.0 / days
```

**输出字段**：`date, code, dom, next, f_dom, f_next, oi_dom_share, oi_next_share, t_dom, t_next, ry_ann`。

**测试** `tests/test_carry_curve.py`：
- 交割月前 19 个交易日的合约不能当主力。
- 主力和次主力的到期日严格递增。
- 人造曲线：主力 100、次主力 98、间隔 120 天 → `ry_ann ≈ ln(100/98)×365/120 ≈ 6.1%`。

**验收**：`|ry_ann| > 60%` 的观测占比 < 1%（作为对比：现有面板 18% 的观测 |gap| > 5%，而且没有年化）。

---

### K2 持有合约收益指数（修 D4）

**规则**

- 持有 K1 当天的主力合约；主力变化时，在 **T+1 开盘** 平旧开新。
- 指数收益 = 同一合约的日收益（`close_t / close_{t-1} − 1`）；换月日的收益 = 旧合约 T−1 收盘 → T+1 开盘，加上新合约 T+1 开盘 → T+1 收盘。
- 每次换月记 2 次成交成本（复用 `path_a_filters.fill_cost`）。

```python
def held_index(rows):
    """rows：按日期升序，字段 date, dom, bars（dict: sym -> bar）。返回 [(date, ret, rolled)]。"""
    out, cur = [], None
    for i in range(1, len(rows)):
        prev, today = rows[i - 1], rows[i]
        if cur is None:
            cur = prev["dom"]
        b0, b1 = prev["bars"].get(cur), today["bars"].get(cur)
        if not b0 or not b1:
            out.append((today["date"], 0.0, False))
            continue
        r = b1["close"] / b0["close"] - 1.0
        rolled = False
        if prev["dom"] != cur:                       # 昨天收盘发现主力已变：今天开盘换月
            nb = today["bars"].get(prev["dom"])
            if nb:
                r = (b1["open"] / b0["close"] - 1.0) + (nb["close"] / nb["open"] - 1.0)
                cur, rolled = prev["dom"], True
        out.append((today["date"], r, rolled))
    return out
```

**验收**：(1) 指数在换月日没有跳空（换月日 |ret| 的分布和非换月日一致，可以做 KS 检验）；(2) 用 R6 的复权主连对同一品种做对照，两者 1 年累计收益差 < 3%，差异主要来自展期收益（逐年列出）。

---

### K3 信号：预登记 5 个，跑完不再追加

| ID | 名称 | 定义 | 依据 |
|----|------|------|------|
| S1 | 横截面 carry | 每周五按 `ry_ann` 横截面排序，取前 1/3 做多、后 1/3 做空 | Bianchi 等 2019：等权足够，排序和强度加权没有明显改善 |
| S2 | 时序 carry | `ry_ann > +5%` 做多，`< −5%` 做空，否则空仓 | 预先给定阈值，不扫参 |
| S3 | 固定合约对基差动量 | 在同一对 (dom, next) 上计算：`r_dom(60) − r_next(60)`；如果 60 日内主力切换过，用新合约对重算，数据不足就记缺失 | Boons & Prado 定义；修 D3 |
| S4 | S1 + S3 等权 | 两个信号的横截面秩各占 50% | 预登记组合 |
| S5 | 去季节 carry | `ry_ann` 减去该品种过去 3 年同一日历月 `ry_ann` 的中位数，只用 t 之前的数据，再按 S1 规则排序 | 处理 SA/JD/FG/RU 的季节性 |

**统一规则**：周五收盘计算信号，下周一开盘成交；同一品种的目标仓位变化小于 20% 就不调（缓冲）；**板块中性版本**作为每个信号的附加结果一起输出（文献提醒行业效应解释了很大一部分动量利润）。

**登记**：5 个信号 × {原始、板块中性} = 10 个试验，全部写入 `experiment_registry`（R15）。之后 DSR 的 n_trials 至少按 10 计。

---

### K4 袖套回测引擎

- **新文件** `research/carry/sleeve_bt.py`，和 Path-A 的 `simulate` 分开，避免互相污染。
- **收益**：用 K2 的持有合约指数。
- **定仓**：逆波动率加权，品种波动用 60 日 EWMA 估计；袖套目标年化波动 8%；总名义 ≤ 150%。
- **成本**：Base（1 跳 + 公示手续费）和 Stress（2 跳 + 手续费 × 1.25），沿用 `research_cost.json`；换月成本单独统计。
- **区间**：从 K0 覆盖开始的年份（预计 2019 年）到 2026-11。

```powershell
python -m research.carry.sleeve_bt --signals S1,S2,S3,S4,S5 --neutral both --cost base,stress --out lab/research/carry/K4_all.json
```

**每个试验都要输出**：年化收益、年化波动、Sharpe、最大回撤、Calmar、分年收益、换手、成本占比、IC（对未来 5 日和 20 日）、三分位组合的收益是否单调，以及和 EWMAC 趋势、Path-A 日收益的相关系数。

---

### K5 整手与 20 万元可行性

- **单手风险预筛**（沿用 R10）：1 手的 ATR 风险 > 单品种风险预算 × 1.5，或者 1 手名义 > 权益的 40%，就不进入袖套。
- **整手版**：多空各取前 3 和后 3，手数 = `floor(目标名义 / 1 手名义)`，算出来为 0 就丢掉。
- **对比**：整手版 Sharpe ÷ 按比例版 Sharpe，并统计每天实际持有的品种数。

**参考**（20 万权益、最新价格）：RB、FG、SA、V、MA、M、JD、TA 这类品种 1 手名义只有权益的 9%–16%，适合做袖套；RU、AG、CU、AU 1 手就超限，排除。

**验收**：整手版 Sharpe ≥ 按比例版的 70%；平均同时持仓 ≥ 4 个品种。

---

### K6 验证与闸门（全部满足才算过闸）

| 条件 | 阈值 |
|------|------|
| 样本长度 | ≥ 6 年（K0 覆盖决定；不足 6 年只能停在 Research） |
| Stress 成本下的 Sharpe | ≥ 0.4 |
| IC（20 日）t 值 | ≥ 2 |
| 三分位单调 | 多头组 > 中间组 > 空头组，按年计 ≥ 60% 的年份成立 |
| 正收益年份占比 | ≥ 60% |
| 与 EWMAC 趋势、Path-A 的相关系数 | < 0.3 |
| DSR（n_trials ≥ 10） | ≥ 0.9 |
| PBO | ≤ 0.3 |
| 整手版 Sharpe / 按比例版 Sharpe | ≥ 0.7 |

**选择规则**：只在过闸的试验里选 Sharpe 最高的一个；如果板块中性版和原始版都过闸，选板块中性版，因为它风险更低。**一个都不过闸，就在 `docs/UPGRADE_ITERATIONS.md` 里记“carry 在本数据上未证实”并关闭这条轨，不允许追加信号重跑。**

---

### K7 Shadow 挂载与组合测试

1. 产出 `external/strategies/carry_sleeve.json`，包含 `equity_curve`、`final_positions` 和 `trade_log`；在 `desk/strategies/extra/carry_sleeve.json` 指向它，Desk 上就能叠加显示。
2. 组合测试（研究层）：`趋势袖套 : carry 袖套 = 50 : 50`（按风险分配），对比单独趋势的最大回撤和 Calmar。
3. 影子跟踪至少 6 个月（锁定参数，只看样本外），再按 R16 的门槛评估能不能晋级。
4. 日报里只展示 carry 袖套的目标仓位，**不写入 `paper_book`**。

---

## 3. 风险与已知限制

- **数据起点**：`public_curve` 的注释写着新浪很多月份合约只有 2018–2019 年以后的数据，所以样本大概率只有 6–7 年，达不到 R16 要求的 8 年。这种情况下最多只能作为 Shadow 袖套运行。
- **郑商所老合约代码**：见 K0 的核实项，没解决会导致 2020 年前的郑商所品种缺数。
- **交割规则**：个人户不能持仓进入交割月，K1 的 20 个交易日缓冲是硬约束；具体日期以 `configs/calendar/delivery_rules.json` 为准，节假日要校正。
- **季节性**：S5 只是一种处理办法。如果只有 S5 过闸，要在反馈里明确写出来，因为它的收益来源更接近“季节价差回归”，不是风险溢价。
- **原型的局限**：第 0 节的数字用的是有缺陷的面板和近似复权主连，只能说明“现有数据判断不了”，不能当作 carry 的最终结论。

---

## 4. 执行模板（贴给 Cursor）

```text
开刀 K?：<名称>（R14 carry 袖套）
先读：docs/CARRY_SLEEVE_R14.md 第 0 节和本刀；docs/STRATEGY_EVIDENCE_REVIEW.md 第三节
范围：只新增/修改 research/carry/、scripts/backfill_contract_history.py、tests/test_carry_*.py
禁止：改 historical_backtest.py / paper_book.py / execution_rules.json / universe.json；写任何 *_latest.json 正式文件
测试：python -m pytest tests/test_carry_*.py -q；全量 python -m pytest tests/ -q
产物：<路径>
完成后反馈（3–6 行）：做了什么 / 产物 / 验证 / 风险与未做 / 建议下一刀或停
```
