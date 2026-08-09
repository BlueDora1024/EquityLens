# EquityLens

[中文](#中文) · [English](#english)

EquityLens 是一款本地优先的 macOS 美股复盘与分析桌面工具。它将全局证券库、
业务标签、股票池和三类分析工具集中在一个原生 PySide6 / Qt Quick 应用中。

EquityLens is a local-first macOS desktop workbench for reviewing and analyzing US
equities. It brings a shared security library, business tags, watchlists, and three
focused analysis tools into one native PySide6 / Qt Quick application.

> EquityLens 仅用于研究与复盘，不构成投资建议。指标描述历史市场数据，不预测未来收益。
>
> EquityLens is research software, not investment advice. Its signals describe
> historical market data and do not predict future returns.

## 中文

### 核心能力

- **RS 强度**：在多个时间区间内，将股票池成员与 SPY 或 QQQ 比较，并按照股票池中
  选定的业务标签汇总强弱结果。
- **拐点筛选**：在多个 K 线周期中识别左侧 CD 背离信号，以及可选的右侧均线确认。
- **极值偏离**：逐只复盘证券，展示所选周期内修正版买卖压力和偏离程度。
- **共享工作区**：全局只维护一份证券资料和业务标签，可将证券分配到多个股票池，
  避免重复保存基础信息。
- **可插拔行情源**：支持长桥、富途 OpenD，以及 Yahoo 公开数据兜底。AI 为可选能力，
  兼容 OpenAI 协议，仅在用户主动请求报告时调用。

### 隐私与本地数据

公开仓库和发布包不包含用户数据库、行情 Token、API Key、诊断日志或分析历史。
EquityLens 首次启动时会在当前 macOS 用户目录下创建独立的空数据空间：

```text
~/Library/Application Support/EquityLens
```

应用不会自动读取旧产品的数据目录。诊断信息默认保留在本机，导出前会过滤密钥等敏感内容。

### 下载与安装

请从 [GitHub Releases](https://github.com/BlueDora1024/EquityLens/releases/latest)
下载与你的 Mac 匹配的压缩包：

- `EquityLens-vX.Y.Z-arm64.zip`：Apple 芯片 Mac
- `EquityLens-vX.Y.Z-x86_64.zip`：Intel Mac

应用目前使用 ad-hoc 签名，尚未经过 Apple 公证。macOS 可能要求你手动确认打开。
发布包不包含任何供应商账户或凭据。

### 本地开发

环境要求：macOS、Python 3.12、Xcode Command Line Tools。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/equitylens-gui
```

常用命令：

```bash
./scripts/test.sh fast
./scripts/test.sh batch rs
./scripts/test.sh batch turning-point
./scripts/test.sh batch extreme-deviation
./scripts/test.sh full
./scripts/build_app.sh
```

CLI 与桌面应用复用同一套应用服务：

```bash
.venv/bin/equitylens analysis list
.venv/bin/equitylens --help
```

### 架构与维护文档

- [系统架构](documentation/architecture.md)
- [产品流程](documentation/product-flows.md)
- [数据、权限与隐私](documentation/data-and-permissions.md)
- [测试与回归门禁](documentation/testing.md)
- [构建、发布与公开镜像](documentation/releasing.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

项目保留 Python 包名 `stock_toolbox` 作为内部兼容边界；产品名称、应用包、命令行入口
和发布产物统一使用 EquityLens。

## English

### What it does

- **RS Strength** compares watchlist members with SPY or QQQ over multiple date
  ranges, then aggregates the results by the business tag selected in that watchlist.
- **Turning Point** detects left-side CD divergence signals and optional right-side
  moving-average confirmation across multiple K-line periods.
- **Extreme Deviation** reviews one security at a time and visualizes corrected buy
  and sell pressure across selected periods.
- **Shared workspace** maintains one global security library and reusable business
  tags while allowing securities to participate in multiple watchlists.
- **Pluggable market data** supports Longbridge, Futu OpenD, and a Yahoo public-data
  fallback. Optional AI reports work with OpenAI-compatible endpoints and run only
  when explicitly requested.

### Privacy and local data

The public repository and release bundles contain no user database, provider token,
API key, diagnostic log, or analysis history. On first launch, EquityLens creates an
independent empty data directory in the current macOS user account:

```text
~/Library/Application Support/EquityLens
```

The app does not automatically read data directories from older product names.
Diagnostics remain local by default, and exported diagnostics redact secrets.

### Install a release

Download the archive matching your Mac from
[GitHub Releases](https://github.com/BlueDora1024/EquityLens/releases/latest):

- `EquityLens-vX.Y.Z-arm64.zip` for Apple silicon
- `EquityLens-vX.Y.Z-x86_64.zip` for Intel Macs

The app is ad-hoc signed rather than notarized. macOS may ask you to confirm that you
want to open it. Provider accounts and credentials are never bundled.

### Develop locally

Requirements: macOS, Python 3.12, and Xcode Command Line Tools.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/equitylens-gui
```

Useful commands:

```bash
./scripts/test.sh fast
./scripts/test.sh batch rs
./scripts/test.sh batch turning-point
./scripts/test.sh batch extreme-deviation
./scripts/test.sh full
./scripts/build_app.sh
```

The CLI uses the same application services as the desktop interface:

```bash
.venv/bin/equitylens analysis list
.venv/bin/equitylens --help
```

### Architecture and maintenance

- [Architecture](documentation/architecture.md)
- [Product flows](documentation/product-flows.md)
- [Data, permissions, and privacy](documentation/data-and-permissions.md)
- [Testing and regression gates](documentation/testing.md)
- [Build, release, and public mirror](documentation/releasing.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

The repository keeps the Python package name `stock_toolbox` as an internal
compatibility boundary. The product, app bundle, command, and release artifacts are
named EquityLens.

## License / 许可证

EquityLens is available under the [MIT License](LICENSE).

EquityLens 使用 [MIT License](LICENSE) 开源。
