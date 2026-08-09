"""Real market-data provider adapters."""

from stock_toolbox.infrastructure.providers.catalog import (
    ProviderDescriptor,
    list_provider_descriptors,
    provider_development_prompt,
)

__all__ = [
    "ProviderDescriptor",
    "list_provider_descriptors",
    "provider_development_prompt",
]
