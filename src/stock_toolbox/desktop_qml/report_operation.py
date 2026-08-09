"""One registry lifecycle for manually requested AI reports."""

from __future__ import annotations

from collections.abc import Callable

from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.operations.executor import (
    ExecuteReservedOperation,
    OperationAdmissionClosedError,
    OperationCandidate,
)
from stock_toolbox.core.operations.registry import (
    OperationControl,
    OperationExecutionContext,
    OperationStatus,
    ReserveResult,
)
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError

_VISIBLE_RUNTIME_CODES = frozenset(
    {
        "ai_configuration_invalid",
        "rs_report_evidence_unavailable",
        "turning_point_report_evidence_unavailable",
    }
)


def reserve_report_operation(
    application: StockToolboxApplication,
    operation_id: str,
) -> bool:
    decision = application.registry.reserve(
        operation_id,
        operation_id,
        "ai_report",
    )
    return decision.result is ReserveResult.RESERVED


def execute_report_operation(
    application: StockToolboxApplication,
    operation_id: str,
    generate: Callable[[OperationControl], object],
) -> object:
    def handler(
        context: OperationExecutionContext,
    ) -> OperationCandidate:
        if context.operation_control.cancellation_requested():
            error = AIAdapterError("canceled")
            return OperationCandidate(OperationStatus.CANCELED, {}, error)
        try:
            report = generate(context.operation_control)
        except AIAdapterError as error:
            terminal = (
                OperationStatus.CANCELED
                if error.code == "canceled"
                else OperationStatus.FAILED
            )
            summary = (
                {}
                if terminal is OperationStatus.CANCELED
                else {"error_code": error.code}
            )
            return OperationCandidate(terminal, summary, error)
        except RuntimeError as error:
            raw_code = str(error)
            report_error = AIAdapterError(
                raw_code
                if raw_code in _VISIBLE_RUNTIME_CODES
                else "report_failed"
            )
            return OperationCandidate(
                OperationStatus.FAILED,
                {"error_code": report_error.code},
                report_error,
            )
        except Exception:  # noqa: BLE001 - UI sanitizes report errors
            report_error = AIAdapterError("report_failed")
            return OperationCandidate(
                OperationStatus.FAILED,
                {"error_code": "report_failed"},
                report_error,
            )
        if context.operation_control.cancellation_requested():
            cancellation_error = AIAdapterError("canceled")
            return OperationCandidate(
                OperationStatus.CANCELED,
                {},
                cancellation_error,
            )
        return OperationCandidate(OperationStatus.SUCCEEDED, {}, report)

    executed = ExecuteReservedOperation(application.registry).execute(
        operation_id,
        handler,
    )
    if executed.payload is not None:
        return executed.payload
    if executed.snapshot.status is OperationStatus.CANCELED:
        return AIAdapterError("canceled")
    if not executed.handler_started:
        return OperationAdmissionClosedError(
            "report operation did not start"
        )
    return AIAdapterError(
        str(executed.snapshot.summary.get("error_code", "internal"))
    )
