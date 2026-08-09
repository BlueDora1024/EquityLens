import re
from dataclasses import dataclass
from pathlib import Path

from stock_toolbox.runtime.environment import RuntimeEnvironment

_SAFE_SCENARIO_ID = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class RuntimePaths:
    environment: RuntimeEnvironment
    data_root: Path
    log_root: Path
    database: Path
    global_ai_database: Path
    exports_root: Path

    @classmethod
    def resolve(
        cls,
        environment: RuntimeEnvironment,
        *,
        home: Path,
        scenario_run_id: str | None = None,
    ) -> "RuntimePaths":
        home = home.expanduser().resolve()
        data_base = home / "Library" / "Application Support" / "EquityLens"
        log_base = home / "Library" / "Logs" / "EquityLens"

        if environment is RuntimeEnvironment.PRODUCTION:
            data_root = data_base
            log_root = log_base
            database_name = "RSRadar.sqlite3"
        elif environment is RuntimeEnvironment.DEVELOPMENT:
            data_root = data_base / "Development"
            log_root = log_base / "Development"
            database_name = "RSRadar.dev.sqlite3"
        elif environment is RuntimeEnvironment.INTEGRATION:
            data_root = data_base / "Integration"
            log_root = log_base / "Integration"
            database_name = "RSRadar.integration.sqlite3"
        else:
            if scenario_run_id is None or _SAFE_SCENARIO_ID.fullmatch(scenario_run_id) is None:
                raise ValueError("scenario_run_id must be a safe non-empty identifier")
            data_root = data_base / "Scenarios" / scenario_run_id
            log_root = log_base / "Scenarios" / scenario_run_id
            database_name = "RSRadar.scenario.sqlite3"

        global_ai_database = (
            data_base / "RSRadar.config.sqlite3"
            if environment
            in {
                RuntimeEnvironment.PRODUCTION,
                RuntimeEnvironment.DEVELOPMENT,
            }
            else data_root / "RSRadar.config.sqlite3"
        )

        return cls(
            environment=environment,
            data_root=data_root,
            log_root=log_root,
            database=data_root / database_name,
            global_ai_database=global_ai_database,
            exports_root=data_root / "Exports",
        )
