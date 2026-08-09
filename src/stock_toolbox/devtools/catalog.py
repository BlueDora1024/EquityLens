import json
from dataclasses import dataclass
from importlib.resources import files

from stock_toolbox.devtools.scenario import ScenarioDocument


class ScenarioNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ScenarioCatalog:
    _documents: tuple[ScenarioDocument, ...]

    @classmethod
    def bundled(cls) -> "ScenarioCatalog":
        root = files("stock_toolbox.analyses.rs_strength").joinpath(
            "resources",
            "scenarios",
        )
        documents = tuple(
            ScenarioDocument.model_validate(json.loads(item.read_text(encoding="utf-8")))
            for item in root.iterdir()
            if item.name.endswith(".json")
        )
        return cls(tuple(sorted(documents, key=lambda item: item.id)))

    def list(self) -> tuple[ScenarioDocument, ...]:
        return self._documents

    def get(self, scenario_id: str) -> ScenarioDocument:
        for document in self._documents:
            if document.id == scenario_id:
                return document
        raise ScenarioNotFoundError(scenario_id)
