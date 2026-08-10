from __future__ import annotations

from stock_toolbox.desktop_qml.update_bridge import UpdateBridge
from stock_toolbox.infrastructure.updates.models import BuildIdentity, ReleaseAsset, ReleaseInfo


def _release(version: str = "1.1.0") -> ReleaseInfo:
    archive = ReleaseAsset(f"EquityLens-v{version}-x86_64.zip", "https://example.com/app.zip", 100)
    checksum = ReleaseAsset(f"{archive.name}.sha256", "https://example.com/app.zip.sha256", 64)
    return ReleaseInfo(
        f"v{version}", version, f"EquityLens {version}",
        ("自动更新", "修复稳定性"), "2026-08-10T08:00:00Z",
        "https://github.com/BlueDora1024/EquityLens/releases/tag/v1.1.0",
        archive, checksum,
    )


class _Service:
    def __init__(self, release: ReleaseInfo | Exception) -> None:
        self.release = release

    def latest_release(self, _architecture: str) -> ReleaseInfo:
        if isinstance(self.release, Exception):
            raise self.release
        return self.release


def test_startup_check_is_non_blocking_and_opens_prompt_for_new_release(qtbot) -> None:
    bridge = UpdateBridge(
        identity=BuildIdentity("1.0.1", "v1.0.1", "a" * 40, "x86_64"),
        service=_Service(_release()),
    )
    with qtbot.waitSignal(bridge.check_finished, timeout=2_000):
        assert bridge.check_on_startup() is True
    assert bridge.update_available is True
    assert bridge.prompt_visible is True
    assert bridge.latest_tag == "v1.1.0"
    assert bridge.release_notes == ["自动更新", "修复稳定性"]


def test_startup_network_failure_is_silent(qtbot) -> None:
    bridge = UpdateBridge(
        identity=BuildIdentity("1.0.1", "v1.0.1", "a" * 40, "arm64"),
        service=_Service(OSError("offline secret detail")),
    )
    with qtbot.waitSignal(bridge.check_finished, timeout=2_000):
        bridge.check_on_startup()
    assert bridge.prompt_visible is False
    assert bridge.status == "idle"
    assert bridge.message == ""


def test_manual_network_failure_has_sanitized_feedback(qtbot) -> None:
    bridge = UpdateBridge(
        identity=BuildIdentity("1.0.1", "v1.0.1", "a" * 40, "arm64"),
        service=_Service(OSError("offline secret detail")),
    )
    with qtbot.waitSignal(bridge.check_finished, timeout=2_000):
        bridge.check_now()
    assert bridge.status == "error"
    assert bridge.message == "无法连接 GitHub，请检查网络或代理后重试。"
    assert "secret" not in bridge.message


def test_current_build_identity_is_exposed() -> None:
    bridge = UpdateBridge(
        identity=BuildIdentity("1.0.1", "v1.0.1", "0123456789abcdef", "arm64"),
        service=_Service(_release("1.0.1")),
    )
    assert bridge.current_version == "1.0.1"
    assert bridge.current_tag == "v1.0.1"
    assert bridge.current_sha == "0123456789ab"
    assert bridge.architecture == "Apple Silicon"
