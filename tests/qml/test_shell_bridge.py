from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtTest import QSignalSpy, QTest

from stock_toolbox.core.operations.registry import (
    OperationRegistry,
    OperationStatus,
)
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge


class _ConstructorRaceRegistry:
    def __init__(self, delegate: OperationRegistry) -> None:
        self._delegate = delegate
        self.registration_reached = threading.Event()
        self.transitions_finished = threading.Event()

    def has_active_operations(self) -> bool:
        active = self._delegate.has_active_operations()
        self.registration_reached.set()
        assert self.transitions_finished.wait(timeout=2)
        return active

    def subscribe(
        self,
        listener: Callable[[bool], None],
    ) -> Callable[[], None]:
        return self._delegate.subscribe(listener)

    def subscribe_with_snapshot(
        self,
        listener: Callable[[bool], None],
    ) -> tuple[Callable[[], None], bool]:
        subscription = self._delegate.subscribe_with_snapshot(listener)
        self.registration_reached.set()
        assert self.transitions_finished.wait(timeout=2)
        return subscription

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


def test_shell_bridge_builds_navigation_from_analysis_registry(
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)

    assert bridge.current_page == "securities"
    page_ids = {
        str(item["pageId"])
        for item in bridge.navigation
        if item["kind"] in {"item", "subitem"}
    }
    assert {"securities", "classifications", "watchlists"} <= page_ids
    for analysis_id in ("rs_strength", "turning_point"):
        assert f"{analysis_id}.run" in page_ids
        assert f"{analysis_id}.history" in page_ids
    assert "extreme_deviation.run" in page_ids
    assert "extreme_deviation.results" in page_ids
    assert "extreme_deviation.history" not in page_ids
    visibility = {
        str(item["pageId"]): bool(item["visible"])
        for item in bridge.navigation
        if item["kind"] == "subitem"
    }
    assert visibility["rs_strength.run"] is False
    assert visibility["extreme_deviation.run"] is False
    tools = {
        str(item.get("analysisId", "")): item
        for item in bridge.navigation
        if item["kind"] == "tool"
    }
    assert "跑赢基准" in str(tools["rs_strength"]["helpText"])
    assert "底背离" in str(tools["turning_point"]["helpText"])
    assert "多周期" in str(tools["turning_point"]["helpText"])
    assert "负分" in str(tools["extreme_deviation"]["helpText"])
    assert "绝对值" in str(tools["extreme_deviation"]["helpText"])


def test_shell_bridge_changes_only_to_known_pages(
    qtbot,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)

    with qtbot.waitSignal(bridge.changed):
        assert bridge.navigate("watchlists") is True

    assert bridge.current_page == "watchlists"
    assert bridge.navigate("missing") is False
    assert bridge.current_page == "watchlists"


def test_shell_bridge_persists_product_tour_dismissal(
    qtbot,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)

    assert bridge.product_tour_dismissed is False
    with qtbot.waitSignal(bridge.changed):
        assert bridge.dismiss_product_tour() is True

    assert bridge.product_tour_dismissed is True
    assert scenario_application.settings().product_tour_dismissed is True
    assert bridge.dismiss_product_tour() is True


def test_shell_bridge_tracks_registry_execution_without_polling(
    qtbot,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)
    registry = scenario_application.registry

    assert bridge.has_active_operation is False
    with qtbot.waitSignal(bridge.active_operation_changed):
        registry.reserve("active", "active-key", "analysis")
    assert bridge.has_active_operation is True

    registry.begin_reserved("active")
    assert bridge.cancel_active_operation() is True
    assert registry.status("active").status is OperationStatus.CANCELED
    assert bridge.has_active_operation is True

    with qtbot.waitSignal(bridge.active_operation_changed):
        registry.try_complete("active", OperationStatus.CANCELED, {})
    assert bridge.has_active_operation is False


def test_shell_bridge_does_not_force_cancel_committing_operations(
    qtbot,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)
    registry = scenario_application.registry
    with qtbot.waitSignal(bridge.active_operation_changed):
        registry.reserve("commit", "commit-key", "analysis")
    context = registry.begin_reserved("commit")
    assert context is not None
    assert context.operation_control.try_enter_committing() is True

    assert bridge.has_active_operation is True
    assert bridge.cancel_active_operation() is False
    assert bridge.has_active_operation is True

    with qtbot.waitSignal(bridge.active_operation_changed):
        registry.try_complete("commit", OperationStatus.SUCCEEDED, {})
    assert bridge.has_active_operation is False


def test_shell_bridge_no_active_operation_is_a_noop(
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)

    assert bridge.has_active_operation is False
    assert bridge.cancel_active_operation() is False


def test_shell_bridge_preserves_rapid_active_and_inactive_edges(
    qapp,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)
    registry = scenario_application.registry
    spy = QSignalSpy(bridge.active_operation_changed)

    registry.reserve("rapid", "rapid-key", "analysis")
    registry.begin_reserved("rapid")
    registry.try_complete("rapid", OperationStatus.SUCCEEDED, {})
    QTest.qWait(20)

    assert [spy.at(index)[0] for index in range(spy.count())] == [
        True,
        False,
    ]
    assert bridge.has_active_operation is False
    assert bridge._has_active_operation is False


def test_shell_bridge_preserves_repeated_and_committing_edges(
    qapp,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)
    registry = scenario_application.registry
    spy = QSignalSpy(bridge.active_operation_changed)

    for suffix in ("one", "two"):
        registry.reserve(suffix, f"{suffix}-key", "analysis")
        context = registry.begin_reserved(suffix)
        assert context is not None
        if suffix == "two":
            assert context.operation_control.try_enter_committing() is True
        registry.try_complete(suffix, OperationStatus.SUCCEEDED, {})
    QTest.qWait(20)

    assert [spy.at(index)[0] for index in range(spy.count())] == [
        True,
        False,
        True,
        False,
    ]


def test_shell_bridge_unsubscribes_when_destroyed(
    qtbot,
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)
    registry = scenario_application.registry
    assert len(registry._listeners) == 1

    with qtbot.waitSignal(bridge.destroyed):
        bridge.deleteLater()

    assert not registry._listeners


def test_shell_bridge_close_unsubscribes_idempotently(
    scenario_application,
) -> None:
    bridge = ShellBridge(scenario_application)
    registry = scenario_application.registry
    assert len(registry._listeners) == 1

    bridge.close()
    bridge.close()

    assert not registry._listeners


def test_shell_bridge_constructor_preserves_edges_around_atomic_snapshot(
    qapp,
    scenario_application,
) -> None:
    registry = scenario_application.registry
    race_registry = _ConstructorRaceRegistry(registry)
    scenario_application.registry = race_registry
    errors: list[Exception] = []

    def transition_during_construction() -> None:
        try:
            assert race_registry.registration_reached.wait(timeout=2)
            registry.reserve("constructor", "constructor-key", "analysis")
            registry.try_complete(
                "constructor",
                OperationStatus.SUCCEEDED,
                {},
            )
        except (AssertionError, RuntimeError) as error:
            errors.append(error)
        finally:
            race_registry.transitions_finished.set()

    worker = threading.Thread(target=transition_during_construction)
    worker.start()
    bridge = ShellBridge(scenario_application)
    spy = QSignalSpy(bridge.active_operation_changed)
    worker.join(timeout=2)
    QTest.qWait(20)

    assert not worker.is_alive()
    assert errors == []
    assert [spy.at(index)[0] for index in range(spy.count())] == [
        True,
        False,
    ]
    assert bridge._has_active_operation is False
    assert registry.has_active_operations() is False
