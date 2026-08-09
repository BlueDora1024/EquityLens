#!/usr/bin/env python3
"""Render deterministic product and analysis-module macOS icon assets."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "packaging" / "assets"
MODULE_RESOURCES = (
    ROOT
    / "src"
    / "stock_toolbox"
    / "analyses"
    / "rs_strength"
    / "resources"
)
DESKTOP_RESOURCES = ROOT / "src" / "stock_toolbox" / "desktop" / "resources"

RENDITIONS = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


@dataclass(frozen=True, slots=True)
class IconDefinition:
    source: Path
    master: Path
    iconset: Path
    icns: Path


ICONS = (
    IconDefinition(
        ASSETS / "stock-analysis-toolbox-icon.svg",
        ASSETS / "StockAnalysisToolbox-1024.png",
        ROOT / "build" / "StockAnalysisToolbox.iconset",
        ASSETS / "StockAnalysisToolbox.icns",
    ),
    IconDefinition(
        ASSETS / "rs-strength-icon.svg",
        ASSETS / "RSStrength-1024.png",
        ROOT / "build" / "RSStrength.iconset",
        ASSETS / "RSStrength.icns",
    ),
)


def render(renderer: QSvgRenderer, destination: Path, size: int) -> None:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(Qt.GlobalColor.transparent))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    if not image.save(str(destination), "PNG"):
        raise RuntimeError(f"failed to write {destination}")


def build_icon(definition: IconDefinition) -> None:
    renderer = QSvgRenderer(str(definition.source))
    if not renderer.isValid():
        raise RuntimeError(f"invalid SVG source: {definition.source}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(definition.iconset, ignore_errors=True)
    definition.iconset.mkdir(parents=True)
    render(renderer, definition.master, 1024)
    for name, size in RENDITIONS.items():
        render(renderer, definition.iconset / name, size)

    subprocess.run(
        [
            "iconutil",
            "-c",
            "icns",
            str(definition.iconset),
            "-o",
            str(definition.icns),
        ],
        check=True,
    )
    print(f"wrote {definition.master}")
    print(f"wrote {definition.icns}")


def main() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("macOS icon generation requires iconutil")
    for definition in ICONS:
        build_icon(definition)
    MODULE_RESOURCES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ASSETS / "RSStrength-1024.png",
        MODULE_RESOURCES / "rs-strength.png",
    )
    DESKTOP_RESOURCES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ASSETS / "StockAnalysisToolbox-1024.png",
        DESKTOP_RESOURCES / "toolbox.png",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
