from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from stock_toolbox.core.market_data.fallback import FallbackOffer
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.desktop_qml.fallback_consent import FallbackConsentGate


def _offer() -> FallbackOffer:
    return FallbackOffer(
        "turning_point",
        ("A.US", "B.US"),
        ("1d",),
        (FailureCode.TIMEOUT,),
        8,
        10,
    )


def test_gate_waits_off_ui_thread_and_resolves_once(qtbot) -> None:
    gate = FallbackConsentGate()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gate.request, _offer())
        qtbot.waitUntil(lambda: gate.pending)

        assert gate.operation_label == "拐点筛选"
        assert gate.failed_count == 2
        assert gate.completed_count == 8
        assert gate.total_count == 10
        assert gate.failure_text == "请求超时"

        gate.accept()
        assert future.result(timeout=1) is True

    assert gate.request(_offer()) is True


def test_gate_cancel_releases_waiting_worker(qtbot) -> None:
    gate = FallbackConsentGate()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(gate.request, _offer())
        qtbot.waitUntil(lambda: gate.pending)
        gate.cancel()
        assert future.result(timeout=1) is False


def test_gate_presents_process_offer_without_blocking_and_emits_decision() -> None:
    gate = FallbackConsentGate()
    decisions: list[bool] = []
    gate.resolved.connect(decisions.append)

    gate.present(_offer())

    assert gate.pending is True
    assert gate.failed_count == 2
    gate.decline()
    assert decisions == [False]
    assert gate.pending is False


def test_gate_routes_to_network_settings_once_and_ends_primary_attempt() -> None:
    gate = FallbackConsentGate()
    routes: list[bool] = []
    decisions: list[bool] = []
    gate.settings_requested.connect(lambda: routes.append(True))
    gate.resolved.connect(decisions.append)
    gate.present(_offer())

    gate.open_network_settings()
    gate.open_network_settings()

    assert routes == [True]
    assert decisions == [False]
    assert gate.pending is False
