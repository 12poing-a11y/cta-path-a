# Gamma Wall：数据源、调用方式与调用量

## 数据源优先级（V1）

1. **免费主源：AkShare 郑商所日频期权接口** `option_hist_czce`。CF/SR 的期权日行情提供合约代码、结算价、持仓量（空盘量）、Delta、隐含波动率等字段。
2. **免费标的价格：AkShare 新浪单合约日线** `futures_zh_daily_sina(symbol="CF2701")`。必须使用目标交割月单合约，不允许用 CF0 主连替代。
3. **不调用 iFinD / Wind / Tushare**：V1 日频采集不读取现有付费 Secrets，不产生这些供应商的 API 计费或额度消耗。
4. 新浪商品期权 T 型链保留作备用/交叉验证；V1 主计算使用郑商所日频接口，因为其字段包含 OI 与 IV。

## 每次调用量（单合约、单交易日）

- 期权：`option_hist_czce(symbol="棉花期权", trade_date="YYYYMMDD")` **1 次**。接口返回该品种当日全期权合约，本地筛选 CF2701 对应 CF701 系列。
- 标的：`futures_zh_daily_sina(symbol="CF2701")` **首次 1 次**，之后命中本地缓存；缓存不存在时重新请求。
- Greeks/GEX/墙位/迁移/绘图：全部本地计算，**0 次外部 API 调用**。
- 同一交易日重复运行：命中期权原始快照和期货日线缓存，正常 **0 次外部 API**。
- 每天首次跑一个合约：通常 **1 次外部 API**；首次初始化/缓存清理后最多 **2 次**。
- CF2701 + SR2701 每日运行：通常 **2 次外部 API**，首次最多 **4 次**。
- 60 日历史回填：期权端按交易日每个交易日 1 次；CF/SR 两品种约 120 次。期货日线按合约首次 1 次，之后缓存。
- 以上是代码逻辑调用数，不是供应商承诺的 HTTP 请求数；AkShare 重试、重定向可能使底层请求数不同。

## 重要口径与限制

- 期权到期日必须由交易所合约规则/交易日历核实，命令行显式传入 `--expiry`，不自动猜到期日。
- IV 为百分数时自动除以 100；OI 按郑商所期权日行情的手数处理；乘数 CF=5、SR=10。
- Call 侧画在零轴上方、Put 侧画在零轴下方，只为对称展示两侧 Gamma 集中度，**不是 dealer 持仓方向**。
- OI 不含持仓方身份，V1 不发布真实 Dealer Net GEX，也不伪造 Gamma Flip。净 GEX 只能作为明确假设情景。
- 历史快照从部署日起累积，不虚构历史墙位。回填需按真实交易日逐日请求。

## 研究台调用

1. 本地拉取仓库最新 main。
2. 安装依赖：`pip install -r requirements.txt`（研究台本身还需项目原有 Streamlit/Plotly 运行环境）。
3. 启动：`streamlit run desk/app.py`。
4. 页面顶部选择「Gamma 结构」，选择 CF2701 或 SR2701，填入经核实的期权到期/最后交易日，点击「拉取并计算当日 Gamma 快照」。
5. 后续交易日重复点击；系统按交易日落盘，迁移图会逐日积累。

## 本地命令行调用


~~~bash
python gamma_wall.py --contract CF2701 --expiry YYYY-MM-DD
python gamma_wall.py --contract CF2701 --expiry YYYY-MM-DD --date YYYY-MM-DD
python gamma_wall.py --contract SR2701 --expiry YYYY-MM-DD
python -m pytest tests/test_gamma_wall.py -q
~~~

结果保存至 `.cache/gamma_wall/CF2701/YYYY-MM-DD.json`。不提交密钥，不访问付费接口。
