# Data, permissions, and privacy

EquityLens requests read-only market data. It does not place trades or require account,
position, order, or asset permissions for its analysis workflows.

## Local state

The app creates local SQLite data and rotating diagnostic logs at runtime. The historical
application-support directory is intentionally retained across the EquityLens rename so an
existing installation does not lose its library or settings.

## External services

- Longbridge OAuth tokens are persisted and refreshed by the official SDK.
- Futu access goes through the user's local OpenD process.
- Yahoo is a slower public-data fallback and may require a working network proxy.
- AI is optional and only invoked when the user requests classification or interpretation.

Secrets are never written to diagnostic logs. The public mirror rejects runtime databases,
logs, private keys, private home paths, and secret-like tokens.
