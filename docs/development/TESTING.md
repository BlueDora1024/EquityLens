# 分级测试

测试只有一个入口：`./scripts/test.sh`。默认使用 `.venv/bin/python`，可用
`PYTHON_BIN` 覆盖。离线级别统一设置 Qt offscreen，不读取生产数据库、OAuth token
或 AI Key。

| 级别 | 命令 | 用途 |
| --- | --- | --- |
| L0 快检 | `./scripts/test.sh fast` | 提交前秒级检查架构、入口和三个算法 |
| L1 冒烟 | `./scripts/test.sh smoke` | Mock 端到端、CLI、QML 桥接与桌面壳 |
| L2 批次 | `./scripts/test.sh batch <name>` | 按受影响模块回归 |
| L3 全量 | `./scripts/test.sh full` | 全部回归、Ruff、strict mypy、QML lint |
| L4 产物 | `./scripts/test.sh package` | 已构建 App 的启动、隔离、资源与导出验收 |
| L5 真实 | `./scripts/test.sh live [symbol] [benchmark]` | 显式真实 Yahoo、当前主供应商与 AI 只读质检 |

这六个名称是稳定的回归门禁。构建不是第七个测试层级：
`./scripts/build_app.sh` 会先运行 L3，再生成、签名并用 L4 验收新产物。
性能基准是独立工具 `./scripts/test.sh benchmark`，不进入每次提交。

测试归属优先由目录决定；跨目录的快速合同使用 `fast` marker，外网与产物验收
分别使用 `live`、`package` marker。禁止在脚本中维护 QML 单文件清单。每次发布
还必须运行 `.venv/bin/python scripts/check_version_chronicle.py`，确保完整 Git
历史没有漏记或重复归属。

## L2 批次

| 名称 | 覆盖 |
| --- | --- |
| `rs` | RS 领域、应用、历史 codec、Mock 全流程与 CLI |
| `turning-point` | 拐点算法、共享行情、Longbridge、Mock 与 CLI |
| `extreme-deviation` | 指标、评分、缓存、Mock、CLI 与 QML bridge |
| `desktop-qml` | 共享 QML 控件、页面/桥接、Qt 几何与截图证据合同 |
| `platform` | 操作控制、证券、基础设施、迁移、QML bridge 与桌面壳 |

QML、主题、弹层、截图或 Bridge 的局部改动运行
`./scripts/test.sh batch desktop-qml`；它不替代跨模块的 `platform` 或发布前的 L3。
该批次会把普通 Bridge/合同、QML App 几何分别放到独立 pytest 进程，避免 Qt Quick
对象累计析构触发测试进程段错误；这只是进程隔离，覆盖集合没有减少。L3 同样先跑
非 QML 全仓，再用两个独立进程跑 QML 合同与真实 App 几何。

一个改动影响多个边界时运行多个批次；准备合并时始终运行 L3。不要把 L2 当作完整
回归。

可编辑长列表必须用真实 QML 行为测试约束，而不是只检查源码。Bridge 写入会替换
QML `list` 模型时，测试至少要把列表滚到第 30 行，执行新增、修改或删除，再断言：

- `contentY` 按新 `contentHeight` 夹取后保持在原位置，不跳回第一行；
- 当前业务实体 ID 保持不变，连续执行第二次操作仍成功；
- 删除导致列表变短时允许向上夹取，但不能无条件归零。

诊断日志属于 `platform` 批次和 L3 发布门禁。回归必须验证：

- 事件构造和导出双重脱敏，API Key、OAuth token、代理凭据、提示词与响应不能
  出现在原始 JSONL 或 ZIP；
- 写入异步、有界，debug 队列溢出优先丢弃且重要事件仍有保留通道；
- 5 MiB 滚动、7 天清理和 100 MiB 最近使用淘汰；
- 操作、SQL、进度、应用生命周期和 Qt 事件循环卡顿具备稳定事件合同；
- 高级设置页的筛选、搜索、打开目录、后台导出和二次确认清空可用；
- CLI 的 `diagnostics status|export|clear --confirm` 与桌面使用同一日志目录。

分析资源优化属于发布阻断项，必须覆盖：

- 正式组合根把三个冻结脚本路由到 Longbridge Quant；
- 富途组合根不调用 Quant，按额度预检后路由到不复权 RTH K 线和本地算法；
- RS 多范围仍只形成一个成员请求包络；
- 600×6 任务预算、覆盖水位命中和 50 次物理请求确认线；
- Longbridge 220/650 根分别按 2/4 个分页计数，Yahoo 1h/2h/4h 只下载一次；
- 富途预检额度快照在同次运行复用，大任务可在首请求前改用 Yahoo；
- 批量缓存一次读、一事务写以及旧缓存 payload 兼容；
- 极值偏离只保留最近 100 个结果但继续使用原始样本数判断置信度；
- 拐点未命中时不得请求快照；命中时只请求命中证券，市值标注失败不得改变核心
  可靠性或保存资格；
- 左侧以 `CCC` 从假变真命中，DIF 收缩只作增强确认；右侧以 CD 当根弱势结构和
  后续 20 根内上穿 High EMA26 命中；日内展示时间必须是 K 线结束时间；
- 超预算确认前后请求对象完全相同，资源预检不得访问 Provider；
- 三个运行页都具备资源卡、非阻塞加载态和阻断点击穿透的确认层。

优雅异常同样属于发布阻断项。确定性覆盖必须包含：

| 场景 | 冻结断言 |
| --- | --- |
| timeout 恢复 | 有限退避后成功，外部调用不超过初次 + 2 次 |
| scattered 429 | 首次降为一路并在本次运行保持；每个证券有界恢复，个别重试耗尽只跳过当前项 |
| persistent infrastructure failure | 连续 8 次同类错误或最近 20 项中同类错误至少 16 次才熔断；新运行重置 |
| auth / quota | 零重试，停止相关任务，提供设置动作 |
| exactly 80% / 79% | 前者保存 `PARTIAL`，后者不新增历史；未执行任务进入分母 |
| database busy / disk blocked | busy 只重试一次；磁盘安全清理后仍不足则阻断 |
| user cancel | 停止补充请求，不保存、不清空上一结果 |
| AI failure with old report | 只更新报告弹层错误，旧报告和确定性结果保持不变 |
| Yahoo fallback accepted | 丢弃主源临时结果，以 Yahoo 重跑整个请求；历史来源不得为 `mixed` |

Futu 额度与整次 Yahoo 备用路径的聚焦回归：

```bash
.venv/bin/python -m pytest -q \
  tests/qml/test_rs_run_bridge.py \
  tests/qml/test_turning_point_bridge.py \
  tests/qml/test_extreme_deviation_bridge.py \
  tests/qml/test_fallback_consent.py \
  tests/qml/test_qml_contract.py \
  tests/unit/application/test_analysis_budget.py \
  tests/unit/core/operations/test_reliability_wire.py \
  tests/integration/test_analysis_yahoo_fallback.py
```

该回归冻结四条语义：Futu 额度预检只读且缺口大于零必须阻断；Yahoo 选择只影响
本次运行并从第一步开始；完成历史不得混合 Provider；`insufficient_data` 只表示
真实短样本，`quota_exhausted` 不得被翻译或降级成短样本。

Provider/Scenario fixture 必须断言外部调用次数或 `max_provider_calls`，不能只断言
最终文案。十类故障合同可以独立或聚合复用：

```bash
./scripts/run_failure_scenario.sh --list
./scripts/run_failure_scenario.sh timeout-recovery
./scripts/run_failure_scenario.sh all
```

脚本不是 pytest 节点别名。每个 ID 都从包内 JSON 读取
`ScenarioDocument.fault_plan`，通过 `ScenarioRunner` 构建隔离 Composition
和临时 SQLite，再执行真实导入、股票池、RS、保存/回滚及报告链路。输出为每个
场景一行 `cli-output-v1` JSON；`scenario_assertions_passed=true` 才表示终态、
历史增量、未执行证券和 Provider 调用预算同时通过。
熔断原因按运行保存，未执行项继续报告实际触发源（rate limit、auth 或 quota），
不得把不同错误统一伪装成 429。

L4 产物的 `.zip.sha256` 只记录归档文件名，可把 zip 与 sidecar 一起复制到任意
目录后执行 `shasum -a 256 -c <sidecar>`。包内验收通过唯一退出 trap 终止并等待
GUI，且在成功、失败和信号退出时都清理临时数据库与 JSON。

聚合发布运行命令：

```bash
./scripts/test.sh smoke
./scripts/test.sh batch rs
./scripts/test.sh batch turning-point
./scripts/test.sh batch extreme-deviation
./scripts/test.sh batch desktop-qml
./scripts/test.sh batch platform
```

需要定位单个恢复合同，可运行：

```bash
.venv/bin/pytest -q \
  tests/unit/infrastructure/providers/test_longbridge_quant.py \
  tests/unit/infrastructure/ai/test_openai_compatible.py \
  tests/unit/core/operations/test_failure_policy.py \
  tests/unit/core/operations/test_storage_guard.py \
  tests/integration/persistence/test_uow.py \
  tests/qml/test_rs_history_bridge.py \
  tests/qml/test_turning_point_bridge.py \
  tests/qml/test_extreme_deviation_bridge.py
```

全局证券浅色状态证据使用完全隔离的 Scenario 数据生成：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python \
  scripts/capture_global_securities.py \
  --output artifacts/global-securities
```

脚本覆盖证券列表/详情、单只证券标签管理、删除确认、导入空状态、180/200
运行状态、导入结果、全局标签成员、批量多选和部分失败结果，以及股票池详情、
候选去重、两步批量添加、完成状态和池内参评标签切换；不读取正式 SQLite、
OAuth token 或 AI Key。

全局 QML 画廊支持按窗口尺寸生成浅色/深色证据：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python \
  scripts/capture_qml_gallery.py \
  --output artifacts/qml-gallery-980x680 \
  --width 980 --height 680
```

发布前至少检查 980 × 680、1280 × 800 和 1600 × 1000。自动测试同时验证共享
按钮内容中心偏差不超过 0.5 px、选择项 indicator 不侵占文字，以及最小尺寸下主
页面和设置页结构文字不截断。截图检查仍用于发现无法仅靠几何断言识别的光学偏差。

RS 运行态的浅色证据可独立生成：

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. .venv/bin/python \
  scripts/capture_rs_run_states.py \
  --output artifacts/rs-run-concurrency
```

脚本覆盖准备、拉行情、计算、取消、失败、分类历史、单区间个股、AI 未配置、
AI 运行中、已保存报告与 1120 × 720 紧凑运行态；使用隔离 Scenario HOME，
不读取真实授权、密钥或生产数据库。

RS 冻结 hash 与 30 次性能采样使用 `./scripts/test.sh benchmark`，不进入每次
提交的冒烟。

已有 bundle 可单独执行：

```bash
./scripts/test.sh package
```

## 真实服务

真实 smoke 是显式、只读的 L5 外部检查，不进入普通测试：

```bash
./scripts/test.sh live IREN.US SPY.US
```

它先运行标记为 `live` 的 Yahoo 网络用例，再读取用户已经在 App 中保存的
当前供应商和 AI 配置，验证资料、交易日、RS、拐点、极值偏离、AI 分类和技术
解读，并确保历史数量不变。富途单项验收也可显式运行：

Yahoo live 同时冻结两类能力：小样本日线/全部支持周期，以及 NVDA 当前截止日
30m、1h、日线、周线各至少 650 根。该测试证明当前网络与 Yahoo 保留窗口能覆盖
近期极值偏离，不代表 Yahoo 能覆盖超过 60 天的 30m 历史或公司资料。`query1`、
`query2` 等同源入口不得计作第二个独立 Provider。

```bash
RUN_LIVE_FUTU=1 .venv/bin/python -m pytest -q \
  tests/integration/providers/test_futu_live.py
```

OpenD 未在 `127.0.0.1:11111` 登录时，该用例记录明确跳过原因，不声明现场通过。
命令不接收或输出
密钥；未配置时应返回非零退出码。`full` 明确排除 `live` 与 `package` marker，
因此普通开发回归不会消耗外部额度。

量化脚本发布前还必须通过 Navi 静态检查，并至少对一只美股验证拐点服务端支持
周期、日线极值偏离和 RS 成员 close；极值偏离只验证 30m、60m、日线和周线；120m/240m 拐点必须单独验证 SDK 原生 K 线
本地计算，禁止作为 Quant 周期测试。输出只保留根数、字段名和稳定状态码。

当前发布证据见[交付状态](../CURRENT_STATE.md)，详细检查项见
[真实服务 Smoke](live-smoke.md)。
