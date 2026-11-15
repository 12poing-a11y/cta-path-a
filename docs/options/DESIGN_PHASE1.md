# 期权研究台 · 阶段 A 设计（阶段一卖方）

**日期**：2026-11-15  
**目标**：在**不改 Path-A 正式层**前提下，为有限风险卖方（信用价差）建可审计研究底座。  
**阶段一范围**：卖方信用价差（vertical credit）；买方策略延后。

---

## 1. 设计原则

1. **隔离**：期权研究读写仅限 `data/options/`、`research/options/`、`desk` 只读面板；禁止写 `paper_book` / 正式 BT / seats。  
2. **诚实定价**：无 Bid/Ask 时用结算价 + 显式滑点折扣；状态最高 WARN。  
3. **无未来函数**：入场只用 T 日收盘后可得字段；管理用 T+1 及之后。  
4. **Synthetic 保留**：ATR 合成期权继续服务保护观察；与上市腿研究并存，字段分离。  
5. **质量闸优先于策略**：链缺失 / 覆盖率低 / 基差过大 → 拒算或标 REJECT，不默默用连续替代。

---

## 2. 复用 vs 新增

### 复用（轻改或旁路调用）

| 能力 | 来源 | 用法 |
|------|------|------|
| CZCE 日链抓取 | `gamma_wall._fetch_czce_day` | 抽出到 `research/options/chain_czce.py` 或包装调用 |
| 合约侧/月份解析 | `_contract_side` / `czce_option_month` | 公共 utils |
| Black-76 gamma | `black76_gamma` | 迁入 `pricing/black76.py` 后双向兼容导入 |
| 质量评估模板 | `assess_data_quality` | 扩展期权链质量字段 |
| 精确期货日线 | `exact_contract` / historical_backtest helpers | 标的结算价 / 基差 |
| IV 日缓存 | `iv_breakout` | 仅作筛选特征，不作定价 IV |
| 选腿启发式 | `option_compare._pick_leg` | 研究入场参考，非唯一规则 |
| 观察配置 | `universe.observe.option_hedge` | 保持 observe-only |

### 新增（阶段 B–C 落地）

```
research/options/
  __init__.py
  specs.py              # 合约规格：乘数、最小变动、保证金粗模
  chain_store.py        # 日链落盘 / 读取 data/options/snapshots
  quality.py            # 链质量闸
  pricing/
    black76.py          # 正算/反算 IV、delta、gamma（FD 校验）
    surface.py          # ATM / 邻近行权价插值（无恒定期限则标 WARN）
  strategies/
    credit_vertical.py  # 信用价差：选腿、入场、管理、到期
  backtest/
    engine.py           # 研究回测（独立产物）
    metrics.py          # 胜率、平均信用、最大不利、保证金占用
  paper/
    ledger.py           # data/options/paper_trades 台账（非 Path-A paper_book）
desk/options_research_panel.py   # 研究台面板（可选阶段 C）
scripts/run_options_chain_collect.py
scripts/run_options_credit_bt.py
tests/test_options_*.py          # 离线夹具
```

### 不新建（明确延后）

- 买方引擎 / 跨式 / 日历价差完整回测  
- 全品种期权宇宙自动扫描  
- 写入正式 `paper_book` 或替换 seats  
- NotebookLM / 外部 LLM 自动调参闭环  

---

## 3. 目标文件变更（按阶段）

| 阶段 | 文件 | 变更类型 |
|------|------|----------|
| A | `option_hedge.py` | **热修** OH-01：`is not None` |
| A | `tests/test_option_hedge.py` | 新增：ATM=0 不被吞 |
| A | `docs/options/*` | 本设计 + 审计 + 路线图 |
| B | `research/options/pricing/*` | 新建 Black-76 + 反算 |
| B | `research/options/specs.py` | CF/SR/MA 乘数与点值 |
| B | `gamma_wall.py` | 可选：import 新 black76，行为不变 |
| C | `research/options/chain_store.py` + collect script | 日链 + 质量闸落盘 |
| C | `tqsdk_client` | 可选扩展：活链 Bid/Ask 字段写入快照 |
| D | `strategies/credit_vertical.py` + bt engine | 卖方研究回测 |
| D | `desk/options_research_panel.py` | 只读展示研究 KPI |
| E | paper ledger + risk report | 研究纸面 + 风险报告 |

**禁止变更清单（全程）**：`paper_book.py`、正式 `historical_backtest` 晋升路径、`execution_rules.json`、seats 生成、`daily_update` 硬失败路径。

---

## 4. 数据契约（阶段 B/C）

### 日链快照 `data/options/snapshots/{CODE}/{YYYYMMDD}.json`

```json
{
  "code": "CF",
  "asof": "2026-11-14",
  "underlying": "CF701",
  "underlying_settle": 15230.0,
  "source": "czce_day|tq_live",
  "quality": {"status": "OK|WARN|REJECT", "reasons": []},
  "legs": [
    {
      "symbol": "CF701C15200",
      "side": "C",
      "strike": 15200,
      "settle": 180.0,
      "close": null,
      "bid": null,
      "ask": null,
      "oi": 1200,
      "volume": 80,
      "exchange_iv": 0.22,
      "delta": 0.45
    }
  ],
  "pricing_note": "no_bid_ask; use settle minus slip_ticks for credit entry research"
}
```

### 研究纸面 `data/options/paper_trades/ledger.jsonl`

- 与 Path-A `paper_book` **物理分离**  
- 字段含：`strategy_id`、`legs[]`、`credit`、`margin_est`、`status`、`asof`、`quality`

### 回测产物 `data/options/backtests/credit_vertical_latest.json`

- 仅研究 KPI；不得覆盖 `historical_backtest_latest.json`

---

## 5. 卖方信用价差（阶段一）逻辑草图

1. **标的池**：先 CF / SR / MA（数据最齐）；其他 CZCE 观察。  
2. **选腿**：同到期；卖近 ATM / 买更 OTM；宽度可配置（点或 ATR 倍数）。  
3. **入场价（研究）**：  
   - 有 Bid/Ask：卖用 Bid、买用 Ask（规格要求）。  
   - 无：`credit = (settle_short − settle_long) − slip_ticks × tick_size`；`pricing_mode=settle_discount`。  
4. **管理**：到期结算 / 固定止损（不利点数）/ 时间衰减阈值；**禁止**用未来 RV 调仓。  
5. **风控**：单笔保证金上限、同品种同向敞口上限、链质量 REJECT 日跳过。  
6. **状态机**：`RESEARCH` →（稳定 Bid/Ask + 样本）`WARN` → 人工晋升；不自动进 Path-A。

---

## 6. Synthetic 与上市腿并存规则

| 字段前缀 | 含义 |
|----------|------|
| `syn_*` / `premium_source=synthetic_atr` | ATR 合成保护 |
| `listed_*` / `premium_source=exchange` | 上市期权研究 |

Desk / 报告禁止混标题；比价模块继续输出两者差额，但差额**不**作为入场唯一条件。

---

## 7. 验收标准（阶段 A 完成定义）

- [x] 审计文档列出 P0–P1 与数据缺口  
- [x] 设计文档明确复用/新增/禁止触碰  
- [x] 未升级部分有分阶段路线图与依赖  
- [x] OH-01 已修且有单测  
- [ ] 阶段 B 起需单独确认后再写代码  

**阶段 A 状态：完成（文档 + OH-01 热修）。**
