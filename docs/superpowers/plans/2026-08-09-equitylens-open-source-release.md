# EquityLens Open Source Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the shipped product to EquityLens and create a sanitized, reproducible public repository with dual-architecture macOS releases.

**Architecture:** The private working repository remains the source of truth. A deterministic one-way sync script materializes an allowlisted public tree, runs privacy checks, and leaves Git history and pushing under the public repository's control.

**Tech Stack:** Python 3.12, PySide6/QML, PyInstaller, pytest, Ruff, mypy, shell scripts, GitHub Actions.

---

### Task 1: Pin the EquityLens brand contract

**Files:**
- Modify: `src/stock_toolbox/gui.py`
- Modify: `src/stock_toolbox/desktop_qml/qml/PilotWindow.qml`
- Modify: `packaging/stock-toolbox.spec`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_package_entrypoints.py`
- Test: `tests/unit/test_verify_bundle.py`

- [ ] Add failing assertions for `EquityLens`, `EquityLens.app`, `com.equitylens.desktop`, and the `equitylens` CLI.
- [ ] Run the focused tests and confirm they fail on the old brand.
- [ ] Replace user-visible product strings and keep the old CLI aliases.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Make packaging architecture-aware

**Files:**
- Modify: `packaging/stock-toolbox.spec`
- Modify: `packaging/stock-toolbox-cli.spec`
- Modify: `scripts/build_app.sh`
- Modify: `scripts/install_app.sh`
- Modify: `scripts/verify_bundle.py`
- Modify: `scripts/run_packaged_acceptance.sh`
- Test: `tests/unit/test_packaging_assets.py`
- Test: `tests/unit/test_local_app_install.py`
- Test: `tests/unit/test_verify_bundle.py`

- [ ] Add tests that require architecture-derived target selection and architecture-specific archive names.
- [ ] Parameterize PyInstaller target architecture from `EQUITYLENS_TARGET_ARCH`, defaulting to the host architecture.
- [ ] Rename the bundle, executable, archive, manifest, install staging path and verification contract.
- [ ] Preserve the existing application-data directory and remove only the verified legacy App bundle.
- [ ] Run the packaging unit tests.

### Task 3: Curate public documentation

**Files:**
- Modify: `README.md`
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `documentation/architecture.md`
- Create: `documentation/flows.md`
- Create: `documentation/permissions.md`
- Create: `documentation/variables.md`
- Create: `documentation/tests.md`
- Create: `documentation/automation.md`

- [ ] Rewrite README as the public product landing page with screenshots, install/build steps, privacy boundaries and provider capabilities.
- [ ] Add MIT licensing and professional contributor/security/community policies.
- [ ] Document architecture, trust-boundary flows, local permissions, secrets/configuration, AI automation and real test coverage.
- [ ] Scan for placeholders and private absolute paths.

### Task 4: Implement deterministic public sync

**Files:**
- Create: `scripts/public_manifest.txt`
- Create: `scripts/sync_public_repo.py`
- Create: `scripts/check_public_repo.py`
- Test: `tests/unit/test_public_repo_sync.py`

- [ ] Write failing tests for allowlisted copy, stale-file removal, secret rejection and preservation of public `.git`.
- [ ] Implement manifest-based copy from the working tree into a requested destination.
- [ ] Implement forbidden-file, secret-pattern and absolute-private-path scanning.
- [ ] Run sync tests and a dry run against a temporary directory.

### Task 5: Add GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/pull_request_template.md`

- [ ] Add offline CI on `macos-15` arm64.
- [ ] Add tag-triggered release jobs on `macos-15` arm64 and `macos-15-intel` x86_64.
- [ ] Upload architecture-specific zip and SHA-256 files, then publish one GitHub Release.
- [ ] Validate workflow YAML and required runner/asset contracts locally.

### Task 6: Materialize and initialize the public repository

**Files:**
- Create the local public-mirror tree at the maintainer-selected destination.

- [ ] Run the public sync into the target directory.
- [ ] Initialize `main`, set local Git identity only if already configured, and create the initial public commit.
- [ ] Confirm no remote is invented when no GitHub URL is available.
- [ ] Run the public privacy checker against the committed tree.

### Task 7: Full verification and local installation

**Files:**
- Modify: `docs/development/CHANGELOG.md`
- Modify: `docs/development/VERSION_CHRONICLE.md`

- [ ] Run focused brand, sync and packaging tests.
- [ ] Run the full offline test/lint/type/QML gate.
- [ ] Build the Intel App on the local Intel Mac.
- [ ] Verify Bundle ID, architecture, ad-hoc signature and packaged CLI workflow.
- [ ] Install `/Applications/EquityLens.app` and verify it reuses the existing formal data path without bundling user data.
- [ ] Run public repository checks and inspect `git status` in both repositories.
