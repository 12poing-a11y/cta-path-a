# 研究台升级方案（可执行版）

目标：把 `cta-path-a` 从「策略信号工具」升级为**可验证的商品期货量化研究系统**。  
原则：**研究层与正式层隔离** · **先数据后模型** · **先验证后上线**。

权威参数：`execution_rules.json`（止损 **0.8×ATR** / 止盈 **2R**）。

---

## 总状态

| 范围 | 状态 |
|------|------|
| P0 数据/成交/日历/合约缓存 | **主路径完成** |
| P1 统计验证 + PBO | **完成** |
| P2 LSP + Gamma 研究 | **完成（触碰样本仍短）** |
| P3 组合风险影子 | **完成** |
| P4 ML 轻量 | **完成（Research only）** |
| P4 ML 重型（Transformer/RL） | **暂缓** |

---

## P0 明细（本轮）

| 项 | 状态 |
|----|------|
| 双掩码 / simulate 闸门 / Base·Stress | 已做 |
| 交割日历 + 显式 `last_trade_dates` | 已做 |
| front-month 日线灌库 `.cache/contracts/` | **已做 27/27 + AU/AG 2702** |
| 合约开盘叠加 fill；AU→2702 按上市月 | **已做** |
| 覆盖率（近窗） | 均值约 **86%**；AU2701 旧约稀，已改 AU2702 |

```powershell
python lab/scripts/backfill_front_month_daily.py --month 2701
python lab/scripts/backfill_front_month_daily.py --month 2702 --codes AU,AG
```

---

## P4 轻量（本轮）

| 项 | 状态 |
|----|------|
| 标签：LSP 反转 / 趋势失效 / 突破延续 | **已做**（无泄漏：不含 MFE/MAE/事后收益） |
| LightGBM（缺则 HistGBM）+ 时序切分 OOS | **已做** |
| 产物 `lab/research/ml/p4_light_latest.json` | **已跑** |
| Desk「P4 轻量ML」 | **已挂** |
| 正式 Path-A | **未改**（Shadow/Research only） |

首跑（CF）：LSP 反转 OOS AUC≈0.73；趋势失效≈0.67；突破延续≈0.53（弱，待更多样本）。

```powershell
python lab/scripts/run_p4_light.py
python -m pytest tests/test_p4_light.py -q
```

---

## 常用命令

```powershell
python lab/scripts/run_pbo_path_a.py --mode seats
python lab/scripts/run_lsp_cf.py --period both
python lab/scripts/run_gamma_research.py --contract CF2701
python lab/scripts/run_portfolio_risk.py
python lab/scripts/run_p4_light.py
```

---

## 下次（剩余）

1. **交易所官历精校**（用公告替换近似 `last_trade_dates`）  
2. **Gamma 触碰**：继续积累日频墙；当前放宽 ATR 后有事件但多为 stay  
3. **P4 重型**（可选，暂缓）  
4. 提交/推送本轮升级（需你明确说）

---

参考：[ChatGPT share](https://chatgpt.com/s/t_6af71fa383b0819181f1377777a325e2)
