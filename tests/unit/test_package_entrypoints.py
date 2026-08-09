import subprocess
import sys
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import stock_toolbox

pytestmark = pytest.mark.fast


def test_primary_entrypoints_use_new_product_package() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = config["project"]["scripts"]

    assert config["project"]["name"] == "equitylens"
    assert scripts["equitylens"] == "stock_toolbox.cli:main"
    assert scripts["stock-toolbox"] == "stock_toolbox.cli:main"
    assert scripts["stock-toolbox-gui"] == "stock_toolbox.gui:main"
    assert scripts["rs-radar-cli"] == "rs_radar.cli:main"
    assert stock_toolbox.__version__ == config["project"]["version"]


def test_package_has_version_and_equitylens_entrypoint() -> None:
    assert stock_toolbox.__version__
    scripts = {item.name: item.value for item in entry_points(group="console_scripts")}
    assert scripts["equitylens"] == "stock_toolbox.cli:main"
    assert scripts["stock-toolbox"] == "stock_toolbox.cli:main"
    assert scripts["stock-toolbox-gui"] == "stock_toolbox.gui:main"
    assert scripts["rs-radar-cli"] == "rs_radar.cli:main"


def test_release_tools_read_the_version_from_pyproject() -> None:
    spec = Path("packaging/stock-toolbox.spec").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_bundle.py").read_text(encoding="utf-8")
    builder = Path("scripts/build_app.sh").read_text(encoding="utf-8")

    assert 'PROJECT["project"]["version"]' in spec
    assert 'PROJECT["project"]["version"]' in verifier
    assert "tomllib.load" in builder
    assert '"$ROOT/scripts/write_sha256.sh" "$ARCHIVE"' in builder


def test_successful_build_prunes_only_reproducible_release_intermediates() -> None:
    builder = Path("scripts/build_app.sh").read_text(encoding="utf-8")

    assert "prune_build_artifacts()" in builder
    assert '"$ROOT/dist/EquityLens"' in builder
    assert "'EquityLens-v*-*.zip'" in builder
    assert 'EquityLens-v${VERSION}-${TARGET_ARCH}.zip' in builder
    assert 'TARGET_ARCH=${EQUITYLENS_TARGET_ARCH:-$(uname -m)}' in builder


def test_bundle_reuses_cli_payload_and_excludes_futu_development_modules() -> None:
    builder = Path("scripts/build_app.sh").read_text(encoding="utf-8")
    gui_spec = Path("packaging/stock-toolbox.spec").read_text(encoding="utf-8")
    cli_spec = Path("packaging/stock-toolbox-cli.spec").read_text(
        encoding="utf-8"
    )

    assert 'cp "$ROOT/dist/equitylens" "$APP/Contents/MacOS/equitylens-cli"' in builder
    assert 'ln -s "equitylens-cli" "$APP/Contents/MacOS/stock-toolbox"' in builder
    assert 'ln -s "equitylens-cli" "$APP/Contents/MacOS/rs-radar-cli"' in builder
    assert builder.count('cp "$ROOT/dist/equitylens"') == 1
    for spec in (gui_spec, cli_spec):
        assert "futu.examples" in spec
        assert "futu.tools" in spec


def test_release_checksum_is_portable_after_copy(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    archive = release / "artifact.zip"
    archive.write_bytes(b"portable release")

    generated = subprocess.run(
        ["scripts/write_sha256.sh", str(archive)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert generated.returncode == 0, generated.stderr
    checksum = release / "artifact.zip.sha256"
    assert str(release) not in checksum.read_text(encoding="utf-8")
    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / archive.name).write_bytes(archive.read_bytes())
    (portable / checksum.name).write_bytes(checksum.read_bytes())
    verified = subprocess.run(
        ["shasum", "-a", "256", "-c", checksum.name],
        cwd=portable,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr


def test_packaged_acceptance_has_one_exit_cleanup_trap() -> None:
    source = Path("scripts/run_packaged_acceptance.sh").read_text(
        encoding="utf-8"
    )

    assert "cleanup()" in source
    assert "trap cleanup EXIT" in source
    assert "trap 'exit 129' HUP" in source
    assert "trap 'exit 130' INT" in source
    assert "trap 'exit 143' TERM" in source
    assert 'kill -TERM "$GUI_PID"' in source
    assert 'wait "$GUI_PID"' in source
    assert 'exec "$GUI"' in source
    assert '"$CLI_HOME"' in source
    assert '"$GUI_HOME"' in source
    assert 'stock-toolbox-turning-point.json' in source
    assert 'stock-toolbox-legacy-cli.json' in source
    assert "PACKAGED_ACCEPTANCE_FORCE_FAILURE_AFTER_GUI_START" in source


def test_cli_source_entry_executes_main_for_pyinstaller(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "src/stock_toolbox/cli.py",
            "--env",
            "dev",
            "--home",
            str(tmp_path),
            "scenario",
            "list",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert '"schema_version": "cli-output-v1"' in result.stdout


def test_gui_source_has_direct_pyinstaller_entry_guard() -> None:
    source = Path("src/stock_toolbox/gui.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source
    assert "build_pilot_engine" in source
    assert "--legacy-widgets" not in source
