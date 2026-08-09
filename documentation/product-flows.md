# Product flows

## First run

Choose and validate one market-data provider. AI configuration is optional. A provider
must pass read-only checks before analysis tools are enabled.

## Shared data

Import US common stocks into one global security library. Assign up to three reusable
business tags, then add a security to any number of watchlists with one selected evaluation
tag per watchlist.

## Analysis tools

- **RS Strength:** watchlist → benchmark → date ranges → preflight → fetch → calculate →
  aggregate by selected tag → frozen result.
- **Turning Point:** watchlist → strategy side → periods → date → preflight → signals →
  risk annotations → history.
- **Extreme Deviation:** one security → selected periods → date → preflight → pressure
  calculation → visual result → optional AI interpretation.

Long operations disable duplicate submission, remain cancellable, publish incremental
progress, and keep the Qt event loop free. Provider/resource failures are summarized once
rather than producing a dialog storm.
