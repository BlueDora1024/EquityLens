from pathlib import Path
from typing import Any, Self

import pytest
from pydantic import ValidationError

import stock_toolbox.devtools.runner as runner_module
from stock_toolbox.devtools.runner import ScenarioRunner
from stock_toolbox.devtools.scenario import ScenarioDocument
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_scenario_document_has_stable_version_and_id() -> None:
    document = ScenarioDocument.model_validate(
        {
            "schema_version": "scenario-v1",
            "id": "startup-empty",
            "title": "Empty startup",
            "provider_fixture": "empty-v1",
            "ai_fixture": "disabled-v1",
            "steps": [{"action": "bootstrap"}],
            "expected": {"terminal": "succeeded"},
            "max_provider_calls": 4,
        }
    )
    assert document.id == "startup-empty"
    assert document.steps[0].action == "bootstrap"
    assert document.max_provider_calls == 4


def test_scenario_rejects_negative_provider_call_budget() -> None:
    with pytest.raises(ValidationError):
        ScenarioDocument.model_validate(
            {
                "schema_version": "scenario-v1",
                "id": "bad-call-budget",
                "title": "Bad call budget",
                "provider_fixture": "empty-v1",
                "ai_fixture": "disabled-v1",
                "steps": [{"action": "bootstrap"}],
                "expected": {},
                "max_provider_calls": -1,
            }
        )


def test_runner_rejects_provider_request_storm() -> None:
    document = ScenarioDocument.model_validate(
        {
            "schema_version": "scenario-v1",
            "id": "request-storm",
            "title": "Request storm",
            "provider_fixture": "virtual-market-v1",
            "ai_fixture": "disabled-v1",
            "steps": [{"action": "bootstrap"}],
            "expected": {},
            "max_provider_calls": 3,
        }
    )

    with pytest.raises(ValueError, match="provider call budget"):
        ScenarioRunner().verify_provider_call_budget(document, actual_calls=4)

    ScenarioRunner().verify_provider_call_budget(document, actual_calls=3)


def test_scenario_rejects_unknown_schema() -> None:
    with pytest.raises(ValidationError):
        ScenarioDocument.model_validate(
            {
                "schema_version": "scenario-v2",
                "id": "bad",
                "title": "Bad",
                "provider_fixture": "empty-v1",
                "ai_fixture": "disabled-v1",
                "steps": [],
                "expected": {},
            }
        )


def test_scenario_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ScenarioDocument.model_validate(
            {
                "schema_version": "scenario-v1",
                "id": "bad-extra",
                "title": "Bad extra",
                "provider_fixture": "empty-v1",
                "ai_fixture": "disabled-v1",
                "steps": [],
                "expected": {},
                "secret": "must-not-be-accepted",
            }
        )


def test_runner_refuses_production() -> None:
    runner = ScenarioRunner()
    with pytest.raises(PermissionError, match="production"):
        runner.validate_environment(RuntimeEnvironment.PRODUCTION)


def test_runner_closes_its_persisted_row_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class TrackingConnection:
        closed = False

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str) -> "TrackingConnection":
            return self

        def fetchone(self) -> tuple[int]:
            return (0,)

        def close(self) -> None:
            self.closed = True

    connection = TrackingConnection()

    class Factory:
        def open_reader(self) -> TrackingConnection:
            return connection

    class Application:
        factory = Factory()

        def list_history(self) -> tuple[object, ...]:
            return ()

    def build_application(*_args: object, **_kwargs: Any) -> Application:
        return Application()

    monkeypatch.setattr(runner_module, "build_application", build_application)
    scenario = ScenarioDocument.model_validate(
        {
            "schema_version": "scenario-v1",
            "id": "reader-cleanup",
            "title": "Reader cleanup",
            "provider_fixture": "virtual-market-v1",
            "ai_fixture": "disabled-v1",
            "steps": [],
            "expected": {"terminal": "succeeded"},
        }
    )

    ScenarioRunner().run(scenario, home=tmp_path)

    assert connection.closed is True


@pytest.mark.parametrize(
    "environment",
    (
        RuntimeEnvironment.DEVELOPMENT,
        RuntimeEnvironment.INTEGRATION,
        RuntimeEnvironment.SCENARIO,
    ),
)
def test_runner_accepts_only_isolated_environments(environment: RuntimeEnvironment) -> None:
    ScenarioRunner().validate_environment(environment)
