# -*- mode: python ; coding: utf-8 -*-

import os
import platform
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
TARGET_ARCH = os.environ.get("EQUITYLENS_TARGET_ARCH") or platform.machine()
if TARGET_ARCH not in {"arm64", "x86_64"}:
    raise ValueError(f"unsupported target architecture: {TARGET_ARCH}")
FUTU_HIDDEN = [
    module
    for module in collect_submodules("futu")
    if not module.startswith(("futu.examples", "futu.tools"))
]
FUTU_DATA = collect_data_files("futu", includes=["VERSION.txt"])
DATAS = FUTU_DATA + [
    (
        str(ROOT / "src/stock_toolbox/infrastructure/persistence/sql"),
        "stock_toolbox/infrastructure/persistence/sql",
    ),
    (
        str(ROOT / "src/stock_toolbox/analyses/rs_strength/resources/scenarios"),
        "stock_toolbox/analyses/rs_strength/resources/scenarios",
    ),
]

analysis = Analysis(
    [str(ROOT / "src/stock_toolbox/cli.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=DATAS,
    hiddenimports=["longbridge.openapi", "yfinance"] + FUTU_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "pytest",
        "mypy",
        "ruff",
        "tests",
        "matplotlib",
        "PIL",
        "futu.examples",
        "futu.tools",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="equitylens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)
