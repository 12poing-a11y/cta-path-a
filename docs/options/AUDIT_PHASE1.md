# 期权研究台 · 阶段 A 审计报告

**日期**：2026-11-15  
**范围**：现有期权相关模块（只读审计 + 发现项）  
**原则**：不改 Path-A 正式信号 / `paper_book` / seats / 日报硬路径；ATR 合成期权保持 Synthetic。  
**规格来源**：ChatGPT 升级规格 V1.0（买方 + 有限风险卖方双引擎；阶段一卖方）

---

## 0. 最重要发现

| ID | 严重度 | 发现 |
|----|--------|------|
| OH-01 | **P0** | `option_hedge.hedge_params` 用 `or`：`strike_atr_mult=0.0`（ATM）被当成 **1.0**；Desk 显示 ATM，观察回测用 1×ATR OTM |
| IV-01 | **P0** | CZCE「IV」=`iv_breakout` 全系列全行权价成交量加权，**不是** ATM / 恒定期限 IV；与 SHFE 单行最高量口径不可比 |
| MD-01 | **P0** | 全仓**无 Bid/Ask 历史**；无法按规格用卖 Bid / 买 Ask 做信用价差入场 |
| CP-01 | **P1** | `option_compare.hist_last_close` 缓存无日期、永不过期；Sina 路径用 `months[0]` 未必对应当前合约 |
| GW-01 | **P1** | Gamma Wall 的 Flip/墙位是 OI×gamma 展示约定，**非**做市商净 Gamma；OI 无买卖方向 |
| VE-01 | **P1** | `vol_engine.vrp_value` = IV−RV20 仅为波动差代理；`sell_vol_credit_spread` 只是标签，无行权价/保证金/损益 |

---

## 1. 模块清单

| 文件 | 职责 | 处理 |
|------|------|------|
| `option_hedge.py` | ATR 合成保护期权权利金/行权/内在价值 | **保留 Synthetic**；修 OH-01；字段标 `premium_source=synthetic_atr` |
| `option_compare.py` | 合成 vs 上市腿比价（Sina/Tq） | **轻扩或替换数据层**；复用选腿逻辑 |
| `iv_breakout.py` | IV 日缓存 / 突破标签 | **复用抓取与缓存**；不直接作定价 IV |
| `vol_engine.py` | RV/IV 分位、VRP、策略标签矩阵 | **保留筛选层**；不改为信用价差研究引擎 |
| `gamma_wall.py` | CZCE 链 + Black-76 gamma + 质量闸 | **复用链抓取/归一化/质量模板**；语义降级展示 |
| `tqsdk_client.fetch_option_chain_snapshot` | 活链 OI/最新价/反算 IV | **扩展可采 Bid/Ask**（报价对象已有） |
| `desk/options_panel.py` | 保护期权机会表 | **保留 Synthetic**；渲染时禁长期依赖网络 |
| `desk/cf_option_pressure.py` | 棉花「权利金压力」 | **保留但标注 ATR 代理**，勿当期权需求证据 |
| `desk/vol_engine_panel.py` / `gamma_panel.py` | 波动/Gamma 台面 | **保留** |
| `scripts/gamma_wall_daily_collect.py` | Gamma 日采 | **保留** |
| `lab/gamma/*` | Gamma 研究旁路 | **保留** |

---

## 2. 可复用接口

- CZCE 日表：`option_hist_czce` → `gamma_wall._fetch_czce_day`（结算、OI、成交、IV%、DELTA）
- 解析：`_contract_side`、`czce_option_month`（CF2701→CF701）
- `gamma_wall.black76_gamma`（公式可用；需补 FD 校验与单位测试）
- `assess_data_quality`（日期一致、覆盖率、拒写）→ 新链质量闸模板
- IV 缓存：`.cache/akshare/option_iv/<CODE>/<ymd>.json`（日更已 force-add）
- 精确期货：`_load_exact_contract_daily` / `load_exact_contract_bars`（禁连续替代）
- 选腿：`option_compare._pick_leg` / `_pick_tq_leg`
- 配置：`universe.observe.option_hedge`（仅观察；正式 BT `option_hedge=False`）

---

## 3. 逻辑与可信度问题（摘要）

### VRP / vol_engine
- VRP 用**事后已实现 RV20**，非期权寿命内前瞻方差溢价  
- IV/RV 分位窗不一致（IV~60 日 vs RV~250 日）  
- `iv_falling` 条件过宽；日历候选仅 SHFE  
- `run_universe` / Desk 渲染会回写 `data/vol_engine_latest.json`

### 合成期权
- 权利金 = `lots×ATR×mult×k`，无期限/IV/偏度；平仓只结内在价值 → 结构性易亏  
- OH-01 使 ATM 配置失效  
- `cf_option_pressure` 实为缩放 ATR，文案易误解为期权需求

### Gamma Wall
- Black-76 gamma 公式正确；T=(expiry−asof)/365，expiry 手填/环境变量  
- Call+/Put− 仅为展示；Flip=累计净暴露过零，可远离现价  
- 观察月统一 2701 可能错过主力序列（如 MA612 vs MA701）  
- 历史薄（CF~6 日，SR/MA~4 日快照）

### 行情
- **无 Bid/Ask**；仅有结算/收盘/最新价  
- 比较模块缓存过期风险；Tq 链截断 `max_options=120`、IV 为本地反算

---

## 4. 测试覆盖缺口

- **无** `option_hedge` 单测 → OH-01 存活  
- `option_compare` 几乎只测 Tq 路径  
- `black76_gamma` 仅测正值，无 FD / put-call  
- `vol_engine.evaluate_code` / `run_universe` 未测  
- `tqsdk` 期权链无离线夹具  
- 无期权保证金/信用价差/未来函数专用测试

---

## 5. 数据缺口（CF / SR / MA）

### 已有
| 源 | CF | SR | MA |
|----|----|----|-----|
| 日 IV 缓存 | ~72 日 | ~78 日 | ~90 日 |
| Gamma 原始链（gitignore） | ~6 日 | ~1 日 | ~1 日 |
| 已提交 Gamma 快照 | ~6 | ~4 | ~4 |
| 精确期货日线 | 有 | 有 | 有 |
| 连续 CODE0 | 有（长史） | 有 | 有 |

### 缺（信用价差研究硬门槛）
- Bid/Ask 时间序列  
- 按行权价结算价的长历史（回测路径）  
- ATM / 恒定期限 / 25Δ IV  
- CZCE 偏度与期限结构  
- 期权到期日历（非手填 expiry）  
- 期权保证金/手续费模型  
- 行权/指派记录  

**结论**：阶段一可先用**结算价 + 显式滑点折扣**做研究定价；在拿到稳定 Bid/Ask 前，策略状态最高 **WARN / 研究候选**，不得 `PAPER_VALIDATED` 以上。

---

## 6. 与 Path-A 正式层耦合（禁止触碰）

- `universe.json` 主池 / `entry_filter=seats` / `execution_rules.json`  
- `paper_book.py` / `paper_book_latest.json`（无 `opt_*` 字段，保持）  
- `l1_report*`、正式 `historical_backtest_latest.json`（观察/对冲跑写入 `_art_opt/`）  
- `daily.yml` / `ci.yml` 全量 pytest（新测失败会挡日报 → 新测须离线夹具）  
- `daily_update` 中 IV 刷新、vol_engine 快照为 soft；勿改成硬熔断除非另立闸门  
- `prediction_log` / sentiment 消费 `vol_fields_by_code` → **勿破坏 schema**

---

## 7. 阶段 A 交付清单

- [x] 本审计 `AUDIT_PHASE1.md`  
- [x] `DESIGN_PHASE1.md`（复用 / 新增 / 文件变更）  
- [x] `ROADMAP.md`（未升级部分计划）  
- [x] OH-01 热修（`is not None`）+ 单测（不改正式 Path-A）  

**下一步（待你确认后开分支）**：阶段 B 基础定价与合约规格（见 ROADMAP）。
