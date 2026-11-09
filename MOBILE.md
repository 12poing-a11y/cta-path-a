# 手机无电脑：每日自动验证

可以。**不依赖你的电脑开机**；跑在 GitHub Actions 云端。

## 你必须先做一次（手机浏览器）

打开：https://github.com/12poing-a11y/cta-path-a/settings/secrets/actions  

添加 Secrets：

| Name | 值 |
|------|-----|
| `IFIND_AUTH_TOKEN` | primary iFinD MCP Key（免费源不足时补日线） |
| `IFIND_AUTH_TOKEN_BACKUP` | backup Key（可选） |
| `NOTION_TOKEN` | Notion Integration Secret（可选，写台账） |
| `FUYAO_API_KEY` | 可选：扶摇合约日线补洞（无则跳过） |
| `TQ_USER` / `TQ_PASS` | 可选：天勤补洞（无则跳过） |

Workflows 已设 `IFIND_ACTIVE_SLOT=primary`（日报 Fetch / 历史回测等）。一般**不必**再加这个 Secret。

Notion Integration 需连接「CTA日信号台账 / CTA回测报告」。

`IFIND_AUTH_TOKEN` 为空时，依赖 iFinD 补缺的任务可能失败；扶摇/天勤为软依赖，缺省不拖垮日更。

## 仓位规则（路径A）

- Equity ¥20万；同日最多 **3** 个品种  
- 总名义敞口 ≤ 权益 **50%**  
- 改规则：编辑仓库 `universe.json` 的 `max_positions` / `max_gross_exposure_pct`

## 之后手机怎么用

1. **自动**：工作日约 15:30（北京时间）跑日报；周六约 09:00 周回测  
2. **手动**：GitHub App → `cta-path-a` → Actions → 选 workflow → **Run workflow**  
3. **看结果**：Actions 日志 / Artifacts；或仓库 `archive/`；或 Notion；或 https://12poing-a11y.github.io/（需同步 data）

## 注意

- GitHub cron 可能延迟几分钟到十几分钟  
- 国内节假日仍可能触发；无行情时报告会异常或空  
- 行情：先拉新浪和腾讯日线；根数不足、缺 OHLC，或最后一根早于 12 个自然日，才用 iFinD
- iFinD：优先 primary；额度不足时**当次进程**切 backup，下次跑仍从 primary 起；两 Key 都没额度则失败 
