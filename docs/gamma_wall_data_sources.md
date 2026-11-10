# Gamma Wall：数据源、质量控制、自动采集与调用量

## 数据源与费用
1. 免费主源：AkShare 郑商所日频期权接口 option_hist_czce，按交易日拉取品种全量期权行情，本地筛选目标系列。
2. 免费标的价格：AkShare 新浪单合约日线（如 CF2701）。缺日依次用同花顺扶摇（`CF701.CZC`）、天勤 TqSdk（`CZCE.CF701`）精确合约补洞。禁止用主连或前一日价格替代。
3. 观察品种：仅对**有期权链且能取到 OI+IV** 的品种出图；无期权自然跳过。当前引擎主源仍为郑商所日频期权表。
4. **扶摇期权能力结论（2026-11-09 实测）**：品种/合约目录与期权日 K（OHLC/量/额）可用；**日 K 与合约详情不含隐含波动率 IV、不含持仓量 OI/空盘量**。因此扶摇**不能**替代 Gamma 计算所需的完整期权链。扶摇仅作期货单合约缺日补洞。
5. **天勤 TqSdk（2026-11-09 实测）**：快期账号可取期货日线+OI；期权链有 OI，IV 由 `OPTION_IMPV` 本地反算（非交易所结算 IV）。Gamma 正式快照仍优先 AkShare 郑商所结算 IV；天勤作标的缺日补洞与期权链备份研究源。凭据：`TQ_USER`/`TQ_PASS` 或 `.env.tqsdk`（gitignore）。
6. **GitHub Actions**：不把 `FUYAO_API_KEY` / `TQ_*` 作为日更硬依赖；无 Key 时跳过对应补洞、不失败。Gamma 日采继续走 AkShare 郑商所期权表；未配置 `GAMMA_*_EXPIRY` 的品种跳过。
7. OI 或 IV 缺失不插值、不借用其他日期字段；该快照拒绝入库。

## 数据质量闸门
- 标的行情日期必须与期权快照日期一致。
- 目标期权系列必须匹配 CF2701→CF701 / SR2701→SR701。
- 有效行权价至少 5 档。
- 有效合约覆盖率至少 60%（有效 OI+IV 合约数 / 匹配系列合约数）。
- OI 必须大于 0；IV 必须可解析且在合理数值边界内；到期日必须晚于快照日。
- 任一条件不通过：抛出明确错误，不写入正式历史目录，也不进入墙位迁移图。

上述阈值是工程质量闸门，不是交易所对数据完整性的承诺。后续用真实采集样本评估覆盖率分布后再校准，不能为了让图表“有结果”而放宽。

## 历史保存与迁移
- 通过闸门的每日快照保存在 data/gamma_wall/{合约}/{YYYY-MM-DD}.json，由 GitHub Actions 提交回仓库，避免 Runner 临时文件丢失。
- 原始接口缓存放在被忽略的 .cache/gamma_wall/raw/，不提交原始全量期权表。
- 迁移窗口支持 5/10/20/30/60 个有效交易日，默认 20 日；历史从正式部署并成功采集后开始累积，不虚构过去的 Gamma。
- 历史加载器只读取 data_quality.status=PASS 的快照。

## 自动采集
工作流：.github/workflows/gamma_wall_daily.yml
- 工作日北京时间 16:35（UTC 08:35）运行，支持手动触发。
- 在 GitHub 仓库 Settings → Secrets and variables → Actions → Variables 中设置：
  - `GAMMA_<合约>_EXPIRY`：例如 `GAMMA_CF2701_EXPIRY`、`GAMMA_MA2701_EXPIRY`，值为该期权系列最后交易/到期日 YYYY-MM-DD。
- 覆盖 CF/SR/MA/TA/SA/RM/OI/FG 的 2701 合约；优先用 Variables 中的到期日；未配置时回退到该合约目录下最新 PASS 快照的 `expiry`（须仍晚于 asof）。
- 采集由 `scripts/gamma_wall_daily_collect.py` 执行：至少一个合约成功才算绿；全跳过/全失败则 error（避免空跑当成功）。
- 首次启用建议手动运行一次，并在 Variables 写入核实后的 `GAMMA_*_EXPIRY`。

## 调用量估算
- 每个品种每个新交易日：期权接口约 1 次，标的期货日线在缓存无该交易日时请求，通常 1 次。
- CF + SR 每日通常约 2–4 次 AkShare 函数调用；底层 HTTP 请求可能因重试/重定向增加。
- Gamma、GEX、墙位、质量检查、迁移、绘图均为本地计算，0 次额外 API 调用。
- GitHub Actions 每次是新 Runner，不能承诺跨运行缓存命中。

## 口径限制
- IV 为百分数时自动除以 100；OI 按郑商所期权日行情手数处理；乘数 CF=5、SR=10。
- Call 侧画在零轴上方、Put 侧画在零轴下方，只为对称展示两侧 Gamma 集中度，不是 Dealer 持仓方向。
- OI 不含持仓方身份，V1 不发布真实 Dealer Net GEX，也不伪造 Gamma Flip。
- Black-76 使用期货价格；当前 GEX 为研究近似值，不应与美股做市商标准化 GEX 直接比较。

## 研究台与命令行
本地启动：pip install -r requirements.txt 后运行 streamlit run desk/app.py，进入「Gamma 结构」页面，选择 CF2701/SR2701，填写经核实的到期日并点击拉取。

```bash
python gamma_wall.py --contract CF2701 --expiry YYYY-MM-DD
python gamma_wall.py --contract CF2701 --expiry YYYY-MM-DD --date YYYY-MM-DD
python gamma_wall.py --contract SR2701 --expiry YYYY-MM-DD
python -m pytest tests/test_gamma_wall.py -q
```


## 日更空跑保护

gamma_wall_daily.yml 在「无 Variables 且无可用快照到期日、因而 0 个成功快照」时会 **失败**（::error::），避免绿色=空跑。推荐仍在 Settings → Variables 填写核实后的 `GAMMA_*_EXPIRY`；缺省时可回退仓库内 PASS 快照到期日。桌面 Gamma 页会显示「累积有效快照 N / 窗口」。
