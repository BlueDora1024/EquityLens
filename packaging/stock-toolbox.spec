# -*- mode: python ; coding: utf-8 -*-

import os
import platform
from pathlib import Path
import tomllib
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
VERSION = str(PROJECT["project"]["version"])
TARGET_ARCH = os.environ.get("EQUITYLENS_TARGET_ARCH") or platform.machine()
RELEASE_TAG = os.environ.get("EQUITYLENS_RELEASE_TAG") or "local"
GIT_SHA = os.environ.get("EQUITYLENS_GIT_SHA") or "development"
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
        str(ROOT / "src/stock_toolbox/analyses/rs_strength/resources"),
        "stock_toolbox/analyses/rs_strength/resources",
    ),
    (
        str(ROOT / "src/stock_toolbox/desktop/resources"),
        "stock_toolbox/desktop/resources",
    ),
    (
        str(ROOT / "src/stock_toolbox/desktop_qml/qml"),
        "stock_toolbox/desktop_qml/qml",
    ),
]

analysis = Analysis(
    [str(ROOT / "src/stock_toolbox/gui.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=DATAS,
    hiddenimports=["longbridge.openapi", "yfinance"] + FUTU_HIDDEN,
    hookspath=[str(ROOT / "packaging/hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
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
    [],
    exclude_binaries=True,
    name="EquityLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EquityLens",
)
application = BUNDLE(
    collection,
    name="EquityLens.app",
    icon=str(ROOT / "packaging/assets/StockAnalysisToolbox.icns"),
    bundle_identifier="com.equitylens.desktop",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "EquityLens",
        "CFBundleName": "EquityLens",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": "29",
        "EquityLensReleaseTag": RELEASE_TAG,
        "EquityLensGitSHA": GIT_SHA,
        "EquityLensArchitecture": TARGET_ARCH,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    },
)
