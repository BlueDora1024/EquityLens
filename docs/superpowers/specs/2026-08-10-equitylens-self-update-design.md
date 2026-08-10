# EquityLens 内置更新设计

## 目标

EquityLens 在不阻塞启动、不触碰用户 SQLite 与配置的前提下，展示当前构建身份，发现 GitHub 正式 Release，并按本机架构完成下载、SHA256 校验、应用替换与自动重启。

## 产品行为

- “设置 → 高级 → 版本与更新”展示版本、Release Tag、Git SHA 与架构。
- 启动后异步检查最新正式 Release；网络失败保持安静，不影响主窗口。
- 有新版本时展示轻量更新弹层，包含版本号和简短更新说明，可“稍后”或“下载并更新”。
- 手动检查始终给出明确结果；下载阶段显示进度，校验或安装失败可重试。
- 更新只替换当前 `EquityLens.app`，不读取、迁移或删除 Application Support 中的数据库、日志和配置。

## 安全边界

- 仅信任 `BlueDora1024/EquityLens` 的 HTTPS GitHub Release API。
- 仅接受与当前 CPU 架构严格匹配的版本化 ZIP 和对应 `.sha256`。
- 解压前校验摘要；解压后校验 bundle identifier、版本、架构和 codesign 完整性。
- 外部 `/bin/zsh` 更新器等待主进程退出后原位替换；失败时恢复备份。
- 更新脚本和临时文件位于系统临时目录，不包含 API Key、Token、股票或历史结果。

## Release 约定

- 正式 Tag 使用 `vMAJOR.MINOR.PATCH`。
- 每个正式版本必须提供 `docs/releases/<tag>.md`；流水线以此作为 GitHub Release 正文。
- App 从 Release 正文提取标题和要点，最多展示若干条，避免大段 Markdown。
- 构建时把 Tag 与完整 Git SHA 写入 Info.plist，开发构建回退为 `local` 与当前提交。

## 失败处理

- 启动检查：超时、离线、GitHub 限频均静默结束。
- 手动检查：显示可理解的失败提示，不泄漏技术堆栈。
- 下载/校验：保留当前 App，不启动替换。
- 替换：先备份旧 App；新 App 未能就位时立即回滚；用户数据不在替换路径内。

