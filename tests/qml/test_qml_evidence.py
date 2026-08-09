from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QImage

from scripts.capture_qml_core import _write_comparisons
from scripts.qml_capture import require_qml_object


def _solid_image(path: Path, color: str) -> None:
    image = QImage(10, 6, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def test_evidence_writer_creates_side_by_side_and_overlay(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    actual = tmp_path / "actual.png"
    _solid_image(baseline, "#FFFFFF")
    _solid_image(actual, "#000000")

    _write_comparisons(baseline, actual, tmp_path, "light")

    comparison = QImage(str(tmp_path / "comparison-light.png"))
    overlay = QImage(str(tmp_path / "overlay-light.png"))
    assert (comparison.width(), comparison.height()) == (20, 6)
    assert (overlay.width(), overlay.height()) == (10, 6)


def test_required_qml_object_has_one_clear_failure_path() -> None:
    root = QObject()
    child = QObject(root)
    child.setObjectName("capturedChild")

    assert require_qml_object(root, "capturedChild", "capture target") is child
    with pytest.raises(RuntimeError, match="capture target is unavailable"):
        require_qml_object(root, "missing", "capture target")


def test_every_qml_capture_routes_save_through_checked_helper() -> None:
    repository = Path(__file__).resolve().parents[2]
    capture_scripts = (
        "capture_qml_core.py",
        "capture_qml_gallery.py",
        "capture_global_securities.py",
        "capture_rs_run_states.py",
    )

    for filename in capture_scripts:
        source = (repository / "scripts" / filename).read_text()
        assert "grabWindow().save" not in source
        assert "save_window(" in source

    helper = (repository / "scripts" / "qml_capture.py").read_text()
    assert "if not window.grabWindow().save" in helper
    assert "raise RuntimeError" in helper


def test_capture_scripts_share_named_qml_target_lookup() -> None:
    repository = Path(__file__).resolve().parents[2]
    capture_scripts = (
        "capture_qml_gallery.py",
        "capture_global_securities.py",
        "capture_rs_run_states.py",
    )

    for filename in capture_scripts:
        source = (repository / "scripts" / filename).read_text()
        assert "require_qml_object" in source
        assert "findChild(QObject" not in source


def test_gallery_captures_narrow_turning_auth_actions_in_both_themes() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "scripts" / "capture_qml_gallery.py").read_text()

    assert "turning-outcome-auth-narrow-{mode}.png" in source
    assert "window.setWidth(980)" in source
    assert "window.setHeight(680)" in source


def test_gallery_captures_turning_progress_while_the_turning_page_is_active() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "scripts" / "capture_qml_gallery.py").read_text()

    turning_run = source.index('if page_id == "turning_point.run":')
    turning_progress = source.index(
        'save_state(f"turning-running-{mode}.png")'
    )
    extreme_results = source.index(
        'if page_id == "extreme_deviation.results":'
    )

    assert turning_run < turning_progress < extreme_results


def test_gallery_rejects_an_oversized_extreme_idle_progress_panel() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "scripts" / "capture_qml_gallery.py").read_text()

    assert '"extremeProgressPanel"' in source
    assert "extreme_bridge._failure_state = FailureState()" in source
    assert "idle extreme progress panel exceeds 80 px" in source
