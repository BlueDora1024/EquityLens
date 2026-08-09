# Architecture

EquityLens is a local-first PySide6 application with Qt Quick/QML presentation. The code is
organized so desktop views, CLI scenarios, and tests call the same application services.

## Layers

1. **Presentation** — QML views and thin Qt bridges expose observable state and commands.
2. **Application** — use cases coordinate imports, watchlists, runs, reports, and settings.
3. **Analysis modules** — RS strength, turning point, and extreme deviation own their
   algorithms and result contracts.
4. **Core** — shared market-data normalization, reliability policies, resource budgets,
   and run lifecycle behavior.
5. **Infrastructure** — SQLite repositories, Longbridge/Futu/Yahoo adapters, AI clients,
   diagnostics, and filesystem integration.

Provider-specific responses are normalized before they reach an analysis. A fallback run
restarts with one consistent source; it does not mix providers inside a single result.

The internal package name remains `stock_toolbox` to avoid a risky persistence and import
migration. Public product identity is isolated at the command, GUI, bundle, docs, and
packaging boundaries.
