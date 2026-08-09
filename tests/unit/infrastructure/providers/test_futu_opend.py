from __future__ import annotations

from pathlib import Path

from stock_toolbox.infrastructure.providers.futu_opend import (
    FutuOpenDService,
)


def test_probe_reports_not_installed_when_bundle_is_missing(
    tmp_path: Path,
) -> None:
    service = FutuOpenDService(bundle_path=tmp_path / "Futu_OpenD.app")

    status = service.probe()

    assert not status.installed
    assert not status.port_open
    assert status.code == "futu_opend_not_installed"


def test_probe_reports_not_running_when_bundle_exists_but_port_is_closed(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "Futu_OpenD.app"
    bundle.mkdir()
    service = FutuOpenDService(
        bundle_path=bundle,
        port_probe=lambda _host, _port: False,
    )

    status = service.probe()

    assert status.installed
    assert not status.port_open
    assert status.code == "futu_opend_not_running"


def test_probe_reports_ready_port(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "Futu_OpenD.app"
    bundle.mkdir()
    service = FutuOpenDService(
        bundle_path=bundle,
        port_probe=lambda host, port: host == "127.0.0.1" and port == 11111,
    )

    status = service.probe()

    assert status.installed
    assert status.port_open
    assert status.code == "futu_opend_port_ready"


def test_open_uses_gui_bundle_without_credentials(tmp_path: Path) -> None:
    launched: list[Path] = []
    bundle = tmp_path / "Futu_OpenD.app"
    bundle.mkdir()
    service = FutuOpenDService(
        bundle_path=bundle,
        launcher=lambda path: launched.append(path) or True,
    )

    assert service.open()
    assert launched == [bundle]


def test_open_does_not_launch_missing_bundle(tmp_path: Path) -> None:
    launched: list[Path] = []
    service = FutuOpenDService(
        bundle_path=tmp_path / "Futu_OpenD.app",
        launcher=lambda path: launched.append(path) or True,
    )

    assert not service.open()
    assert launched == []
