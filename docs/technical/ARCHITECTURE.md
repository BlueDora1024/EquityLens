# 技术架构

## 结构

```text
PySide6 QML GUI / argparse CLI
           │
     Composition Root
           │
 core use cases + analysis modules
           │
 Longbridge / Futu OpenD / Yahoo / AI / SQLite adapters
```

`stock_toolbox.core` 只包含跨工具能力：证券、分类、股票池、行情 DTO、缓存和运行
控制。`stock_toolbox.analyses.<tool>` 拥有自己的请求、算法、报告和历史 payload。
`stock_toolbox.infrastructure` 实现 Longbridge、Futu OpenD、Yahoo、
OpenAI-compatible AI 与 SQLite。
`stock_toolbox.composition` 是唯一装配入口。

共享层不得导入具体分析模块。GUI、CLI 和 Virtual 场景必须调用同一应用服务。

行情 Provider 使用受控注册表展示当前构建已接入的实现。新增 Provider 必须复用
证券资料、快照、可选 `QuantMarketDataPort` 和必要的原始 K 线契约，在组合根接线并注册
`ProviderDescriptor`；应用不从用户目录动态执行 Python 插件。

## 分析模块

每个工具实现一个 `AnalysisModule`，通过 `AnalysisDescriptor` 提供稳定 ID、
名称、版本、图标和数据要求。QML 页面由正式桌面壳统一承载，不在分析模块内再
建立第二套页面工厂。

模块在 `AnalysisRegistry` 显式注册。工具之间不共享运行状态或结果 schema；只有
全局证券、分类、股票池、行情和配置可共享。

## 运行

一次运行按以下阶段推进：

1. 校验并冻结请求；
2. 在后台按精确缓存键扫描预算；富途只额外读取历史额度，不请求 K 线；
3. 物理外部请求超过 50 时等待用户确认，不改变冻结请求；Longbridge 原始 K 线按
   200 根真实分页、Futu 按 1000 根分页及额度探测、Yahoo 按批量下载族计数；
4. 解析最新完整交易日；
5. 一次确定最长包络，按当前 Provider 能力生成数据请求；
6. Longbridge Quant 未命中项最多 2 路并发，并以 750ms 间隔（约 1.33 次/秒）平滑启动直连请求；富途通过 OpenD 限频分页读取原始行情；
7. Longbridge 服务端返回命名序列；富途本地算法读取原始 K 线，两路共用确定性评分；
8. 可补救的主行情终止失败时，后台任务等待一次用户备用数据决定；同意后丢弃
   尚未保存的主源临时结果，以 Yahoo 为唯一 Provider 从第一步重跑完整请求；
9. 汇总结果并冻结单一 Provider、逐证券来源与请求/实际日期；
10. 在取消门禁后事务保存。

量化缓存键包含 Provider、证券、周期、精确起止时间和脚本版本；只缓存完整收盘
区间，脚本升级自然失效。网络完成顺序不会改变成员、失败或历史顺序。校验和个股
计算按 50 个成员一块，分类聚合按 10 个分类一块，每块只组合现有公开阶段并报告
真实进度，不建立第二套算法。

缓存访问按一次运行批量执行：一个 `IN` 查询读取该批键，一个事务
`executemany` 写入完整结果，禁止按 600 个证券重复建立连接。极值偏离复用共享 OHLC
缓存并在本地计算；覆盖水位必须达到目标完整 K 线，落后时增量补尾。完整输入用于 500/250/90 窗口预热，历史结果只冻结最近 100 根
图表证据。30 根是评分下限，100 根起完整置信，500 根不是可用性硬门槛。

`analyses.resource_budget` 是三个工具共用的只读预检服务。它访问股票池、
SQLite 缓存，并在富途模式读取一次最近 7 天历史额度，输出理论任务、命中、
冷请求、额度缺口、保护线和数据路径；QML bridge 用
`QThreadPool` 执行预检。超预算确认只是一道门禁，不是第二套调度器，也不得修改
应用服务最终收到的请求。

Longbridge Quant 的结束日期是排他上界。Provider 适配器统一把请求上界推进一个
自然日，并在解析后裁掉原结束时间之后的点；三个工具不各自复制边界补偿逻辑。
边界契约改变时同步升级脚本版本，使旧缓存自然失效。

日期容错由 `core.market_data.probe` 统一实现：用户边界前后各扩展四个工作日，
取数后向算法区间内部解析 actual 边界。扩大包络不改变请求日期、算法跨度或显示
时区中的今天上限；这些日期随结果一同冻结。

Longbridge 当前 Quant 服务不稳定支持 `request.security` 跨证券执行，因此冷启动
仍按“证券 × 周期”请求，但以 2 路有限并发执行。RS 成员只返回 close；拐点的
30m/1h/日线/周线返回 EMA/MACD/volume 所需序列，2h/4h 因 Quant 无对应周期而
改走 SDK 原生 K 线和本地冻结算法；极值偏离的 30m/1h/日线/周线一律读取原始 K 线
并运行本地修正版公式。SPY/QQQ 在 Quant 服务
当前无结果，RS 基准是唯一例外：通过同一 Longbridge SDK 读取一次日线。

拐点核心信号完成后才执行可选增强：命中证券按 100 只一批读取快照，只补充
小市值或市值未知提示。

桌面端正式/开发环境中，证券导入、RS、拐点和极值偏离等 Provider 重任务均通过
App 内置 CLI 子进程执行，QML Bridge 只消费版本化 JSONL 进度、备用数据确认与最终
结果。这样 Longbridge/Curl 原生调用即使长时间占用 Python GIL，也不会阻塞 Qt GUI
事件循环；取消只终止对应工作子进程，不保存半成品。资源预检和股票池下拉等短小
只读任务仍使用 `QThreadPool`。Scenario 与单元测试可直接注入内存实现，避免为纯
UI 测试启动额外进程；两条路径必须调用同一 Application API，不能复制算法。

子进程边界同时包含输出背压约束：stdout 只传 JSONL 合同，stderr 由 Bridge 持续
排空；大股票池进度先更新内存状态，再以 50ms 窗口合并 QML 通知。诊断日志保留阶段
首尾和所有限频、重试、错误反馈，普通进度每阶段最多约 20 个采样，禁止逐证券日志
写入反过来拖慢界面。
增强失败不回写核心周期结果，也不进入 80% 可靠性分母。

正式组合根必须按冻结脚本选择数据路径：

- RS 成员：`daily-close-quant-v2`；
- 拐点：30m/1h/日线/周线使用 `turning-point-quant-v3`，2h/4h 使用原生
  `Period.Min_120/Period.Min_240`；
- 极值偏离：原始 K 线 + `extreme-deviation-corrected-v3` 本地冻结公式。

RS 与拐点的量化能力路由不依赖供应商名称硬编码；极值偏离不声明 Quant 能力，
所有 Provider 都走相同本地公式。长桥与富途配置各自保留，但 SQLite
只保存一个 active provider；候选质检和启用分离，启用后统一重建资料导入与分析
Provider。缓存键带 Provider ID，因此切换不会复用另一来源的行情结果。

Quant 临时失败只执行受控重试，之后记录单项失败；禁止在同一批次静默切换成
大量 Longbridge 原始 K 线下载。只有用户在共享确认层明确同意后，组合根才捕获
内部 `WholeRunFallbackRequested`，重建 Yahoo-only 服务并重跑完整冻结请求。
异常在任何事务保存前发生，因此主源半成品不会进入历史。没有 Quant 能力的其他
Provider 也必须显式使用兼容路径，资源卡按真实分页成本计入预算。

`OperationRegistry` 负责互斥、取消和关闭窗口保护。后台任务只发不可变结果，Qt
主线程更新控件；晚到信号必须检查页面和运行身份。失败/取消不清空上次成功结果。

## 数据

业务 SQLite 由顺序 SQL migrations 管理，当前包含：

- 全局证券、分类、证券分类和股票池成员；
- RS 冻结运行及其范围、成员、个股、分类和失败；
- 通用分析运行与工具 payload；
- K 线缓存、版本化量化结果缓存、设置与迁移记录。

AI 全局配置保存在独立 SQLite。API Key 按用户明确要求以明文保存，但不得进入
日志、命令行、fixture、历史或导出。Longbridge token 只由 SDK 存放在
`~/.longbridge/openapi/tokens/<client_id>`。

Production、Development、Integration 与 Scenario 使用不同业务数据目录；
Scenario 和普通测试只能注入 Virtual/Fake 或临时路径。

诊断日志位于独立的 `~/Library/Logs/EquityLens`，不是业务 SQLite
的一部分。`JsonlDiagnosticLogger` 使用有界队列和单后台写线程；调用方只提交
结构化事件，日志 I/O、滚动和清理不占用 Qt 主线程。默认每个文件 5 MiB、保留
7 天、目录总量 100 MiB，超限时按最近访问/修改时间删除旧文件。

## UI

正式桌面端使用 PySide6 Qt Quick/QML 和自研 Soft Glass 视觉组件；颜色与层级由
`Theme.qml` 统一维护。`ThemeBridge` 解析“跟随系统/浅色/深色”，监听 macOS
外观变化，并通过 `ServiceSettingsStore` 将用户选择保存到业务 SQLite；截图覆盖
只影响当前进程，不改写偏好。一级导航为全局数据、分析工具与设置；每个工具包含
运行和历史二级页面。仓库只保留正式 QML 展示层，已退出使用的 Qt Widgets
兼容界面不再随产品维护。

无边框窗口的 48 px 标题栏由 QML 绘制，但红黄绿按钮调用真实 `QWindow` 动作。
标题栏 z 层级固定高于全屏遮罩。共享按钮、选择项和侧栏项统一从主题读取控件高度，
发布测试在三档窗口尺寸计算内容中心、indicator 间距和文字截断。

QML 不直接接触数据库或算法。每个业务区域由一个小型 QObject bridge 暴露只读
状态和命令；长任务通过 `QThreadPool/QRunnable` 执行，后台只发不可变结果，
主线程更新界面。导航由分析注册表生成，因此增加股票池或分析工具不依赖硬编码
页面数量。

全局证券使用两类投影而不修改规范数据：

- SQLite 和 Provider 始终保存 `SYMBOL.US`，`MasterDataBridge` 仅向界面提供
  `displaySymbol`、视觉序号、中文标签和格式化详情；
- 公司基础资料随导入持久化；详情页仍可通过共享快照契约异步按需读取最新行情。
  全局刷新使用后台任务按 50 只分批读取资料与快照，将最近成功价格、市值、
  可用状态和检查时间写入既有 `business_profile_json.refresh`，不新增重复证券表；
  确定不可用与临时检查失败分开记录，失败不清除上一份有效快照；
- `ImportProgress` 使用全批统一总数并携带逐项终态，QML 同时渲染进度条、统计
  与明细，不另建一套导入状态机；
- 标签绑定继续复用 `set_security_classifications` 的三项上限和参评引用保护；
  标签详情按全局投影列出成员；批量添加逐只复用同一接口并分别提交，因此某只
  证券达到上限只产生该行失败，不回滚同批其他证券；
- 删除继续由 SQLite 事务先清成员关系再清证券。

RS 运行桥缓存完整股票池 DTO，首次打开下拉时在线程池加载；已有缓存期间后台刷新
不会把模型替换为空。结束日期使用独立异步交易日任务，自定义区间和结束日期共享
QML 月历组件，Python Bridge 只接收规范 `YYYY-MM-DD` 并继续执行最终范围校验。
运行页消费应用层的成员/计算块进度，展示阶段、完成数、成功/失败、当前证券和用时；
配置在运行期间只读，失败和取消保留实际进度并留在本页。Bridge 只对成功终态增加
250ms 的有界阶段展示：同阶段成员进度实时覆盖，未来阶段各保留最新一条，全部六
阶段极快时最多延后约 1.5 秒再导航结果；失败和取消清空队列并立即完成。任务日志、
数据库时间与算法执行不读取展示时钟。

极值偏离运行桥在线程池加载有效全局证券 DTO；桌面端请求只携带
`selected_security_id`，不再读取股票池或二次选择成员。页面默认使用显示时区中的
昨天，再把此日期作为上界异步查询当前供应商的美股交易日历；实际运行日取不晚于该
上界的最近完整交易日。证券读取、交易日解析和固定四周期正式运行互不占用 GUI
线程，运行状态卡常驻并消费真实进度。

拐点 Bridge 将运行态与历史投影分开：运行终态只有携带持久化 `run_id` 的完成或
部分完成结果才由应用壳导航到 `turning_point.history`，失败与取消不跳页。历史
选择会把结果筛选重置为该记录的“综合关注”，再按该记录冻结的周期生成筛选项；
单周期投影直接复用冻结 `period_results` 的 `signal_at/crossed_at`，不重新计算、
不请求行情。未命中、固定、CSV 导出和 AI 报告都使用同一个 `selected_run_id`。
AI 弹窗始终读取该记录的全部所选周期，不受当前“综合关注/单周期”视图影响。

RS 历史桥只向个股列表投影当前选中 `run_range_id`，切换历史时重置到该记录第一
个区间；同时从冻结区间价格生成唯一的基准收益摘要。个股结果由 Bridge 按
`rs_percentage_points` 稳定排序，默认降序，QML 表头只触发方向切换。分类综合
仍单独显示跨周期结论；每个状态的中文解释由 Bridge 读取对应
`classification_period_results` 的中位 RS 生成，QML 不重复实现判断规则。
历史时间始终以 UTC 持久化；未改名记录由 Bridge 根据当前 `display_timezone`
重建展示名称，用户自定义名称直接保留。桌面端删除外部历史导入，只把既有 `csv`
导出暴露为 ZIP 统计包，并自动补 `.zip` 默认文件名。
手动 AI 解读由应用层纯函数从冻结
`HistorySnapshotRecord` 构建有界证据：全部分类综合与分类周期分、各区间互斥的
强弱前列、按原区间权重归一化的综合强弱前列、周期分歧和失败统计。后台任务复用
OpenAI-compatible 文本适配器，成功后把报告原子附加到
`snapshot_extensions.ai_reports`。因此报告与历史共享删除、恢复默认、备份和
导出生命周期，同时不修改任何冻结算法表。

CSV 文件先由 `core.securities.import_input` 做结构预览：限制文件大小/行列数，
识别 UTF-8/GB18030、分隔符、表头与内容有效率；只有明显领先的证券代码列自动
选中，歧义候选交给 QML 展示列名和样例。选定后只产生规范代码文本，最终写入仍
唯一经过原有 ImportService 的资产白名单、Provider 校验和原子追加事务。
CSV、侧栏工具说明和分类状态统一复用 QML `InfoTip`；组件只负责悬浮触发、
软玻璃背景和多行排版，不复制领域规则。

股票池成员工作区使用池上下文投影：

- `watchlist_candidates` 只返回未加入当前池的全局证券，提交时应用层再次按证券
  ID 去重，避免界面状态过期造成重复成员；
- 添加弹层先收集证券，再为每只证券选择其已有标签；默认第一项并以一个批次提交；
- `set_watchlist_member_binding` 在事务中替换指定成员的参评标签并递增股票池
  revision，不改证券的全局标签；展示层只消费 `displaySymbol`，因此不出现 `.US`。

AI 分类输入包含完整现有标签池和别名。适配器优先解析既有身份，新标签必须通过
中文与长度校验；AI 不可用时仅对 Provider 已可靠确认的正股使用当前供应商
`sector/category` 白名单映射，资产资格不确定时禁止降级绕过。

设置桥接层把服务配置组织为状态流水线：

- Longbridge：动态注册 → 官方 OAuth → 交易日 → 基础资料 → 日 K 线，全部通过后
  才持久化 Client ID；
- Futu：检测 OpenD → 本机登录 → 六项只读质检 → 原子启用，不创建交易上下文；
- AI：模型发现 → 默认模型选择 → IREN 分类质检 → 原子保存，临时 `bytearray`
  在成功和失败路径均清零。

UI 只负责收集输入、显示状态和调用应用服务，不包含指标公式、Provider 分页或
持久化事务。Scenario Lab 始终创建独立 Scenario 数据库和 Fake Secret Store，
即使从正式 App 的开发者模式进入，也不会读写正式数据或凭据。

## 错误与安全

边界错误映射为稳定 code、用户消息、可重试性和上下文摘要。结构化诊断记录模块、
动作、状态、任务、阶段、证券代码、耗时和进程内存；SQLite 只记录操作类型与耗时，
不记录 SQL 文本、参数或结果。日志模型在构造时拒绝密钥、token、Authorization
header、Cookie、代理凭据、完整提示词/响应和用户数据库内容，导出时再次白名单
过滤。

`UiStallMonitor` 每 250 ms 观察 Qt 事件循环：晚到 1 秒记 warning，晚到 3 秒记
error，并附当前页面、活跃操作数、后台线程数与 RSS。它只采样已发生的卡顿，不
启动额外业务请求。所有长操作通过共享 span 记录单调时钟耗时和内存；运行进度按
阶段和计数记录，避免正式环境只能看到最终失败而无法定位停滞位置。

`core.operations.failure_policy` 是三个分析工具的唯一故障分类与可靠性规则来源；
Provider 只负责单次请求的有限恢复和运行内熔断，分析服务负责核心输入校验与
80% 保存门槛，Bridge 只把不可变状态投影为同一摘要卡和按需详情层。成功率为：

```text
成功任务 / (成功任务 + 失败任务 + 熔断后未执行任务)
```

连续 8 个同类基础设施错误、最近 20 个完成任务中同类错误至少 16 个，或认证、权限、
配额、存储、数据库损坏、内存不足等致命错误都会停止
提交新请求。已在执行的最多四个请求到安全检查点后收尾；熔断、取消和保存失败
都不会自动重启，也不会覆盖上一份结果。

`desktop_qml.fallback_consent.FallbackConsentGate` 只在分析 worker 中等待；
QML 主线程继续绘制进度并显示一个共享确认层。决定在一个运行内只能提交一次，
取消会唤醒等待线程。接受会在事务保存前抛出内部重跑信号，组合根丢弃主源临时
结果并用 Yahoo-only 服务执行完整请求；备用失败继续走同一可靠性与终态规则。

分析开始前执行磁盘预检。可用空间低于 1 GiB 显示提醒；低于 256 MiB 时只清理
`quant_result_cache` 与 `market_candle_cache`。SQLite 删除产生的 freelist
记为可复用字节，不冒充操作系统已释放空间。清理后“物理可用 + 新增可复用”仍
低于 256 MiB 则阻止运行。证券、标签、股票池、设置、历史、用户导出和 OAuth
材料永不进入自动清理范围。

`OperationExecutor` 把进程内可捕获的 `MemoryError` 映射为
`memory_exhausted`，停止新任务并建议缩小股票池或周期；不在同一进程自动重跑。
操作系统直接终止进程的 OOM 无法由应用捕获，因此架构边界是不承诺从该状态恢复，
而是通过最多四路并发、有界 future、批量缓存和紧凑结果避免自身制造无限资源增长。

必须保留：

- 外部输入校验与资产白名单；
- SQLite 事务、备份和迁移失败保护；
- Provider 超时、有限重试、分页去重和取消；
- AI 输出本地 schema 校验与提示注入隔离；
- 发布前 bundle、签名、架构和隔离启动检查。

实现细节以 `src/stock_toolbox` 和
`src/stock_toolbox/infrastructure/persistence/sql` 为唯一事实来源。
