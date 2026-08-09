from __future__ import annotations

from datetime import UTC, datetime

from stock_toolbox.core.operations.admission import ApplicationAdmission
from stock_toolbox.core.operations.registry import (
    OperationRegistry,
    OperationStatus,
    ReserveResult,
)

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def admission() -> ApplicationAdmission:
    return ApplicationAdmission(OperationRegistry(clock=lambda: NOW))


def test_read_identity_is_deduplicated_and_released_in_finally_style() -> None:
    gate = admission()
    identity = ("securities", "search=NVDA", "cursor=first")

    assert gate.try_begin_read(identity)
    assert not gate.try_begin_read(identity)
    gate.finish_read(identity)
    assert gate.try_begin_read(identity)
    gate.finish_read(identity)


def test_short_mutations_are_tracked_but_not_cancelable_operations() -> None:
    gate = admission()

    assert gate.try_begin_short_mutation("mutation-1")
    assert not gate.try_begin_short_mutation("mutation-1")
    assert gate.registry.status("mutation-1") is None
    gate.finish_short_mutation("mutation-1")


def test_closing_atomically_stops_all_new_admission_and_reports_snapshot() -> None:
    gate = admission()
    gate.reserve_operation("op-1", "key", "run")
    gate.try_begin_read(("history", "all"))
    gate.try_begin_short_mutation("mutation-1")

    snapshot = gate.begin_closing()

    assert snapshot.generation == 1
    assert tuple(item.operation_id for item in snapshot.operations) == ("op-1",)
    assert snapshot.reads == (("history", "all"),)
    assert snapshot.short_mutations == ("mutation-1",)
    assert (
        gate.reserve_operation("op-2", "other", "run").result
        is ReserveResult.ADMISSION_CLOSED
    )
    assert not gate.try_begin_read(("securities", "all"))
    assert not gate.try_begin_short_mutation("mutation-2")


def test_quiescence_requires_every_inflight_category_to_finish() -> None:
    gate = admission()
    gate.reserve_operation("op-1", "key", "run")
    context = gate.registry.begin_reserved("op-1")
    assert context is not None
    gate.try_begin_read(("history", "all"))
    gate.try_begin_short_mutation("mutation-1")
    closing = gate.begin_closing()

    assert not gate.confirm_quiescent(closing.generation).quiescent
    assert context.operation_control.try_enter_committing()
    gate.registry.try_complete("op-1", OperationStatus.SUCCEEDED, {})
    gate.finish_read(("history", "all"))
    gate.finish_short_mutation("mutation-1")

    final = gate.confirm_quiescent(closing.generation)
    assert final.quiescent
    assert final.operations == ()
    assert final.reads == ()
    assert final.short_mutations == ()


def test_resume_requires_current_closing_generation() -> None:
    gate = admission()
    closing = gate.begin_closing()

    assert not gate.resume(closing.generation + 1)
    assert gate.resume(closing.generation)
    assert gate.try_begin_read(("securities", "all"))
