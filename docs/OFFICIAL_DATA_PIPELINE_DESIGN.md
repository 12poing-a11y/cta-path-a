# 官方逐合约日行情：每日自动收集与合并（设计方案，待磊确认后再实现）

状态：**仅设计，未实现任何代码**。边界：正式层数据源不切换（继续用现有本地数据）；`historical_backtest.yml` 继续暂停；本管道只产出官方库、校验报告、官方主力/复权序列，供 shadow 对照与后续研究。

## 1. 范围

- 27 个品种的交易所分布：**上期所 11**（RB FU BU RU AG SP AU CU AL NI SS）、**郑商所 6**（MA FG TA SA CF SR）、**大商所 10**（V EG M EB PP L JD P I JM）、**上期能源 0**。
  → 上期能源**不需要**，不做适配器（以后品种池含 SC/NR/LU/BC 时再加）。
- 复用 R8 抓取代码：`archive/R8/fetch_contract.py`（SHFE `kx{date}.dat`、CZCE `FutureDataDaily.txt`，HTTP）、`ingest_dce.py`（DCE 经真实浏览器同源 POST `/dcereport/publicweb/dailystat/dayQuotes`）、`contract_loader.py`（解析成 `{合约: {日期: {open,high,low,close,settle,presettle,volume,oi,turnover_wan}}}`）。

## 2. 各所发布时间与访问性（今天实测，2026-11-26 晚）

| 所 | 方式 | 本机访问 | 文件时间戳（Last-Modified，北京时间） |
|---|---|---|---|
| 上期所 | `www.shfe.com.cn/.../kx{date}.dat` HTTP GET | 200，0.1 s | 11-25 15:22；11-26 15:25 |
| 郑商所 | `czce.com.cn/.../FutureDataDaily.txt` HTTP GET | 200，0.2 s | 11-25 15:40；**11-26 16:15**（晚到，说明会有迟发） |
| 大商所 | 脚本直连 **412 / SSL 错误**；真实浏览器同源 POST 可用 | 浏览器 200，11-26 数据当晚已有（277 行） | 无时间戳，**发布时间未测到** |

结论与做法：
- 上期所约 15:25 前后发布；郑商所 15:40–16:15 波动；**大商所发布时间无法从头部得知**，管道每次尝试都记录"首次可得时间"，一周后据此定死首跑时间。
- **首跑 17:30**（晚于已观察到的最晚时间 16:15，并给大商所留余量）；失败重试 18:30 / 20:00 / 22:00；**次日 08:30 补抓**：每次运行开头先扫描"交易日历中未齐全入库（三所任一缺）的日期"并补抓，所以"当天没抓到的次日补抓"是同一机制，不是另写一条路径。
- 大商所脚本直连不可用是已知反爬（官网对脚本返回 412）；DCE 必须经真实浏览器会话。

## 3. 运行平台比较：本机 Windows 任务计划 vs GitHub Actions

| 项 | 本机任务计划 | GitHub Actions |
|---|---|---|
| 上期所 / 郑商所 | 可访问（实测） | **大概率可访问**：现有 `daily.yml` 已在 Actions 上取上期所 `pm*.dat`、郑商所 `FutureDataHolding.txt`，近 12 次里 9 次成功（失败的 3 次中 2 次是单测，见下）；但**没有直接实测**本管道的 `kx` / `FutureDataDaily` |
| 大商所 | 可用（真实浏览器；本机 Chrome 已有） | **未知，倾向不可用**：脚本直连 412；Actions 机房 IP 上浏览器是否被拦未验证；`member_rank.py` 记录过 Actions 侧 DCE 接口 HTTP 500（2026-11-15）。要验证只能在远端跑一次探针 workflow（需 push，我没做） |
| 准时性 | 由系统时钟触发，准 | **cron 严重延迟**：`daily.yml` 设 15:30 CST（07:30 UTC），近期定时触发实际启动在 16:18–19:25 UTC（延迟约 9–12 小时）；手动触发则即时 |
| 依赖 | 机器必须开机、联网；可设"错过后尽快运行 + 唤醒" | 无机器依赖；runner 无状态，需缓存/提交回仓库 |
| 存储 | 本地磁盘直接存；56 MB 的现有原始库已在本机 | 官方库要么提交进 git（体积大），要么用 artifact/cache（有过期） |
| 同一时间已有的主干问题 | 无 | `daily.yml` 在 11-25、11-26 因 `tests/test_vol_engine_v14.py::test_daily_report_flags_and_cf_snapshot` 失败（与 R8 无关；本机该测试通过），若把本管道放进该 workflow 会被它拖累 |

**推荐：本机 Windows 任务计划为主**（唯一已验证三所都能取、含大商所真实浏览器的路径；时间准；原始库就在本机）。备选/对照：另开一个独立的 `workflow_dispatch` 探针 workflow（仅 SHFE + CZCE，不含 DCE），在磊同意 push 到远端分支后跑一次，只用于判断 Actions 能否作为**备份来源**，不进入主流程。
风险：机器关机/休眠 → 任务计划设"错过后尽快运行"和唤醒定时；因为有"次日补抓"，单日缺失不会丢数据。

大商所的自动化方式：任务计划里用 **Playwright 驱动本机已装的 Chrome（`channel="chrome"`，有头最小化）**，打开 `http://www.dce.com.cn/` 建立会话后做同源 POST（沿用 `ingest_dce.py` 的页内过滤）；限流对策沿用 R8 的经验（串行、间隔、空响应重试）。该方式**需要安装 Playwright**（新增依赖，仅限管道环境，不进正式层依赖）。

## 4. 存储布局

**独立官方库**（不进主仓库的 git；默认位置 `D:\AI\cta-official-data\`，可配置）：

```
cta-official-data/
  raw/{shfe,czce,dce}/{YYYY}/{YYYY-MM-DD}.gz          # 原始响应，按所/日期分文件，只写一次
  manifests/{exchange}.jsonl                            # 追加：日期、url、状态、bytes、sha256、抓取 UTC、首次可得 UTC、尝试次数
  revisions/{exchange}/{date}/{ts}.gz + diff.json       # 已入库日期的内容变化：新内容与差异报告，不覆盖
  contracts/{exchange}/{合约}.jsonl                     # 逐合约日线，增量追加（一行一日）
  derived/main_official.json, adjusted_official/…       # 官方主力序列（5% 守卫）与 R6c 复权序列，增量更新
  reports/daily/{date}.json|.md                         # 每日校验报告
  alerts/ALERT_{date}.md                                # 告警文件
  logs/{date}.log
```

- 主仓库只放：管道代码、配置、**每日校验摘要**（体积小，可选提交）。官方库自成一个本地 git 仓库（可选：推到私有远端做备份，磊定）。
- **种子**：把 R8 已取的 `archive/R8/raw_contract/{shfe,czce,dce}` 与三份 `MANIFEST_*.json`（2016-01-04 → 2026-11-25）迁入官方库，作为第 0 天；管道从 2026-11-26 起增量。
- **已入库不可变**：同日期再次抓到 sha256 相同 → 仅更新 manifest 尝试记录；**不同 → 不覆盖**，新内容落 `revisions/`，生成逐合约逐字段差异报告（只列 27 品种相关合约）并**报警**，`contracts/` 与 `derived/` 保持原值，等人工处理。

## 5. 每日流程（一次运行）

1. 读日历，列出"应有而缺"的交易日（含今天）；对每个缺口逐所抓取（SHFE/CZCE HTTP；DCE 浏览器）。失败重试（指数退避，最多 4 次）；每次尝试写 manifest。
2. 解析 → 追加到 `contracts/`（仅新日期；已入库日期走 §4 的不变性规则）。
3. 每日校验（§6）→ `reports/daily/{date}`。
4. 更新衍生序列（§7）。
5. 退出码与告警（§8）。

## 6. 每日校验

1. **交易日历对齐**：三所当日文件均存在且日期一致；非交易日（节假日、调休）正确跳过；与主仓库日历及本地新浪日期比对。
2. **27 个品种是否齐全 + 合约数**：每品种当日有数据，合约数与前一交易日比、与交易所挂牌合约数（`research/data_quality/calendar.listed_contracts_on`）比；新增/消失合约列出。
3. **OHLC 合理、settle 非空**：`low ≤ open,close ≤ high`；价格 > 0；`settle` 非空且 > 0（成交量为 0 的合约只记不算错）；涨跌幅异常（相对 presettle 超阈值）列出。
4. **主力识别（官方路径 + 5% 守卫）**：用引擎 `build_main_map` 规则，价格匹配对象是本地新浪连续序列当日 bar；输出每品种当日主力、是否未识别（沿用前一日）、守卫拦截数、换月事件。**注意**：新浪连续序列当日 bar 在若干日子里是收盘前快照（附录 1 §2.3 的 9 个快照日），所以"最新一天"的主力识别标 `provisional`，下一交易日新浪 bar 定型后复核。
5. **与本地新浪数据差异（只报告）**：同合约同日 OHLC/volume 的偏差、本地缺合约；不触发告警、不影响通过与否。

## 7. 衍生序列（增量）

- **官方主力序列**：沿用 `archive/R8/long_sample.py` 的 `guarded_main_series` 逻辑（5% 守卫，未识别沿用前一日主力）；**复权序列**沿用 R6c `AdjustedSeries`（roll-free）。
- 只对"最近 3 个交易日"允许重算（`provisional` 窗口，因新浪 bar 定型滞后）；更早日期不可变。重算写入日志。
- 一致性测试：增量结果必须与"从头全量重建"逐位相同（周期性自检，写入每日报告）。
- 新浪连续序列由现有正式层的 `daily_update` 更新，**管道只读**；若当日新浪 bar 还没到，则该日主力标 `pending_sina`，下次运行补算。

## 8. 退出码与告警

- 退出码：`0` 正常；`1` 抓取失败（有所/日缺失）；`2` 校验不通过；`3` 发现已入库日期被修订（生成差异报告）。非零时写日志。
- **告警文件** `alerts/ALERT_{date}.md`：**连续 2 个交易日抓取失败**，或**任何校验不通过**，或**发现修订**。内容含原因、受影响所/品种/日期、已做的重试、建议动作。只生成文件，不自动修复，不自动调整任何研究口径。
- 告警渠道（第一版只落文件；是否另推 Notion/邮件，磊定）。

## 9. "连续正常运行 5 个交易日"的定义（shadow 启动门）

某交易日"正常"= 三所当日数据都入库、§6 全部通过、无告警文件、无修订报告、衍生序列更新成功、增量与全量重建一致。**连续 5 个这样的交易日**之后才启动 shadow（`PREREG_SHADOW_300K.md` §7）。中间任一日不正常 → 计数清零。

## 10. 测试与交付（实现阶段）

- 单测：解析器（三所样本文件，含 R8 已归档原始文件）、manifest 追加/不可变、修订检测与差异报告、日历缺口补抓、校验各项（构造坏数据）、退出码与告警触发（连续 2 日）、衍生序列增量 = 全量。
- 回放验证：把种子库里 2026-01-05 → 2026-11-25 按日期逐日"假装每天运行"，增量产出的主力序列必须与 R8 的一次性结果逐位相同。
- 全量 pytest；受保护文件 diff 为空；`historical_backtest.yml` 不动；不写 `paper_book`。

## 11. 需要磊确认的事项

1. **平台**：采用"本机任务计划为主"（推荐），还是先 push 一个探针 workflow 验证 Actions 能否访问（仅作备份来源）？
2. **官方库位置与备份**：`D:\AI\cta-official-data\` 独立本地 git 仓库；是否推到私有远端备份。
3. **大商所自动化**：同意在管道环境装 Playwright 并驱动本机 Chrome（有头最小化）？
4. **运行时间**：首跑 17:30，重试 18:30/20:00/22:00，次日 08:30 补抓；机器需在 17:30 前后保持开机（或接受唤醒定时）。
5. **种子**：把 R8 的 `raw_contract` 迁入官方库作为第 0 天（保留 R8 目录不动）。
6. **告警**：第一版只落文件，够不够。
7. 主仓库是否提交每日校验摘要（体积小），还是只留在官方库。

## 实现记录与偏差（2026-11-26）

**状态**：管道代码已实现（`official_pipeline/`），计划任务已注册（`CTA_Official_Run_1730` / `CTA_Official_Retry_1830` / `CTA_Official_Retry_2000` / `CTA_Official_Retry_2200` / `CTA_Official_Judge_0830`，周一至周五，WakeToRun，StartWhenAvailable）。**shadow 未启动**：5 天计数尚未达标（见下）。

**与设计一致的已确认决定**：本地计划任务；正式库在仓库外 `D:\AI\data\official\`（可用环境变量 `CTA_OFFICIAL_STORE` 覆盖）；仓库只入库哈希清单 `official_pipeline/manifest_repo/hashes_{shfe,czce,dce}.json`；每周备份到 `D:\AI\data\official_backup\`；Playwright 固定 `1.65.2`（`official_pipeline/requirements.txt`）；种子来自 `archive/R8/raw_contract`，逐日校验解压后 sha256 与 manifest 一致才复制（R8 目录只读，未改动）；告警 = `alerts/ALERT_{date}.md` + Windows 气泡通知；日报不入 main。

**实现中的确定与偏差（需磊确认）**：
1. **交易日历**：仓库内没有节假日表。规则：工作日；若三所对该日都明确返回"未发布"（404 / empty），判为**休市**（不计入、不打断 streak）。任何网络错误、HTTP 412、格式异常**都不算休市**，照常告警。
2. **DCE 格式已验证**：原始应答为 JSON。请求为 `POST` JSON 体 `{"tradeDate":"YYYYMMDD","varietyId":"all","tradeType":"1"}`（Content-Type application/json）；表单编码请求返回业务码 500。规范化与 R8 `ingest_dce.py` 相同（仅 10 个品种行，紧凑排序 JSON）。对 2026-11-20 / 11-24 / 11-25 重抓，与 R8 已入库 body 逐字节一致（sha256 相同）。
3. **衍生主力依赖新浪连续缓存的当日 bar**：价格匹配对象是 `.cache/history/{code}0.json`。该缓存由 CTA 日更任务（`daily.yml` → main）生成，本流水线不改写它。若某品种缺当日 bar，判为不正常并跳过衍生（不沿用前一日假装成功）。2026-11-26 本地缓存只到 11-25（M 只到 11-20），因此该日按规则判为异常。需要的动作：每个交易日 08:30 前，本地缓存须已含当日 bar（拉取主仓库 main 或运行日更）；或由磊决定流水线自行拉取新浪 bar（见下方待决定）。
4. **streak 起点**：仅统计 `start_day`（首次运行日 2026-11-26）之后的交易日；种子历史不计入 5 天门槛。streak 按已判定日期排序后末尾连续正常天数重算；正常判定为终局，异常日可被后续重判（如 DCE 恢复）。
5. **判定窗口**：08:30 任务判定窗口内（最近 14 个工作日）所有尚未正常的日期；告警只在首次判定或原因变化时发出，避免每天重复刷屏。
6. **修订**：已入库日若内容变化，原件不覆盖，差异写入 `revisions/`，`run` 返回码 3 并告警；修订记录需人工处理（当前不自动清除）。
7. **DCE 原始应答**：每次 200 应答原样保存在 `D:\AI\data\official\responses\`（仓库外，仅审计用途，不做分析）。

**测试**：`tests/test_official_pipeline.py` 12 项通过（窗口、streak/休市/终局、store 新增/未变/修订、DCE 规范化、种子哈希校验、告警文件、计划任务 XML、路径边界）；全量 `pytest tests/` 584 passed。受保护文件（`universe.json`、`execution_rules.json`、`configs/formal_rule_lock.json`、`.github/workflows/historical_backtest.yml`）无改动。

**待决定**：
- 衍生主力所需的新浪当日 bar 由谁负责：A) 每个交易日 08:30 前拉取主仓库 main 的缓存（不改代码）；B) 管道自行用免费新浪源补当日 bar 到独立缓存（需改 `build_official_pack` 的输入路径，属于口径相关改动，需单独确认）。
- shadow 启动门 = 连续 5 个"正常"交易日；在 A/B 未定之前，计数不会推进。

## 同步模式变更（2026-11-26，磊）

磊不能保证每个交易日 08:30 同步本地。Sina 当日 bar 由 GitHub 日更（`daily.yml`）累计在仓库里，磊在需要时同步到本地。因此判定改为**补判**，不再绑定 08:30：

- **补判范围**：从 `start_day`（2026-11-26）到昨天的全部工作日。未判定且非休市的日期逐一判定。窗口不再是"最近 14 天"，几天不同步也不会丢日。
- **三种状态**：
  - `normal` / `abnormal`：按原规则判定，异常则告警，计入 streak。
  - `pending`：原始数据完整且通过校验，但 Sina 连续缓存尚未同步到该日（缓存全局最新日期早于该日）。**不判对错、不告警、不计入 streak**，记入 `state.json` 的 `pending`。
  - `gap`：缓存已同步到该日或更晚，但个别品种仍缺该日 bar。这是真缺口，判为异常（例如 M 的 11-21 至 11-25 缺口）。
- **08:30 任务**保留为尽力而为：到点补判一次；未同步时只记 pending，不打扰。同步后手动运行 `python -m official_pipeline judge` 即可补判。
- **status** 会显示 `pending_waiting_for_sina_sync` 与 `sina_cache_synced_to`，便于看当前同步到哪一天。

**待确认**：
- 本地 main 当前领先 origin，GitHub 日更产物（`.cache/history`）要在本地同步到位，需要先从 origin 拉取并合并。这一步未执行，也未推送。
- 此前理解为"GitHub 累计"指 Sina 日更缓存。官方原始数据仍按决定 2 留在本地（仓库只存哈希）。如需把官方原始数据也放到 GitHub，请说明。

## 存储位置变更：官方数据进入 GitHub 私有仓库（2026-11-26，磊）

磊确认：官方原始数据要在 GitHub 上累计，需要时同步到本地。以下替代决定 2 中"仓库外、仅哈希入库"的做法：

- **私有仓库**：`12poing-a11y/cta-official-data`（private）。正式库 `D:\AI\data\official\` 本身就是该仓库的工作目录（`git` 远程为 origin）。
- **入库内容**：`raw/`（gz 原始 body + manifest）、`revisions/`（修订原件）、`state.json`、`reports/`、`alerts/`、`derived/`。`responses/`（DCE 原始应答）与 `logs/` 通过 `.gitignore` 排除，它们与 `raw/` 内容重复或仅用于排查。
- **主仓库**：`official_pipeline/manifest_repo/` 仍保留哈希清单副本（审计用），代码与文档在主仓库。
- **自动同步**：`run` 与 `judge` 结束时自动执行 `sync`（提交 → `pull --rebase` → `push`）。推送失败只记日志，本地保留提交，下次运行再推。
- **手动命令**：
  - `python -m official_pipeline verify`：逐个重算已存 body 的 sha256 与清单比对，只读，给出问题清单。
  - `python -m official_pipeline sync`：立即提交并推送。
  - `python -m official_pipeline pull`：拉取（换机或同步到本地时用）。

**准确性依据（已执行）**：
- 本地库 `verify`：7939 个已存 body 全部与清单 sha256 一致，0 问题。
- 全新 `git clone` 到临时目录后，对克隆出的库运行 `verify`：7939 个全部一致，0 问题。这证明 GitHub 上的数据与本地一致，同步链路可用。

**未变更**：主仓库 `main` 仍领先 origin 32 个提交，**未推送**（磊确认暂不推送）。
