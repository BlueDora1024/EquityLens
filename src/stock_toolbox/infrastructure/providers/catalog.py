"""Trusted market-data integrations shown in the settings workspace."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    display_name: str
    summary: str
    builtin: bool


_LONGBRIDGE = ProviderDescriptor(
    "longbridge",
    "长桥",
    "官方 OpenAPI · 美股基础资料、交易日历与多周期行情",
    True,
)

_FUTU = ProviderDescriptor(
    "futu",
    "富途",
    "官方 OpenAPI · 通过本机 Futu OpenD 提供美股资料与多周期行情",
    True,
)

_DEVELOPMENT_PROMPT = """你正在“EquityLens”的完整源码仓库中工作。你的任务是把一个新的
只读行情供应商接入现有架构，最终做到：能在设置页配置和质检、能安全切换为当前
供应商、三个分析工具可以真实运行、测试和 macOS 打包验收通过。

【先填写】
- 供应商名称：<请填写>
- 官方开发文档：<URL>
- 认证方式与只读权限：<OAuth / API Key / 本地网关等>
- 官方 SDK：<名称、版本、安装方式；没有则填写“官方 HTTP API”>

如果以上信息不完整，先阅读用户提供的官方文档。仍无法确认且会改变实现边界时，
只询问一个关键问题；不得凭空发明 API、权限、额度、周期或 SDK 行为。技术事实只以
目标供应商最新官方文档和当前仓库源码为准。

【第一阶段：只做调查和计划】
1. 检查 Git 状态并保护用户已有改动。不得覆盖用户已有修改，不得使用 reset --hard
   或 checkout 丢弃文件。
2. 阅读当前源码，而不是依赖旧记忆。至少检查：
   - src/stock_toolbox/core/market_data/models.py
   - src/stock_toolbox/core/market_data/quant.py
   - src/stock_toolbox/core/market_data/provider_health.py
   - src/stock_toolbox/core/market_data/date_policy.py
   - src/stock_toolbox/core/market_data/fallback.py
   - src/stock_toolbox/core/securities/models.py
   - src/stock_toolbox/infrastructure/providers/longbridge.py
   - src/stock_toolbox/infrastructure/providers/futu.py
   - src/stock_toolbox/infrastructure/providers/catalog.py
   - src/stock_toolbox/infrastructure/persistence/service_settings.py
   - src/stock_toolbox/composition.py
   - src/stock_toolbox/desktop_qml/settings_bridge.py
   - 对应的 unit、integration、scenario、QML 和 packaged acceptance 测试。
3. 把 LongbridgeProvider 和 FutuProvider 当作两种参考实现，不要整份复制其中任何
   一个。以当前 Protocol、DTO、组合根和测试契约为唯一接入边界。
4. 先输出能力矩阵，逐项写明“原生支持 / 可组合实现 / 不支持 / 尚未确认”：
   - 美股证券基础资料、证券有效性与类型判断；
   - 最近完整交易日；
   - 批量快照；
   - 日线收盘数据；
   - 30 分钟、1 小时、2 小时、4 小时、日线、周线 K 线；
   - 服务端 EMA、MACD、区间高低值或自定义公式；
   - 批量上限、单页上限、分页规则、并发限制、频率限制和行情额度；
   - 历史复权、时区、盘前盘后、未收盘 K 线的语义；
   - 认证、Token 刷新、本地网关、代理和断线重连。
5. 根据官方限制估算 600 只股票运行 RS、拐点筛选和极值偏离的请求预算，分别列出：
   冷启动、缓存命中、服务端量化可用、原始 K 线兼容、部分失败重试五种情况。
6. 给出最小改动计划，列出会修改或新增的文件、每一项测试以及无法对齐的能力。
   若用户已明确授权自主执行，输出计划后继续实施，不重复索要确认。

【第二阶段：按 TDD 实施】
1. 先写一个能因缺少新能力而正确失败的测试，运行并保存 RED 证据；再写最小实现，
   运行到 GREEN。协议、适配器、设置、质检、切换、失败映射和打包依次执行此流程。
2. 实现当前源码中的 DailyBarsProviderPort、ScreeningMarketDataPort 以及证券资料
   所需协议；复用现有领域 DTO、日期策略、缓存、资源预算、Yahoo 整次单源重跑和错误分类。
   不得创建第二套行情领域模型，不得在 GUI 或 CLI 复制业务规则。
3. 供应商确实能以更低资源成本、完整表达现有命名序列时，才实现
   QuantMarketDataPort，并只声明真实支持的 quant_script_versions。若指标接口仍要求
   客户端上传完整 K 线、无法表达现有公式，或限频后成本更高，就保留原始 K 线兼容
   路径。不得伪造服务端量化能力。
4. 不得修改 RS、拐点筛选或极值偏离算法。只允许在供应商适配层完成格式、分页、
   时间、错误和能力映射。

【强制工程契约】
1. 本软件只做行情分析。只申请证券资料、交易日历、报价、快照、历史 K 线和技术
   指标等只读能力；禁止申请或调用资产、账户、持仓、订单和交易权限。
2. 新适配器只能读取该供应商自己的凭据。不得读取 AI API Key、其他 Provider token
   或绕过现有设置存储；不得把凭据写入业务日志、异常文本、导出、诊断包或测试快照。
3. 所有时间必须有明确时区并转换为项目现有 UTC 口径；序列必须升序、去重，命名
   数值序列必须与时间轴严格对齐。只返回已经完整收盘的数据，价格沿用 Decimal。
4. 以供应商官方规则确定批量和分页大小，优先用一次官方最大安全页覆盖完整计算窗口。
   不要把 Longbridge 或 Futu 的固定上限机械套到新供应商。
5. 实现有限并发、超时、可取消、指数退避、限流冷却、额度耗尽和逐证券稳定错误。
   可恢复错误集中汇总，不能反复弹窗；成功结果不因部分证券失败而丢失。
6. 缓存键必须包含供应商身份以及现有协议要求的证券、周期、时间、复权和脚本版本，
   绝不能让不同供应商的数据互相污染。
7. 在 ProviderDescriptor 目录注册新供应商，并接入当前设置持久化、配置界面、
   composition.py 组合根、诊断和 CLI。应用不会运行时加载任意本机脚本；只有重新构建
   后编译进应用的受控实现才能被发现。
8. 新供应商先作为候选供应商。质检至少验证认证或本地网关、最近完整交易日、AAPL
   基础资料、AAPL 快照/日线，以及它声明支持的量化命名序列。
9. 质检通过后才能由用户设为当前供应商。切换必须在现有事务和组合根中原子完成；
   配置、质检或重建失败时保留原供应商、缓存、证券库、股票池和历史。任一时刻只启用
   一个主供应商；Yahoo 仍是运行失败后由用户按次确认的公开兜底。
10. 正式数据、Scenario/Mock 数据和缓存身份必须隔离。Mock 需要覆盖边界场景，但
    不得把 Mock 通过当作真实供应商已经可用。

【完成门槛】
1. 单元测试：字段映射、Decimal、时区、完整收盘、排序去重、分页、批量、限流、
   重试、取消、错误分类、凭据脱敏和资源预算。
2. 契约/集成测试：基础资料、交易日、快照、日线、拐点六周期与极值偏离四周期 K 线；若声明 Quant，再验证
   close、拐点和极值偏离命名序列及脚本版本。
3. 设置与场景测试：配置、质检、候选状态、失败保留旧供应商、原子切换、重启恢复、
   Yahoo 兜底询问、日志与诊断。
4. 使用 Mock 跑完整 CLI 剧本，再使用用户配置的真实环境执行 AAPL 或用户指定证券的
   真实只读 smoke。不得使用账户、资产、订单或交易接口。
5. 运行项目现有 pytest、Ruff、严格 mypy、QML lint、packaged acceptance 和版本
   编年史门禁；更新集成文档、测试说明、CHANGELOG 和 VERSION_CHRONICLE。
6. 构建 Intel macOS 应用，验证签名、架构和产物哈希，并同步更新
   /Applications/EquityLens.app。安装失败时不得覆盖仍可用的旧应用。

【最终交付报告】
最终只依据实际证据汇报：
- 能力矩阵和仍未支持/尚未确认的能力；
- 修改文件和架构接入点；
- 三个分析工具在 600 只股票下的实际请求预算与缓存收益；
- 限流、超时、额度耗尽、网络失败和部分失败的用户体验；
- RED/GREEN、全量门禁、真实只读 smoke 和 packaged acceptance 的结果；
- 构建产物、安装位置和 Git 提交。

如果缺少真实凭据、本地网关、行情权限或额度，就明确写“未执行”并给出可复现命令。
不得在没有证据时声称已经测试通过、已经安装或真实供应商已经可用。"""


def list_provider_descriptors() -> tuple[ProviderDescriptor, ...]:
    """Return integrations compiled into this application build."""

    return (_LONGBRIDGE, _FUTU)


def provider_development_prompt() -> str:
    return _DEVELOPMENT_PROMPT
