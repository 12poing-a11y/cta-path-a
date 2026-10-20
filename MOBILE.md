# 手机无电脑：每日自动验证

可以。**不依赖你的电脑开机**；跑在 GitHub Actions 云端。

## 你必须先做一次（手机浏览器）

打开：https://github.com/12poing-a11y/cta-path-a/settings/secrets/actions  

添加 Secrets：

| Name | 值 |
|------|-----|
| `IFIND_AUTH_TOKEN` | primary iFinD MCP Key（新 Key） |
| `IFIND_AUTH_TOKEN_BACKUP` | backup Key（旧 Key，可选） |
| `NOTION_TOKEN` | Notion Integration Secret（可选，用于写台账） |

Workflows 已设 `IFIND_ACTIVE_SLOT=primary`（日报 Fetch / 历史回测等）。一般**不必**再加这个 Secret。

Notion Integration 需连接「CTA日信号台账 / CTA回测报告」。

当前仓库若 Secrets 为空，定时任务会失败。

## 仓位规则（路径A）

- Equity ¥20万；同日最多 **3** 个品种  
- 总名义敞口 ≤ 权益 **50%**  
- 改规则：编辑仓库 `universe.json` 的 `max_positions` / `max_gross_exposure_pct`

## 之后手机怎么用

1. **自动**：工作日约 15:30（北京时间）跑日报；周日约 20:00 周回测  
2. **手动**：GitHub App → `cta-path-a` → Actions → 选 workflow → **Run workflow**  
3. **看结果**：Actions 日志 / Artifacts；或仓库 `archive/`；或 Notion；或 https://12poing-a11y.github.io/（需同步 data）

## 注意

- GitHub cron 可能延迟几分钟到十几分钟  
- 国内节假日仍可能触发；无行情时报告会异常或空  
- 行情：先拉新浪和腾讯日线；根数不足、缺 OHLC，或最后一根早于 12 个自然日，才用 iFinD
- iFinD：优先 primary；额度不足时**当次进程**切 backup，下次跑仍从 primary 起；两 Key 都没额度则失败 
