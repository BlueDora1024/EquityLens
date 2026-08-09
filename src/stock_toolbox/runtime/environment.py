from enum import StrEnum


class RuntimeEnvironment(StrEnum):
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    INTEGRATION = "integration"
    SCENARIO = "scenario"
