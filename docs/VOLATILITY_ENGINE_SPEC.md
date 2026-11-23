# 商品期权波动率研究引擎规格（Vol-V1.4）

**日期**：2026-11-23  
**归档**：2026-11-23 **轻量入库 GitHub**（复现用 · **不晋级**）  
**来源审计**：[ChatGPT v2.0 白皮书审计](https://chatgpt.com/s/t_6b041c59f0588191b60f9b9059fed500)  
**定位**：Research / Shadow only；不写 Path-A `paper_book` / seats / `position_rules`；不自动下单。

> **结果口径（人工）**：本版反馈**偏弱**，仅作实验骨架归档。  
> `live_trading=false` · `promote_path_a=false` · **不得**当作可交易或 F2/正式层依据。  
> 后续 Vol-V1.5+ 须明示重开；弱结果不等于作废代码，但等于**禁止晋级**。

---

## 目标（本阶段）

落地可验证的 **定价 + Greeks + Shadow Greeks 监控** 骨架，日报告可对 CF/SR/MA 链快照跑通。

**不是**：SABR 残差开仓、奇异期权交易、VIX 直接控商品杠杆、整包 v2.0、策略晋级。

---

## 模块

| 文件 | 职责 |
|------|------|
| `research/options/volatility/iv_surface.py` | 链上 IV 反解网格 + 质量标记 |
| `research/options/volatility/greeks_engine.py` | Black-76 Δ/Γ/ν/Θ |
| `research/options/volatility/shadow_greeks.py` | Sticky Strike / Sticky Delta 有限差分 Shadow Δ/Γ |
| `research/options/volatility/daily_vol_report.py` | 日报告 JSON（无交易指令） |

定价核复用 `research/options/pricing/black76.py`（商品期货期权 Black-76）。

---

## 数据与质量

- 输入：`data/options/snapshots/{CODE}/{asof}.json`
- 权利金优先级：mid(bid,ask) → settle → close；**禁止**求解失败填 IV=0
- Bid > Ask → 腿 REJECT；无有效权利金 → 跳过并计数
- T、F、K 须 > 0；到期日 ≤ asof → 跳过
- Bid/Ask 不足时报告 `quality=WARN`，仍可对 settle 腿出 Greeks

---

## Shadow Greeks 定义（监控）

| 指标 | 定义 | 用途 |
|------|------|------|
| Vanilla Delta | 固定 IV 的 Black-76 Δ | 基准 |
| Sticky Strike Shadow Δ | F±dF，同一 K 的 IV 不变 | 曲面固定行权价假设 |
| Sticky Delta Shadow Δ | F±dF，按 log-moneyness 在曲面重取 IV | 曲面粘性 Δ 假设 |

Shadow Gamma：对 F 再差分一次；上下行分别输出，**不**把符号相反直接当 Risk Reversal 交易信号。

---

## 产物

- `lab/research/volatility/vol_engine_daily_latest.json`
- 字段含：`live_trading=false`、`promote_path_a=false`、`model_version=vol_engine_v1.4`

---

## 后续（未开放）

Vol-V1.5 VRP/Gamma Scalping · Vol-V1.6 TVS 硬化 · 执行成本账本 · SABR 分阶段 · 奇异 · F2 盘口 BT

---

## 硬约束

失败 fail-closed；追加式报告；不覆盖历史正式台账；晋级须人工。
