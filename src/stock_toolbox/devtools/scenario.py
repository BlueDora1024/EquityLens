from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioFault(BaseModel):
    """One deterministic fault consumed by the shared scenario adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: Literal[
        "daily",
        "database_save",
        "storage",
        "cancel",
        "ai_report",
    ]
    events: tuple[str, ...] = ()
    symbol: str = ""
    start_index: int | None = Field(default=None, ge=0)
    stage: str = ""


class ScenarioStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal[
        "bootstrap",
        "import_securities",
        "create_watchlist",
        "add_all_classified",
        "run",
        "run_rs_benchmark",
        "export_latest",
        "generate_rs_report_twice",
    ]
    value: str | None = None
    benchmark: Literal["SPY.US", "QQQ.US"] | None = None
    end_date: str | None = None
    ranges: tuple[Literal["3M", "6M", "1Y"], ...] = ()
    formats: tuple[Literal["json", "markdown", "csv"], ...] = ()

    @model_validator(mode="after")
    def validate_arguments(self) -> "ScenarioStep":
        if self.action in {"import_securities", "create_watchlist"} and not self.value:
            raise ValueError("scenario step value is required")
        if self.action == "run" and (
            self.benchmark is None or self.end_date is None or not self.ranges
        ):
            raise ValueError("run scenario arguments are required")
        if self.action == "export_latest" and not self.formats:
            raise ValueError("export formats are required")
        return self


class ScenarioDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scenario-v1"]
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)
    provider_fixture: str
    ai_fixture: str
    steps: tuple[ScenarioStep, ...]
    expected: dict[str, object]
    max_provider_calls: int | None = Field(default=None, ge=0)
    fault_plan: tuple[ScenarioFault, ...] = ()
