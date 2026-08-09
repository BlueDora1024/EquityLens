from __future__ import annotations

from decimal import Decimal

import pytest

from stock_toolbox.core.operations.failure_policy import (
    AnalysisReliability,
    FailureCode,
    RunReliabilitySummary,
    RunTerminal,
)
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.desktop_qml.failure_presentation import (
    FailureState,
    advance_feedback,
    advance_running,
    finish_outcome,
    group_failures,
    present_failure,
    present_feedback,
    present_summary,
)


def test_retry_feedback_is_yellow_and_does_not_open_dialog() -> None:
    state = present_feedback(
        RunFeedback(
            FeedbackKind.RETRYING,
            FailureCode.TIMEOUT,
            "IREN.US",
            attempt=2,
            max_attempts=2,
        )
    )

    assert state.tone == "warning"
    assert state.modal is False
    assert "第 2 次重试" in state.message


def test_fatal_auth_has_one_settings_action() -> None:
    state = present_failure(FailureCode.AUTHENTICATION_FAILED)

    assert state.tone == "danger"
    assert state.primary_action == "open_settings"
    assert state.primary_label == "检查授权设置"
    assert state.modal is False


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (FailureCode.QUOTA_EXHAUSTED, "配额"),
        (FailureCode.STORAGE_UNAVAILABLE, "存储"),
        (FailureCode.DATABASE_BUSY, "数据库"),
        (FailureCode.DATABASE_CORRUPT, "数据库"),
        (FailureCode.MEMORY_EXHAUSTED, "范围"),
        (FailureCode.INTERNAL, "稍后重试"),
    ],
)
def test_failure_copy_is_stable_and_sanitized(
    code: FailureCode,
    expected: str,
) -> None:
    raw = "Authorization: Bearer secret api_key=abc SELECT * FROM runs"

    state = present_failure(code, detail=raw)

    assert expected in state.message
    assert state.modal is False
    assert raw not in state.message
    assert "secret" not in state.message
    assert "SELECT" not in state.message


def test_partial_summary_says_results_are_usable_and_incomplete() -> None:
    state = present_summary(
        RunReliabilitySummary(
            succeeded=8,
            failed=1,
            unexecuted=1,
            success_rate=Decimal("0.8"),
            terminal=RunTerminal.PARTIAL,
            should_save=True,
        )
    )

    assert state.tone == "warning"
    assert "可用但不完整" in state.title
    assert "80%" in state.message
    assert "成功 8" in state.message
    assert "失败 1" in state.message
    assert "未执行 1" in state.message


def test_failed_summary_says_below_eighty_percent_is_not_saved() -> None:
    state = present_summary(
        RunReliabilitySummary(
            succeeded=7,
            failed=2,
            unexecuted=1,
            success_rate=Decimal("0.7"),
            terminal=RunTerminal.FAILED,
            should_save=False,
        )
    )

    assert state.tone == "danger"
    assert state.title == "本次结果未保存"
    assert "70%" in state.message
    assert "低于 80%" in state.message
    assert "未保存历史记录" in state.message


def test_failure_groups_are_deterministic_and_sanitize_evidence() -> None:
    feedback = (
        RunFeedback(
            FeedbackKind.ITEM_SKIPPED,
            FailureCode.TIMEOUT,
            "bad\nAuthorization: secret",
            "1d<script>",
        ),
        RunFeedback(
            FeedbackKind.ITEM_SKIPPED,
            FailureCode.TIMEOUT,
            "IREN.US",
            "1d",
        ),
        RunFeedback(
            FeedbackKind.CIRCUIT_OPEN,
            FailureCode.RATE_LIMITED,
            "NVDA.US",
            "1h",
        ),
    )

    groups = group_failures(feedback)

    assert groups == [
        {
            "code": "rate_limited",
            "count": 1,
            "symbols": ["NVDA.US"],
            "intervals": ["1h"],
        },
        {
            "code": "timeout",
            "count": 2,
            "symbols": ["IREN.US"],
            "intervals": ["1d"],
        },
    ]
    assert "secret" not in repr(groups)


def test_recovered_collapses_inline_state_and_fatal_stays_non_modal() -> None:
    retrying = advance_feedback(
        FailureState(),
        RunFeedback(
            FeedbackKind.RETRYING,
            FailureCode.TIMEOUT,
            "IREN.US",
            attempt=1,
            max_attempts=2,
        ),
    )
    recovered = advance_feedback(
        retrying,
        RunFeedback(FeedbackKind.RECOVERED, symbol="IREN.US"),
    )
    stable = advance_running(recovered)
    fatal = advance_feedback(
        stable,
        RunFeedback(
            FeedbackKind.FATAL,
            FailureCode.AUTHENTICATION_FAILED,
            "IREN.US",
        ),
    )

    assert recovered.recovery_visible is True
    assert recovered.recovery_tone == "success"
    assert stable.recovery_visible is False
    assert stable.recovery_tone == "neutral"
    assert fatal.outcome_visible is True
    assert fatal.outcome_primary_action == "open_settings"
    assert present_feedback(
        RunFeedback(
            FeedbackKind.FATAL,
            FailureCode.AUTHENTICATION_FAILED,
        )
    ).modal is False


def test_complete_without_reliability_is_still_green() -> None:
    state = finish_outcome(FailureState(), "READY", None)

    assert state.outcome_tone == "success"
    assert state.outcome_title == "分析完成"


def test_failed_auth_summary_keeps_no_save_copy_and_one_settings_action() -> None:
    state = finish_outcome(
        FailureState(),
        "FAILED",
        AnalysisReliability(
            7,
            2,
            1,
            Decimal("0.7"),
            False,
            FailureCode.AUTHENTICATION_FAILED.value,
        ),
    )

    assert "未保存历史记录" in state.outcome_summary
    assert state.outcome_primary_action == "open_settings"
    assert state.outcome_primary_label == "检查授权设置"


@pytest.mark.parametrize(
    ("code", "title", "label"),
    [
        (
            FailureCode.AUTHENTICATION_FAILED,
            "授权已失效",
            "检查授权设置",
        ),
        (
            FailureCode.QUOTA_EXHAUSTED,
            "服务配额已用完",
            "检查服务设置",
        ),
    ],
)
def test_primary_fatal_cause_beats_generic_insufficient_result_code(
    code: FailureCode,
    title: str,
    label: str,
) -> None:
    state = finish_outcome(
        FailureState(),
        "FAILED",
        AnalysisReliability(
            7,
            2,
            1,
            Decimal("0.7"),
            False,
            code.value,
        ),
        "insufficient_reliable_results",
    )

    assert state.outcome_title == title
    assert state.outcome_primary_action == "open_settings"
    assert state.outcome_primary_label == label
    assert "未保存历史记录" in state.outcome_summary


@pytest.mark.parametrize(
    "error_code",
    [
        "history_save_failed",
        "HISTORY_SAVE_FAILED",
        "persistence_failed",
        "persistence_internal",
        "persistence_data_error",
        "persistence_conflict",
        "concurrent_modification",
        "data_validation_failed",
    ],
)
def test_complete_analysis_with_save_failure_has_truthful_copy(
    error_code: str,
) -> None:
    state = finish_outcome(
        FailureState(),
        "FAILED",
        AnalysisReliability(
            10,
            0,
            0,
            Decimal(1),
            False,
            None,
        ),
        error_code,
    )

    assert state.outcome_title == "分析完成，但未保存"
    assert "本地保存失败" in state.outcome_summary
    assert "没有新增历史记录" in state.outcome_summary
    assert "低于 80%" not in state.outcome_summary
    assert state.outcome_primary_action


def test_retry_feedback_preserves_wait_seconds() -> None:
    state = advance_feedback(
        FailureState(),
        RunFeedback(
            FeedbackKind.RETRYING,
            FailureCode.TIMEOUT,
            "IREN.US",
            attempt=2,
            max_attempts=3,
            wait_seconds=1.5,
        ),
    )

    assert state.wait_seconds == 1.5


def test_cancel_after_fatal_clears_danger_action_and_failure_groups() -> None:
    fatal = advance_feedback(
        FailureState(),
        RunFeedback(
            FeedbackKind.FATAL,
            FailureCode.AUTHENTICATION_FAILED,
            "IREN.US",
        ),
    )

    canceled = finish_outcome(fatal, "CANCELED", None)

    assert canceled.recovery_visible is False
    assert canceled.outcome_visible is False
    assert canceled.outcome_tone == "neutral"
    assert canceled.outcome_primary_action == ""
    assert group_failures(canceled.failures) == []


@pytest.mark.parametrize(
    ("succeeded", "total", "expected"),
    [
        (159, 200, "79.5%"),
        (4, 5, "80%"),
        (1, 1, "100%"),
    ],
)
def test_success_percentage_never_rounds_up_across_policy_boundary(
    succeeded: int,
    total: int,
    expected: str,
) -> None:
    failed = total - succeeded
    terminal = (
        RunTerminal.FAILED
        if succeeded * 5 < total * 4
        else RunTerminal.PARTIAL
        if failed
        else RunTerminal.READY
    )
    state = present_summary(
        RunReliabilitySummary(
            succeeded,
            failed,
            0,
            Decimal(succeeded) / Decimal(total),
            terminal,
            terminal is not RunTerminal.FAILED,
        )
    )

    assert expected in state.message
    assert not (
        succeeded * 5 < total * 4
        and "成功率 80%" in state.message
    )


@pytest.mark.parametrize(
    "transition",
    [
        FeedbackKind.RECOVERED,
        FeedbackKind.ITEM_SKIPPED,
        FeedbackKind.CIRCUIT_OPEN,
        FeedbackKind.FATAL,
    ],
)
def test_non_waiting_feedback_clears_stale_retry_state(
    transition: FeedbackKind,
) -> None:
    retrying = advance_feedback(
        FailureState(),
        RunFeedback(
            FeedbackKind.RETRYING,
            FailureCode.TIMEOUT,
            "IREN.US",
            attempt=2,
            max_attempts=3,
            wait_seconds=4,
        ),
    )

    state = advance_feedback(
        retrying,
        RunFeedback(
            transition,
            (
                FailureCode.AUTHENTICATION_FAILED
                if transition is FeedbackKind.FATAL
                else FailureCode.TIMEOUT
            ),
            "IREN.US",
        ),
    )

    assert state.retry_count == 0
    assert state.wait_seconds == 0


def test_terminal_transition_clears_stale_retry_state() -> None:
    retrying = advance_feedback(
        FailureState(),
        RunFeedback(
            FeedbackKind.RETRYING,
            FailureCode.TIMEOUT,
            attempt=2,
            max_attempts=3,
            wait_seconds=4,
        ),
    )

    terminal = finish_outcome(retrying, "FAILED", None, "internal")

    assert terminal.retry_count == 0
    assert terminal.wait_seconds == 0
    assert terminal.active_concurrency == 4


def test_ordinary_progress_preserves_provider_reduced_concurrency() -> None:
    assert FailureState().active_concurrency == 4
    throttled = advance_feedback(
        FailureState(),
        RunFeedback(
            FeedbackKind.THROTTLED,
            FailureCode.RATE_LIMITED,
            active_concurrency=1,
        ),
    )
    recovered = advance_feedback(
        throttled,
        RunFeedback(
            FeedbackKind.RECOVERED,
            active_concurrency=1,
        ),
    )

    running = advance_running(recovered)

    assert running.recovery_visible is False
    assert running.active_concurrency == 1
