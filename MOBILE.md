# 手机无电脑：每日自动验证

可以。**不依赖你的电脑开机**；跑在 GitHub Actions 云端。

## 你必须先做一次（手机浏览器）

打开：https://github.com/12poing-a11y/cta-path-a/settings/secrets/actions  

添加 Secrets：

| Name | 值 |
|------|-----|
| `IFIND_AUTH_TOKEN` | 新 iFinD MCP Key |
| `IFIND_AUTH_TOKEN_BACKUP` | 旧 Key（可选） |
| `NOTION_TOKEN` | Notion Integration Secret（可选，用于写台账） |

Notion Integration 需连接「CTA日信号台账 / CTA回测报告」。

当前仓库若 Secrets 为空，定时任务会失败。

## 之后手机怎么用

1. **自动**：工作日约 15:30（北京时间）跑日报；周日约 20:00 周回测  
2. **手动**：GitHub App → `cta-path-a` → Actions → 选 workflow → **Run workflow**  
3. **看结果**：Actions 日志 / Artifacts；或仓库 `archive/`；或 Notion；或 https://12poing-a11y.github.io/（需同步 data）

## 注意

- GitHub cron 可能延迟几分钟到十几分钟  
- 国内节假日仍可能触发；无行情时报告会异常或空  
- iFinD 额度耗尽会切 backup；都没额度则失败  
