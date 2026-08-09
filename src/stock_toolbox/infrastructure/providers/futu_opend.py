"""Local Futu OpenD GUI discovery and launch boundary."""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

FUTU_OPEND_BUNDLE = Path("/Applications/Futu_OpenD.app")
FUTU_OPEND_HOST = "127.0.0.1"
FUTU_OPEND_PORT = 11111
FUTU_OPEND_GUIDE_URL = (
    "https://openapi.futunn.com/futu-api-doc/quick/opend-base.html"
)


@dataclass(frozen=True, slots=True)
class FutuOpenDStatus:
    installed: bool
    port_open: bool
    code: str


def _socket_probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _open_bundle(bundle: Path) -> bool:
    completed = subprocess.run(
        ("open", "-a", str(bundle)),
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


class FutuOpenDService:
    def __init__(
        self,
        *,
        bundle_path: Path = FUTU_OPEND_BUNDLE,
        host: str = FUTU_OPEND_HOST,
        port: int = FUTU_OPEND_PORT,
        port_probe: Callable[[str, int], bool] = _socket_probe,
        launcher: Callable[[Path], bool] = _open_bundle,
    ) -> None:
        self.bundle_path = bundle_path.expanduser().resolve()
        self.host = host
        self.port = port
        self._port_probe = port_probe
        self._launcher = launcher

    def probe(self) -> FutuOpenDStatus:
        if not self.bundle_path.is_dir():
            return FutuOpenDStatus(
                False,
                False,
                "futu_opend_not_installed",
            )
        if not self._port_probe(self.host, self.port):
            return FutuOpenDStatus(
                True,
                False,
                "futu_opend_not_running",
            )
        return FutuOpenDStatus(
            True,
            True,
            "futu_opend_port_ready",
        )

    def open(self) -> bool:
        return (
            self.bundle_path.is_dir()
            and self._launcher(self.bundle_path)
        )
