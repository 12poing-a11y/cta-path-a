# 哪些量化与期权策略真正有用：面向 cta-path-a 的证据综述

> 适用对象：中国商品期货 CTA 纸面研究台，20 万元个人账户，日线到周线频率，不做托管机房或高频交易。
> 本文只引用检索到原文句子的结论；没有原文数字的地方标为“未找到”，作者自己的推断标为“推断”。

## 一、结论先行

长期真正有效的策略，背后都有一个说得清的理由：要么是承担了别人不愿承担的风险而拿到补偿，要么是因为制度限制，价格偏差没人能纠正。按这个标准，证据最扎实的三类收益来源是**期限结构（carry）、动量/趋势、基差动量**。在中国商品期货市场，已有研究确认动量和 carry 的盈利能力很强 [[1](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)]；在散户主导、有准入壁垒的环境里，期限结构和动量溢价一直存在，而偏度、波动率、流动性和对冲压力溢价都被时变保证金和严格限仓扭曲了 [[2](https://www.researchgate.net/publication/338118608_The_untold_story_of_commodity_futures_in_China)]。

期权方面：股指期权卖方的超额收益近 15 年已经和零没有统计差别 [[3](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf)]。拿来做尾部保护时，AQR 认为趋势跟踪比买看跌期权更省成本 [[4](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/Journal-of-Systematic-Investing-Vol-1-Issue-1--Tail-Risk-Hedging-AQR.pdf?sc_lang=en)]。所以对一个 CTA 账户来说，期权最多只是辅助工具，不该作为主要收益来源，也不该常备买保护。

对 cta-path-a 的含义很直接。项目自己的十年近似重放显示，20/60 日动量配 0.8 倍 ATR 止损长期不赚钱，平均持仓只有两三天，而文献里能赚钱的动量持有期是 1–12 个月。下一步不该继续堆价格过滤器，而应该：(1) 把趋势改成持有更久、按波动率定仓；(2) 新增一个独立的 carry/基差动量袖套；(3) 用十年以上的面板数据加试验次数折扣来做晋级判断。

## 二、证据强度排序总表

下表按“证据强度 × 对本项目的可行性”排序。“证据强度”综合考虑样本长度、跨市场一致性和是否有中国实证。

| 排名 | 策略/方法 | 证据强度 | 中国实证 | 扣成本后（日/周频） | 20 万元可行性 | 与现有趋势策略的关系 | 建议 |
|---|---|---|---|---|---|---|---|
| 1 | 期限结构 / carry | 高 | 显著为正，具体数字未找到 | 未找到 | 中：需按主力/次主力展期 | 低相关（定性） | **新增独立袖套** |
| 2 | 时间序列动量 / 趋势 | 高（百年以上） | 稳健为正，具体数字未找到 | 日内不行；日频以上未找到数字 | 中：分散度受限 | 本身就是 | **保留，改长持有期** |
| 3 | 基差动量 | 中高 | 各展期法下都盈利 | 未找到 | 中：需多合约数据 | 未找到 | 并入 carry 袖套测试 |
| 4 | 横截面动量 | 中 | 稳健为正，行业效应占比大 | 未找到 | 低：多空需要更多品种 | 高相关 | 暂缓 |
| 5 | 波动率目标 | 中（降尾部，不提 Sharpe） | 动量上有改善证据 | 股票因子上存疑 | 高 | 风险层工具 | **采用（仓位层）** |
| 6 | 卖期权 / 信用价差 | 中，正在衰减 | 未找到 | 未找到 | 低：保证金与跳空风险 | 尾部方向相反（推断） | 小样本观察 |
| 7 | 常态买保护 | 低（长期拖累） | 未找到 | 负（推断） | 低 | 功能重叠 | 不做 |
| 8 | 偏度/流动性/对冲压力 | 低（在中国被扭曲） | 不稳健 | 未找到 | — | 未找到 | 不做 |
| 9 | 库存/仓单/会员持仓 | 未找到 | 未找到 | 未找到 | 数据可得 | 未找到 | 自行验证（R13） |

说明：“中国实证”一栏写“具体数字未找到”，表示文献结论是显著为正，但本次没拿到论文表格里的年化收益、Sharpe 和最大回撤。

## 三、中国商品期货因子：carry、基差动量与动量

**Carry 对实现细节不敏感，这是好事。** Bianchi 等用了四种展期方法，发现 carry、动量和基差动量溢价都不受展期方法影响 [[1](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)]；排序加权和强度加权相对等权也没有明显改善 [[1](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)]。对小项目来说，这意味着最简单的等权实现就够了，不需要复杂优化，也不容易过拟合。

**有两个现实约束。** 第一，中国的近月合约只占全市场持仓约 10%、成交约 3%，照搬美国文献的近月做法不可行 [[1](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)]，必须用主力和次主力合约来构造期限结构。第二，中国 carry 的收益低于美国，原因是在中国它没有因承担股票波动率风险而得到补偿 [[5](https://3a1e3a2c-5fbb-40af-8aa5-f0cb4cdd9ea5.filesusr.com/ugd/b57550_b8bb450c1d894814be9e8855ab9c6861.pdf)]。所以预期要放低。

**基差动量**最早由 Boons 和 Prado 提出，在美国数据上预测能力明显强于单看基差或动量 [[6](https://finm-32800.github.io/_downloads/049399c24fc42f7ce33438fcf7181b9b/BoonsPrado2019BasisMomentum.pdf)]。Bianchi 等是第一篇在中国检验它的研究：除常规展期下第 2、第 4 近月合约这两个例外，在所有展期方法下都盈利 [[1](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)]。这几类溢价都暴露在下行风险中，一般在市场上行状态下更高 [[1](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)]。

**动量的频率很关键。** Yang、Goncu 和 Pantelous 用分钟数据和逐品种的真实成本估计，结论是动量和反转能长期带来稳健收益，但日内策略的超额收益不够覆盖高频交易成本 [[7](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3069253)]。cta-path-a 现在 26% 的交易当天进当天出，实际上处在“成本吃掉优势”的区间。另外，中国数据显示管理波动率能明显改善商品动量 [[8](https://www.researchgate.net/publication/349210239_Managing_volatility_in_commodity_momentum)]；引入尾部风险择时后，TSMOM 的样本外 Sharpe 也有统计显著的提升 [[9](https://www.researchgate.net/publication/340610529_Asymmetry_Tail_Risk_and_Time_Series_Momentum)]。

但要注意，行业效应解释了中美商品动量利润的很大一部分，多空动量的风险可能比原来以为的更大 [[10](https://openreview.net/pdf/8d1977572e466bab9fc0317b7d34e3b0226d524a.pdf)]。这也是 cta-path-a 现有“每板块最多 1 个”规则合理的地方。

## 四、趋势跟踪：长期证据很强，近年回撤也很深

时间序列动量的原始研究覆盖 58 个流动性好的期货 [[11](https://www.johnhcochrane.com/s/Moskowitz_time_series_momentum.pdf)]，收益持续性出现在 1–12 个月，更长周期会部分反转 [[12](https://www.rpmfonder.se/s/Time-Series-Momentum-Moskowitz-et-al.pdf)]。AQR 把证据延伸到 1880 年，趋势跟踪一百多年来收益为正、与传统资产相关性低 [[13](https://www.jkgcapital.com/wp-content/uploads/2017/02/AQR-A-Century-of-Trend-Following-Investing.pdf)]。CFM 的两百年研究在剔除市场整体上涨后，超额收益的 t 值 1960 年以来约为 5、1800 年以来约为 10 [[14](https://ui.adsabs.harvard.edu/abs/2014arXiv1404.3274L/abstract)]。

**但长期有效不等于每年都赚钱。** 有资料显示，截至 2025 年 4 月 30 日的一年里，相关 SG 指数下跌 18.7%，是其 25 年以上历史中最差的 12 个月 [[15](https://mebfaber.com/wp-content/uploads/2025/05/the_patience_premium_5028-1747850090.pdf?)]（原文没写明是 SG Trend 还是 SG CTA 指数，引用时要注意）。同一种“趋势”在不同管理人手里差别很大：SG Trend 成分里，每年最好与最差的管理人通常相差约 10 个百分点，有些年份达到两倍 [[16](https://www.man.com/insights/deep-dive-trend-following)]。也就是说，实现细节（持有周期、定仓、品种）决定了大部分结果。

业界的标准做法以 Carver 为代表：预测值标准化，仓位与预测值成正比、与波动率成反比，目标是恒定风险而不是恒定名义 [[17](https://github.com/chomperflower0816-svg/Backtest-on-Robert-Carver-index)]。cta-path-a 现在是“同向就开、固定 ATR 止盈止损”，和这个框架差别很大。

**衰减**：股票因子发表后，归因于知情交易的收益下降估计为 32%，样本内收益越高的预测变量下降越多 [[18](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623)]。这条证据来自股票，不是期货，但“论文数字要打折”的原则同样适用。中国 CTA 私募的策略结构和业绩数据，本次未找到。

## 五、期权：卖波动率在衰减，买保护不划算

**卖方。** 一项研究 1987–2025 年 S&P 500 期权的论文发现，风险溢价在 2012 年前后出现结构性断点 [[19](https://www.dew-becker.org/documents/option_decline.pdf)]。更早的长期数据里，1986–2015 年 CBOE PutWrite 指数每年跑赢 BuyWrite 约 1.1% [[20](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-PutWrite-vs-BuyWritevF.pdf)]。商品上，农产品期货存在负的方差风险溢价，说明市场愿意付钱对冲波动率上升 [[21](http://oxfordjournals.org/erae/article-pdf/50/4/1428/51832487/jbad026.pdf)]，而上行和下行分量的重要性因市场而异，与套保需求有关 [[22](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3416414)]。**国内场内商品期权的 IV 与 RV 之差、买卖价差和流动性的系统实证，本次未找到**，所以在自己用本地数据验证之前，不该假设豆粕、白糖等期权有可收割的溢价。

另外（推断）：卖期权是做空凸性，趋势跟踪是做多凸性，两者在尾部会朝相反方向走。往 CTA 账户里叠加卖方策略，会抵消趋势本来的危机收益。

**买保护。** AQR 把长期持有虚值看跌期权当作直接尾部对冲，把多资产趋势跟踪当作间接对冲 [[23](https://www.aqr.com/Insights/Research/White-Papers/Tail-Risk-Hedging-Contrasting-Put-and-Trend-Strategies)]，结论是成本优势在趋势一边。Universa 的案例常被拿来反驳：泄露文件显示它 2008–2019 年资本年化回报 105% [[24](https://www.businessinsider.com/universa-investing-strategy-black-swan-taleb-fund-tail-risk-hedging-2020-10?)]。但这是对冲资本本身的回报，不是整个组合的回报（推断）；CalPERS 在 2019 年 10 月终止了这个项目，正好错过 2020 年 3 月约 10 亿美元的收益 [[25](https://inv.institutionalinvestor.com/article/2bsx81qp5g2t3adglle68/portfolio/nassim-taleb-and-universa-versus-the-world)]。这恰恰说明，常备保险很难长期坚持。

**期权替代止损**：学术或研报实证未找到。推断是：只在重大事件窗口（节假日长假、USDA 报告）前临时买短期虚值期权可能划算，常态滚动买会吞掉趋势收益的一大部分。

## 六、组合与风控：哪些方法真能降回撤

**波动率目标：降尾部，不提升商品的 Sharpe。** Man Group 和 Duke 的研究用 1927–2017 年、60 多种资产的数据发现，只有股票、信用这类风险资产的 Sharpe 有提升 [[26](https://www.man.com/insights/the-impact-of-volatility-targeting)]，而对债券、外汇和商品影响可以忽略 [[27](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538)]；但它在所有资产类别上都减少了极端收益 [[27](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538)]。股票因子上的“波动管理组合”在样本外失效、扣成本后也站不住 [[28](https://lbsresearch.london.edu/id/eprint/3716/1/The%20Journal%20of%20Finance%20-%202024%20-%20DeMIGUEL%20-%20A%20Multifactor%20Perspective%20on%20Volatility%E2%80%90Managed%20Portfolios.pdf)]。结论：在仓位层按波动率缩放，目的是让风险预算稳定、尾部变薄，**别指望靠它提高收益**。

**多策略分散是最直接的降回撤手段。** 跨资产分散的价值加动量组合 Sharpe 很高 [[29](https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere)]，这些风格溢价在商品等资产上同样存在 [[30](https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Understanding-Style-Premia.pdf)]。实际产品里也有同时收割价值、动量、carry、防御四类溢价的做法 [[31](https://www.morningstar.com/funds/xnas/qspix/analysis)]。中国商品上 carry 与趋势的具体相关系数，本次未找到，需要自己算。

**止损不是天然有益。** Kaminski 和 Lo 证明：价格是随机游走时，简单止损一定降低期望收益；只有存在动量时止损才可能有价值 [[32](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338)]，而且在较低采样频率下，部分止损规则能在提高收益的同时降低波动 [[33](https://www.scribd.com/document/240278564/A-Lo-When-Do-Stop-Loss-Rules-Stop-Losses)]。这和 cta-path-a 的观察一致：0.8 倍 ATR 这种在日内噪声范围内的止损，砍掉的是噪声而不是趋势。吊灯/ATR 移动止损和回撤刹车，本次没有找到同行评审的独立实证，应当作为待检验参数纳入试验登记，不能默认有效。

## 七、小资金与统计门槛

**20 万元的主要代价是分散度，不是优势本身。** 小账户放弃的是合约太大、拿不起的品种，而合约大小和信号质量没有必然联系 [[34](https://plaintape.substack.com/i/202972602/layer-1-what-a-small-account-actually-held-and-tracked-the-heart)]。一项从业者模拟显示，2.5 万美元账户平均每天只持有约 5 个品种，10 万美元约 12 个 [[35](https://plaintape.substack.com/p/how-much-does-it-really-cost-to-hold)]。20 万元约合 2.8 万美元，大致落在 5 个品种左右（国内合约面值较小，实际可能稍好）。这个来源是博客而非论文。Carver 在 AFTS 里专门讨论了有限资金下如何做市场分散和模型分散 [[36](https://algoadvantage.substack.com/p/033-rob-carver-the-comprehensive)]。

**统计门槛比想象的高。** 传统 hold-out 检验在投资回测里不可靠，这是 PBO 框架提出的原因 [[37](https://www.davidhbailey.com/dhbpapers/backtest-pro.pdf)]。按年化 Sharpe 标准误约 √((1+SR²/2)/T) 推算（推断）：真实 Sharpe 为 0.5 的策略，要做到 95% 显著需要约 18 年数据；即使只试过 1 次、只要求单边显著，也要约 12 年；试过的参数组合越多，需要的年数越长。cta-path-a 现在用 215 个交易日的成绩来晋级参数（例如 4%/6% 动量门槛），在统计上无法和噪声区分。

## 八、接入 cta-path-a 的行动建议与证据缺口

| 优先级 | 行动 | 依据 | 对应清单 | 晋级判据 |
|---|---|---|---|---|
| 1 | 先修回测引擎 | 数字不可信，后面的比较都没意义 | R0–R7 | 逐笔审计 0 差异 |
| 2 | 趋势改为长持有期 + 波动率定仓 | 1–12 个月动量持续；日内成本吃掉优势 | R9–R11 | 十年面板，Stress 成本下 Calmar 不低于现行 |
| 3 | 新增 carry / 基差动量袖套 | 中国实证最稳健，对实现细节不敏感 | R14 | 长样本 Sharpe ≥ 0.4，与趋势相关 < 0.3 |
| 4 | 品种池按单手风险筛选到 10–15 个小合约 | 小账户损失的是分散度 | R10、R12 | 实际单笔风险接近目标 |
| 5 | 席位、仓单、库存自行验证 | 文献证据未找到 | R13 | seats 相对 base 的 Sharpe 提升 ≥ 0.2 |
| 6 | 期权只做小样本信用价差观察 | 卖方衰减，国内实证未找到 | F2 | 先积累样本，不晋级 |
| 7 | 冻结形态类、Gamma、ML 旁支 | 无长期证据支撑 | — | — |

**证据缺口**（下一轮值得补的）：(1) Bianchi 等 2019、Fan & Zhang、Yang 等 2018 的全文表格，用来拿到中国市场各因子的年化收益、Sharpe、最大回撤和成本假设；(2) 国内期货公司金工研报（中信、国泰君安、华泰、东证）对 carry、仓单、会员持仓因子的回测；(3) 国内场内商品期权的 IV–RV 与买卖价差实证；(4) SG CTA / SG Trend 指数分年数据；(5) 中国 CTA 私募的策略结构与业绩。前三项可以直接用项目已有的数据源（TqSdk、交易所日报、期权链采集）自己算，比等论文更可靠。


## 参考文献

\[1\] [https://acfr.aut.ac.nz/\_\_data/assets/pdf\_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf](https://acfr.aut.ac.nz/__data/assets/pdf_file/0010/265375/A-Practical-Look-at-Commodity-Risk-Factors-in-China.pdf)

\[2\] [https://www.researchgate.net/publication/338118608\_The\_untold\_story\_of\_commodity\_futures\_in\_China](https://www.researchgate.net/publication/338118608_The_untold_story_of_commodity_futures_in_China)

\[3\] [https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf](https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf)

\[4\] [https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/Journal-of-Systematic-Investing-Vol-1-Issue-1--Tail-Risk-Hedging-AQR.pdf?sc\_lang=en](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/Journal-of-Systematic-Investing-Vol-1-Issue-1--Tail-Risk-Hedging-AQR.pdf?sc_lang=en)

\[5\] [https://3a1e3a2c-5fbb-40af-8aa5-f0cb4cdd9ea5.filesusr.com/ugd/b57550\_b8bb450c1d894814be9e8855ab9c6861.pdf](https://3a1e3a2c-5fbb-40af-8aa5-f0cb4cdd9ea5.filesusr.com/ugd/b57550_b8bb450c1d894814be9e8855ab9c6861.pdf)

\[6\] [https://finm-32800.github.io/\_downloads/049399c24fc42f7ce33438fcf7181b9b/BoonsPrado2019BasisMomentum.pdf](https://finm-32800.github.io/_downloads/049399c24fc42f7ce33438fcf7181b9b/BoonsPrado2019BasisMomentum.pdf)

\[7\] [https://papers.ssrn.com/sol3/papers.cfm?abstract\_id=3069253](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3069253)

\[8\] [https://www.researchgate.net/publication/349210239\_Managing\_volatility\_in\_commodity\_momentum](https://www.researchgate.net/publication/349210239_Managing_volatility_in_commodity_momentum)

\[9\] [https://www.researchgate.net/publication/340610529\_Asymmetry\_Tail\_Risk\_and\_Time\_Series\_Momentum](https://www.researchgate.net/publication/340610529_Asymmetry_Tail_Risk_and_Time_Series_Momentum)

\[10\] [https://openreview.net/pdf/8d1977572e466bab9fc0317b7d34e3b0226d524a.pdf](https://openreview.net/pdf/8d1977572e466bab9fc0317b7d34e3b0226d524a.pdf)

\[11\] [https://www.johnhcochrane.com/s/Moskowitz\_time\_series\_momentum.pdf](https://www.johnhcochrane.com/s/Moskowitz_time_series_momentum.pdf)

\[12\] [https://www.rpmfonder.se/s/Time-Series-Momentum-Moskowitz-et-al.pdf](https://www.rpmfonder.se/s/Time-Series-Momentum-Moskowitz-et-al.pdf)

\[13\] [https://www.jkgcapital.com/wp-content/uploads/2017/02/AQR-A-Century-of-Trend-Following-Investing.pdf](https://www.jkgcapital.com/wp-content/uploads/2017/02/AQR-A-Century-of-Trend-Following-Investing.pdf)

\[14\] [https://ui.adsabs.harvard.edu/abs/2014arXiv1404.3274L/abstract](https://ui.adsabs.harvard.edu/abs/2014arXiv1404.3274L/abstract)

\[15\] [https://mebfaber.com/wp-content/uploads/2025/05/the\_patience\_premium\_5028-1747850090.pdf?](https://mebfaber.com/wp-content/uploads/2025/05/the_patience_premium_5028-1747850090.pdf?)

\[16\] [https://www.man.com/insights/deep-dive-trend-following](https://www.man.com/insights/deep-dive-trend-following)

\[17\] [https://github.com/chomperflower0816-svg/Backtest-on-Robert-Carver-index](https://github.com/chomperflower0816-svg/Backtest-on-Robert-Carver-index)

\[18\] [https://papers.ssrn.com/sol3/papers.cfm?abstract\_id=2156623](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623)

\[19\] [https://www.dew-becker.org/documents/option\_decline.pdf](https://www.dew-becker.org/documents/option_decline.pdf)

\[20\] [https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-PutWrite-vs-BuyWritevF.pdf](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-PutWrite-vs-BuyWritevF.pdf)

\[21\] [http://oxfordjournals.org/erae/article-pdf/50/4/1428/51832487/jbad026.pdf](http://oxfordjournals.org/erae/article-pdf/50/4/1428/51832487/jbad026.pdf)

\[22\] [https://papers.ssrn.com/sol3/papers.cfm?abstract\_id=3416414](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3416414)

\[23\] [https://www.aqr.com/Insights/Research/White-Papers/Tail-Risk-Hedging-Contrasting-Put-and-Trend-Strategies](https://www.aqr.com/Insights/Research/White-Papers/Tail-Risk-Hedging-Contrasting-Put-and-Trend-Strategies)

\[24\] [https://www.businessinsider.com/universa-investing-strategy-black-swan-taleb-fund-tail-risk-hedging-2020-10?](https://www.businessinsider.com/universa-investing-strategy-black-swan-taleb-fund-tail-risk-hedging-2020-10?)

\[25\] [https://inv.institutionalinvestor.com/article/2bsx81qp5g2t3adglle68/portfolio/nassim-taleb-and-universa-versus-the-world](https://inv.institutionalinvestor.com/article/2bsx81qp5g2t3adglle68/portfolio/nassim-taleb-and-universa-versus-the-world)

\[26\] [https://www.man.com/insights/the-impact-of-volatility-targeting](https://www.man.com/insights/the-impact-of-volatility-targeting)

\[27\] [https://papers.ssrn.com/sol3/papers.cfm?abstract\_id=3175538](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3175538)

\[28\] [https://lbsresearch.london.edu/id/eprint/3716/1/The%20Journal%20of%20Finance%20-%202024%20-%20DeMIGUEL%20-%20A%20Multifactor%20Perspective%20on%20Volatility%E2%80%90Managed%20Portfolios.pdf](https://lbsresearch.london.edu/id/eprint/3716/1/The%20Journal%20of%20Finance%20-%202024%20-%20DeMIGUEL%20-%20A%20Multifactor%20Perspective%20on%20Volatility%E2%80%90Managed%20Portfolios.pdf)

\[29\] [https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere](https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere)

\[30\] [https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Understanding-Style-Premia.pdf](https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Understanding-Style-Premia.pdf)

\[31\] [https://www.morningstar.com/funds/xnas/qspix/analysis](https://www.morningstar.com/funds/xnas/qspix/analysis)

\[32\] [https://papers.ssrn.com/sol3/papers.cfm?abstract\_id=968338](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338)

\[33\] [https://www.scribd.com/document/240278564/A-Lo-When-Do-Stop-Loss-Rules-Stop-Losses](https://www.scribd.com/document/240278564/A-Lo-When-Do-Stop-Loss-Rules-Stop-Losses)

\[34\] [https://plaintape.substack.com/i/202972602/layer-1-what-a-small-account-actually-held-and-tracked-the-heart](https://plaintape.substack.com/i/202972602/layer-1-what-a-small-account-actually-held-and-tracked-the-heart)

\[35\] [https://plaintape.substack.com/p/how-much-does-it-really-cost-to-hold](https://plaintape.substack.com/p/how-much-does-it-really-cost-to-hold)

\[36\] [https://algoadvantage.substack.com/p/033-rob-carver-the-comprehensive](https://algoadvantage.substack.com/p/033-rob-carver-the-comprehensive)

\[37\] [https://www.davidhbailey.com/dhbpapers/backtest-pro.pdf](https://www.davidhbailey.com/dhbpapers/backtest-pro.pdf)
