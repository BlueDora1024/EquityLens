from __future__ import annotations

import pytest

from stock_toolbox.desktop_qml.report_operation import (
    execute_report_operation,
    reserve_report_operation,
)
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError


@pytest.mark.parametrize(
    "error_code",
    [
        "ai_configuration_invalid",
        "rs_report_evidence_unavailable",
        "turning_point_report_evidence_unavailable",
    ],
)
def test_report_operation_preserves_only_whitelisted_runtime_code(
    scenario_application,
    error_code: str,
) -> None:
    operation_id = f"known-report-{error_code}"
    assert reserve_report_operation(scenario_application, operation_id)

    result = execute_report_operation(
        scenario_application,
        operation_id,
        lambda _control: (_ for _ in ()).throw(
            RuntimeError(error_code)
        ),
    )

    assert isinstance(result, AIAdapterError)
    assert result.code == error_code


def test_report_operation_hides_arbitrary_runtime_detail(
    scenario_application,
) -> None:
    assert reserve_report_operation(scenario_application, "secret-report")

    result = execute_report_operation(
        scenario_application,
        "secret-report",
        lambda _control: (_ for _ in ()).throw(
            RuntimeError("Authorization: Bearer secret")
        ),
    )

    assert isinstance(result, AIAdapterError)
    assert result.code == "report_failed"
    assert "secret" not in str(result)
