"""Pure, sanitized presentation for analysis recovery and terminal failures."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal

from stock_toolbox.core.operations.failure_policy import (
    AnalysisReliability,
    FailureCode,
    RunReliabilitySummary,
    RunTerminal,
)
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback

_SAFE_SYMBOL = re.compile(r"[A-Z0-9.^_-]{1,24}\Z")
_SAFE_INTERVAL = re.compile(r"[A-Za-z0-9_-]{1,16}\Z")
_EIGHTY_PERCENT = Decimal("0.8")


@dataclass(frozen=True, slots=True)
class FailurePresentation:
    tone: str
    title: str
    message: str
    primary_action: str = ""
    primary_label: str = ""
    modal: bool = False


@dataclass(frozen=True, slots=True)
class FailureState:
    recovery_visible: bool = False
    recovery_tone: str = "neutral"
    recovery_message: str = ""
    retry_count: int = 0
    wait_seconds: float = 0
    active_concurrency: int = 4
    outcome_visible: bool = False
    outcome_tone: str = "neutral"
    outcome_title: str = ""
    outcome_summary: str = ""
    outcome_primary_action: str = ""
    outcome_primary_label: str = ""
    failures: tuple[RunFeedback, ...] = ()


_FAILURES = {
    FailureCode.TIMEOUT: (
        "请求超时",
        "服务响应超时，请稍后重试。",
        "retry",
        "重试",
    ),
    FailureCode.NETWORK_ERROR: (
        "网络不可用",
        "暂时无法连接数据服务，请检查网络后重试。",
        "retry",
        "重试",
    ),
    FailureCode.SERVICE_UNAVAILABLE: (
        "服务暂不可用",
        "数据服务暂不可用，请稍后重试。",
        "retry",
        "重试",
    ),
    FailureCode.RATE_LIMITED: (
        "请求受到限制",
        "请求过快，已降低并发；请稍后重试。",
        "retry",
        "稍后重试",
    ),
    FailureCode.QUOTA_EXHAUSTED: (
        "服务配额已用完",
        "当前服务配额不足，请在设置中检查账户配额。",
        "open_settings",
        "检查服务设置",
    ),
    FailureCode.AUTHENTICATION_FAILED: (
        "授权已失效",
        "数据服务授权无效，请检查授权设置后重试。",
        "open_settings",
        "检查授权设置",
    ),
    FailureCode.PERMISSION_DENIED: (
        "权限不足",
        "当前账户没有所需权限，请在设置中检查服务权限。",
        "open_settings",
        "检查服务设置",
    ),
    FailureCode.MALFORMED_RESPONSE: (
        "数据格式异常",
        "服务返回的数据无法安全解析，请稍后重试。",
        "retry",
        "重试",
    ),
    FailureCode.DATA_UNAVAILABLE: (
        "数据暂不可用",
        "所需数据暂不可用，可稍后重试或调整范围。",
        "retry",
        "重试",
    ),
    FailureCode.INSUFFICIENT_DATA: (
        "数据不足",
        "可用数据不足，请调整股票池、周期或日期范围。",
        "",
        "",
    ),
    FailureCode.DATABASE_BUSY: (
        "数据库正忙",
        "本机数据库正忙，请稍后重试。",
        "retry",
        "重试",
    ),
    FailureCode.STORAGE_UNAVAILABLE: (
        "存储不可用",
        "无法使用本机存储，请检查存储空间和目录设置。",
        "open_settings",
        "检查存储设置",
    ),
    FailureCode.DATABASE_CORRUPT: (
        "数据库需要处理",
        "本机数据库无法安全读取，请检查存储设置。",
        "open_settings",
        "检查存储设置",
    ),
    FailureCode.MEMORY_EXHAUSTED: (
        "内存不足",
        "当前范围占用内存过大，请缩小股票池或周期范围后重试。",
        "retry",
        "缩小范围后重试",
    ),
    FailureCode.INTERNAL: (
        "运行未完成",
        "发生内部错误，未显示技术细节；请稍后重试。",
        "retry",
        "重试",
    ),
}

_SAVE_FAILURES = {
    "history_save_failed": FailureCode.STORAGE_UNAVAILABLE,
    "persistence_failed": FailureCode.INTERNAL,
    "persistence_internal": FailureCode.INTERNAL,
    "persistence_data_error": FailureCode.DATABASE_CORRUPT,
    "persistence_conflict": FailureCode.DATABASE_BUSY,
    "concurrent_modification": FailureCode.DATABASE_BUSY,
    "data_validation_failed": FailureCode.DATABASE_CORRUPT,
    "database_busy": FailureCode.DATABASE_BUSY,
    "database_corrupt": FailureCode.DATABASE_CORRUPT,
    "migration_incompatible": FailureCode.DATABASE_CORRUPT,
    "storage_unavailable": FailureCode.STORAGE_UNAVAILABLE,
}

_AI_REPORT_FAILURES = {
    "canceled": "AI 解读已取消。",
    "ai_configuration_invalid": "AI 尚未配置，请先在设置中完成 AI 质检。",
    "rs_report_evidence_unavailable": "本次结果不足，无法生成 AI 解读。",
    "turning_point_report_evidence_unavailable": "本次结果不足，无法生成 AI 解读。",
    "authentication_failed": "AI 授权失败，请检查 API Key。",
    "permission_denied": "AI 服务权限不足，请检查模型与账户权限。",
    "quota_exhausted": "AI 服务配额已用完，请在设置中检查账户配额。",
    "rate_limited": "AI 服务请求过于频繁，请稍后再试。",
    "timeout": "AI 服务响应超时，请稍后再试。",
    "network_error": "无法连接 AI 服务，请检查网络和 Base URL。",
    "invalid_response": "AI 返回内容无法识别，请重新生成。",
    "malformed_response": "AI 返回内容无法识别，请重新生成。",
    "service_unavailable": "AI 服务暂时不可用，请稍后再试。",
}


def present_failure(
    code: FailureCode,
    *,
    detail: object | None = None,
) -> FailurePresentation:
    """Map a stable code to safe copy; untrusted detail is deliberately ignored."""
    del detail
    title, message, action, label = _FAILURES[code]
    return FailurePresentation("danger", title, message, action, label)


def present_ai_report_failure(raw: object) -> FailurePresentation:
    """Return sanitized report-local copy without exposing exception details."""
    code = getattr(raw, "code", None)
    if not isinstance(code, str):
        code = str(raw)
    message = _AI_REPORT_FAILURES.get(
        code,
        "AI 解读失败，请检查配置后重试。",
    )
    return FailurePresentation("danger", "AI 解读未生成", message)


def present_feedback(feedback: RunFeedback) -> FailurePresentation:
    target = _target(feedback)
    if feedback.kind is FeedbackKind.RETRYING:
        attempt = max(1, feedback.attempt)
        limit = max(attempt, feedback.max_attempts)
        message = f"{target} · 第 {attempt} 次重试（最多 {limit} 次）"
        return FailurePresentation("warning", "正在恢复连接", message)
    if feedback.kind is FeedbackKind.THROTTLED:
        wait = _seconds(feedback.wait_seconds)
        message = f"请求过快，等待 {wait} 秒后继续；并发已降至 1"
        return FailurePresentation("warning", "已降低请求速度", message)
    if feedback.kind is FeedbackKind.RECOVERED:
        return FailurePresentation(
            "success",
            "连接已恢复",
            f"{target} 已恢复，继续运行。",
        )
    if feedback.kind is FeedbackKind.ITEM_SKIPPED:
        return FailurePresentation(
            "warning",
            "已跳过一个项目",
            f"{target} 暂不可用，已跳过并继续处理其他项目。",
        )
    if feedback.kind is FeedbackKind.CIRCUIT_OPEN:
        return FailurePresentation(
            "warning",
            "已暂停新的数据请求",
            f"{target} 连续请求失败，已保留当前失败原因和未执行项目。",
        )
    return present_failure(feedback.failure_code or FailureCode.INTERNAL)


def present_summary(summary: RunReliabilitySummary) -> FailurePresentation:
    counts = (
        f"成功 {summary.succeeded}，失败 {summary.failed}，"
        f"未执行 {summary.unexecuted}"
    )
    rate = _percentage(summary.success_rate)
    if summary.terminal is RunTerminal.READY:
        return FailurePresentation(
            "success",
            "分析完成",
            f"成功率 {rate}（{counts}），结果已保存。",
        )
    if summary.terminal is RunTerminal.PARTIAL:
        return FailurePresentation(
            "warning",
            "结果可用但不完整",
            f"成功率 {rate}（{counts}），可用结果已保存。",
        )
    message = (
        f"成功率 {rate}（{counts}），低于 80%，未保存历史记录。"
        if summary.success_rate < _EIGHTY_PERCENT
        else f"成功率 {rate}（{counts}），本次没有新增历史记录。"
    )
    return FailurePresentation(
        "danger",
        "本次结果未保存",
        message,
        "retry",
        "调整后重试",
    )


def advance_feedback(
    state: FailureState,
    feedback: RunFeedback,
) -> FailureState:
    if feedback.kind is FeedbackKind.RECOVERED:
        presentation = present_feedback(feedback)
        return replace(
            state,
            recovery_visible=True,
            recovery_tone=presentation.tone,
            recovery_message=presentation.message,
            retry_count=0,
            wait_seconds=0,
            active_concurrency=max(1, feedback.active_concurrency),
        )
    presentation = present_feedback(feedback)
    failures = state.failures
    if feedback.kind in {
        FeedbackKind.ITEM_SKIPPED,
        FeedbackKind.CIRCUIT_OPEN,
        FeedbackKind.FATAL,
    }:
        failures += (feedback,)
    if feedback.kind is FeedbackKind.FATAL:
        return replace(
            state,
            recovery_visible=False,
            recovery_tone="neutral",
            recovery_message="",
            retry_count=0,
            wait_seconds=0,
            active_concurrency=4,
            outcome_visible=True,
            outcome_tone=presentation.tone,
            outcome_title=presentation.title,
            outcome_summary=presentation.message,
            outcome_primary_action=presentation.primary_action,
            outcome_primary_label=presentation.primary_label,
            failures=failures,
        )
    return replace(
        state,
        recovery_visible=True,
        recovery_tone=presentation.tone,
        recovery_message=presentation.message,
        retry_count=(
            max(1, feedback.attempt)
            if feedback.kind is FeedbackKind.RETRYING
            else 0
        ),
        wait_seconds=(
            max(0, feedback.wait_seconds)
            if feedback.kind in {
                FeedbackKind.RETRYING,
                FeedbackKind.THROTTLED,
            }
            else 0
        ),
        active_concurrency=max(1, feedback.active_concurrency),
        failures=failures,
    )


def advance_running(state: FailureState) -> FailureState:
    """Collapse a recovered notice on the next ordinary progress transition."""
    if state.recovery_tone != "success":
        return state
    return replace(
        state,
        recovery_visible=False,
        recovery_tone="neutral",
        recovery_message="",
        retry_count=0,
        wait_seconds=0,
    )


def finish_outcome(
    state: FailureState,
    status: str,
    reliability: AnalysisReliability | None,
    error_code: str | None = None,
) -> FailureState:
    if status == "CANCELED":
        return FailureState()
    if reliability is not None:
        save_failure = _save_failure(error_code)
        terminal = {
            "READY": RunTerminal.READY,
            "PARTIAL": RunTerminal.PARTIAL,
        }.get(status, RunTerminal.FAILED)
        summary = RunReliabilitySummary(
            reliability.succeeded_tasks,
            reliability.failed_tasks,
            reliability.unexecuted_tasks,
            reliability.success_rate,
            terminal,
            status in {"READY", "PARTIAL"},
        )
        if save_failure is not None:
            failure = present_failure(save_failure)
            presentation = FailurePresentation(
                "danger",
                "分析完成，但未保存",
                (
                    f"分析已完成（成功率 {_percentage(reliability.success_rate)}），"
                    f"但本地保存失败，本次没有新增历史记录。{failure.message}"
                ),
                failure.primary_action,
                failure.primary_label,
            )
        else:
            presentation = present_summary(summary)
            failure_code = _terminal_failure(
                error_code,
                reliability.primary_failure_code,
            )
            if terminal is RunTerminal.FAILED and failure_code is not None:
                failure = present_failure(failure_code)
                message = (
                    f"{failure.message} {presentation.message}"
                    if reliability.success_rate < _EIGHTY_PERCENT
                    else (
                        f"{failure.message} 本次没有新增历史记录。"
                    )
                )
                presentation = replace(
                    presentation,
                    title=failure.title,
                    message=message,
                    primary_action=(
                        failure.primary_action
                        or presentation.primary_action
                    ),
                    primary_label=(
                        failure.primary_label
                        or presentation.primary_label
                    ),
                )
    elif status == "READY":
        presentation = FailurePresentation(
            "success",
            "分析完成",
            "结果已完成并保存。",
        )
    elif status == "PARTIAL":
        presentation = FailurePresentation(
            "warning",
            "结果可用但不完整",
            "部分项目未完成，可用结果已保存。",
        )
    else:
        presentation = present_failure(
            _coerce_failure(error_code) or FailureCode.INTERNAL
        )
    return replace(
        state,
        recovery_visible=False,
        recovery_tone="neutral",
        recovery_message="",
        retry_count=0,
        wait_seconds=0,
        active_concurrency=4,
        outcome_visible=True,
        outcome_tone=presentation.tone,
        outcome_title=presentation.title,
        outcome_summary=presentation.message,
        outcome_primary_action=presentation.primary_action,
        outcome_primary_label=presentation.primary_label,
    )


def group_failures(feedback: Iterable[RunFeedback]) -> list[dict[str, object]]:
    grouped: dict[str, tuple[int, set[str], set[str]]] = {}
    for item in feedback:
        if item.failure_code is None:
            continue
        code = item.failure_code.value
        count, symbols, intervals = grouped.get(code, (0, set(), set()))
        symbol = _safe_symbol(item.symbol)
        interval = _safe_interval(item.interval)
        if symbol:
            symbols.add(symbol)
        if interval:
            intervals.add(interval)
        grouped[code] = (count + 1, symbols, intervals)
    return [
        {
            "code": code,
            "count": count,
            "symbols": sorted(symbols),
            "intervals": sorted(intervals),
        }
        for code, (count, symbols, intervals) in sorted(grouped.items())
    ]


def _target(feedback: RunFeedback) -> str:
    symbol = _safe_symbol(feedback.symbol)
    interval = _safe_interval(feedback.interval)
    return " · ".join(item for item in (symbol, interval) if item) or "当前项目"


def _safe_symbol(value: str) -> str:
    normalized = value.strip().upper()
    return normalized if _SAFE_SYMBOL.fullmatch(normalized) else ""


def _safe_interval(value: str) -> str:
    normalized = value.strip()
    return normalized if _SAFE_INTERVAL.fullmatch(normalized) else ""


def _seconds(value: float) -> str:
    safe = max(0.0, value)
    return str(int(safe)) if safe.is_integer() else f"{safe:.1f}"


def _percentage(value: Decimal) -> str:
    percentage = (value * 100).quantize(
        Decimal("0.1"),
        rounding=ROUND_DOWN,
    )
    text = format(percentage, "f")
    return f"{text.removesuffix('.0')}%"


def _coerce_failure(value: str | None) -> FailureCode | None:
    if value is None:
        return None
    try:
        return FailureCode(value.strip().lower())
    except ValueError:
        return {
            "benchmark_fetch_failed": FailureCode.DATA_UNAVAILABLE,
            "history_save_failed": FailureCode.STORAGE_UNAVAILABLE,
            "insufficient_reliable_results": FailureCode.INSUFFICIENT_DATA,
        }.get(value.strip().lower())


def _save_failure(value: str | None) -> FailureCode | None:
    return _SAVE_FAILURES.get(value.strip().lower()) if value else None


def _terminal_failure(
    error_code: str | None,
    primary_failure_code: str | None,
) -> FailureCode | None:
    error = _coerce_failure(error_code)
    primary = _coerce_failure(primary_failure_code)
    if error in {
        None,
        FailureCode.DATA_UNAVAILABLE,
        FailureCode.INSUFFICIENT_DATA,
    }:
        return primary or error
    return error
