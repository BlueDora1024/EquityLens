from __future__ import annotations

from stock_toolbox.desktop_qml.theme_bridge import ThemeBridge


def test_theme_bridge_can_freeze_light_and_dark_for_evidence(qapp) -> None:
    bridge = ThemeBridge(qapp.styleHints())

    bridge.set_evidence_mode("dark")
    assert bridge.dark is True

    bridge.set_evidence_mode("light")
    assert bridge.dark is False


def test_theme_bridge_persists_explicit_user_mode(qapp) -> None:
    saved: list[str] = []
    bridge = ThemeBridge(
        qapp.styleHints(),
        initial_mode="system",
        save_mode=saved.append,
    )

    assert bridge.mode == "system"
    assert bridge.set_mode("dark") is True
    assert bridge.mode == "dark"
    assert bridge.dark is True
    assert saved == ["dark"]

    assert bridge.set_mode("invalid") is False
    assert bridge.mode == "dark"
    assert saved == ["dark"]


def test_evidence_mode_does_not_overwrite_saved_user_choice(qapp) -> None:
    saved: list[str] = []
    bridge = ThemeBridge(
        qapp.styleHints(),
        initial_mode="dark",
        save_mode=saved.append,
    )

    bridge.set_evidence_mode("light")

    assert bridge.dark is False
    assert bridge.mode == "dark"
    assert saved == []
