# EquityLens

EquityLens is a local-first macOS desktop workbench for reviewing US equities. It keeps
your security library, tags, watchlists, provider settings, analysis runs, and reports on
your Mac while presenting three focused analysis tools in one native PySide6/Qt Quick app.

> EquityLens is research software, not investment advice. Its signals describe historical
> market data and do not predict returns.

## What it does

- **RS Strength** compares a watchlist with SPY or QQQ over several date ranges, then
  aggregates results by the business tag selected for that watchlist.
- **Turning Point** finds left-side CD divergence signals and optional right-side moving
  average confirmation across multiple K-line periods.
- **Extreme Deviation** reviews one security at a time and visualizes corrected buy/sell
  pressure across selected periods.
- **Shared workspace** maintains one global security library, reusable business tags, and
  multiple watchlists without duplicating fundamentals.
- **Pluggable data providers** support Longbridge, Futu OpenD, and a Yahoo public-data
  fallback. OpenAI-compatible endpoints are optional and only used for requested reports.

## Privacy

The source repository contains no user database, provider token, API key, diagnostic log,
or analysis history. Runtime state is created on first launch and stays in the current
macOS user account. Diagnostic exports redact secrets before they leave the app.

## Install a release

Download the archive matching your Mac from GitHub Releases:

- `EquityLens-vX.Y.Z-arm64.zip` for Apple silicon
- `EquityLens-vX.Y.Z-x86_64.zip` for Intel Macs

The app is ad-hoc signed rather than notarized. macOS may require you to confirm that you
want to open it. Provider accounts and credentials are not bundled.

## Develop locally

Requirements: macOS, Python 3.12, and Xcode command-line tools.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/equitylens-gui
```

Useful commands:

```bash
./scripts/test.sh fast
./scripts/test.sh batch rs
./scripts/test.sh batch turning-point
./scripts/test.sh batch extreme-deviation
./scripts/test.sh full
./scripts/build_app.sh
```

The CLI uses the same application services as the desktop interface:

```bash
.venv/bin/equitylens analysis list
.venv/bin/equitylens --help
```

## Architecture and maintenance

- [Architecture](documentation/architecture.md)
- [Product flows](documentation/product-flows.md)
- [Data, permissions, and privacy](documentation/data-and-permissions.md)
- [Testing and regression gates](documentation/testing.md)
- [Build, release, and public mirror](documentation/releasing.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

The repository deliberately keeps the Python package name `stock_toolbox` as an internal
compatibility boundary. The product, app bundle, command, and release artifacts are named
EquityLens.

## License

EquityLens is available under the [MIT License](LICENSE).
