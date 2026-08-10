# EquityLens Self-Update Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Add a safe, non-blocking, architecture-aware GitHub Release updater with embedded build identity and mandatory release notes.

**Architecture:** A pure update domain module parses GitHub releases and validates artifacts. A Qt bridge runs network and filesystem work off the UI thread and exposes stable state to QML. A detached system shell helper replaces the app only after the GUI exits. Build metadata lives in Info.plist.

**Tech Stack:** Python 3.12, PySide6/QML, httpx, PyInstaller, macOS ditto/codesign/open, pytest, GitHub Actions.

---

### Task 1: Update domain and build identity

**Files:**
- Create: `src/stock_toolbox/infrastructure/updates/models.py`
- Create: `src/stock_toolbox/infrastructure/updates/service.py`
- Test: `tests/unit/infrastructure/updates/test_service.py`

Write failing tests for semantic version comparison, architecture asset selection, release-note summarization, SHA parsing and bundle identity. Implement the smallest pure functions and service needed to pass.

### Task 2: Safe installer

**Files:**
- Create: `src/stock_toolbox/infrastructure/updates/installer.py`
- Test: `tests/unit/infrastructure/updates/test_installer.py`

Test safe ZIP extraction, checksum rejection, replacement-script rollback commands and data-path isolation. Implement staged extraction and detached replacement.

### Task 3: Qt bridge and UI

**Files:**
- Create: `src/stock_toolbox/desktop_qml/update_bridge.py`
- Create: `src/stock_toolbox/desktop_qml/qml/UpdateOverlay.qml`
- Modify: `src/stock_toolbox/desktop_qml/app.py`
- Modify: `src/stock_toolbox/desktop_qml/qml/PilotWindow.qml`
- Modify: `src/stock_toolbox/desktop_qml/qml/SettingsOverlay.qml`
- Test: `tests/qml/test_update_bridge.py`
- Test: `tests/qml/test_qml_contract.py`

Test bridge state transitions and QML contracts first. Add the Advanced card and non-blocking startup prompt with release notes, progress, retry and later actions.

### Task 4: Build and release metadata

**Files:**
- Modify: `packaging/stock-toolbox.spec`
- Modify: `scripts/build_app.sh`
- Modify: `scripts/verify_bundle.py`
- Modify: `.github/workflows/release.yml`
- Create: `docs/releases/v1.1.0.md`
- Test: `tests/unit/test_packaging_assets.py`
- Test: `tests/unit/test_public_release_contract.py`

Inject Tag and SHA into Info.plist, require tag-specific release notes, publish those notes, and verify all metadata during bundle checks.

### Task 5: Verification and release

Run update-focused tests, QML lint/contracts, full test suite, Intel packaged acceptance and privacy scan. Sync the public repository, commit one feature release, tag `v1.1.0`, push, wait for both architecture assets, install the verified Intel build locally, and confirm the app reports the release Tag and SHA.

