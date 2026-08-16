from stock_toolbox.desktop_qml.progress_state import monotonic_stage_progress


def test_progress_never_moves_backwards_when_updates_arrive_out_of_order() -> None:
    current = monotonic_stage_progress(
        0.58,
        stage_index=2,
        stage_count=6,
        completed=1,
        total=10,
    )

    assert current == 0.58


def test_progress_reserves_completion_for_terminal_state() -> None:
    current = monotonic_stage_progress(
        0.0,
        stage_index=5,
        stage_count=6,
        completed=10,
        total=10,
    )

    assert current < 1.0
    assert current >= 0.99
