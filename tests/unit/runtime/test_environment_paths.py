from pathlib import Path

import pytest

from stock_toolbox.runtime.environment import RuntimeEnvironment
from stock_toolbox.runtime.paths import RuntimePaths


@pytest.mark.parametrize(
    ("environment", "database_name"),
    [
        (RuntimeEnvironment.PRODUCTION, "RSRadar.sqlite3"),
        (RuntimeEnvironment.DEVELOPMENT, "RSRadar.dev.sqlite3"),
        (RuntimeEnvironment.INTEGRATION, "RSRadar.integration.sqlite3"),
    ],
)
def test_named_environments_are_physically_isolated(
    tmp_path: Path,
    environment: RuntimeEnvironment,
    database_name: str,
) -> None:
    paths = RuntimePaths.resolve(environment, home=tmp_path)
    assert paths.database.name == database_name
    assert paths.data_root != paths.log_root


def test_real_modes_share_one_global_ai_configuration_database(
    tmp_path: Path,
) -> None:
    production = RuntimePaths.resolve(RuntimeEnvironment.PRODUCTION, home=tmp_path)
    development = RuntimePaths.resolve(RuntimeEnvironment.DEVELOPMENT, home=tmp_path)

    assert production.global_ai_database == development.global_ai_database
    assert production.global_ai_database == (
        tmp_path
        / "Library"
        / "Application Support"
        / "EquityLens"
        / "RSRadar.config.sqlite3"
    )
    assert not hasattr(production, "keychain_service")


def test_equitylens_never_reuses_legacy_product_data_directories(
    tmp_path: Path,
) -> None:
    production = RuntimePaths.resolve(RuntimeEnvironment.PRODUCTION, home=tmp_path)

    assert "EquityLens" in production.data_root.parts
    assert "EquityLens" in production.log_root.parts
    assert "Stock Analysis Toolbox" not in production.data_root.parts
    assert "RS Radar" not in production.data_root.parts


def test_integration_global_ai_configuration_is_not_shared_with_real_modes(
    tmp_path: Path,
) -> None:
    production = RuntimePaths.resolve(RuntimeEnvironment.PRODUCTION, home=tmp_path)
    integration = RuntimePaths.resolve(RuntimeEnvironment.INTEGRATION, home=tmp_path)

    assert integration.global_ai_database != production.global_ai_database
    assert integration.global_ai_database.parent == integration.data_root


def test_scenario_environment_requires_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scenario_run_id"):
        RuntimePaths.resolve(RuntimeEnvironment.SCENARIO, home=tmp_path)


def test_scenario_paths_are_unique_and_never_production(tmp_path: Path) -> None:
    first = RuntimePaths.resolve(
        RuntimeEnvironment.SCENARIO, home=tmp_path, scenario_run_id="case-a"
    )
    second = RuntimePaths.resolve(
        RuntimeEnvironment.SCENARIO, home=tmp_path, scenario_run_id="case-b"
    )
    assert first.database != second.database
    assert "Scenarios" in first.database.parts
    assert first.global_ai_database != second.global_ai_database
    assert first.global_ai_database.parent == first.data_root


@pytest.mark.parametrize("run_id", ("", "../escape", "nested/path", "white space"))
def test_scenario_run_id_rejects_unsafe_paths(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="scenario_run_id"):
        RuntimePaths.resolve(
            RuntimeEnvironment.SCENARIO,
            home=tmp_path,
            scenario_run_id=run_id,
        )
