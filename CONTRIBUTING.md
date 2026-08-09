# Contributing to EquityLens

Thanks for improving EquityLens. Small, focused changes are easiest to review and safest
for a market-data application.

## Before opening a change

1. Search existing issues and describe the user-visible problem.
2. Keep provider SDK code behind the provider adapter boundary.
3. Add a failing test before changing behavior.
4. Never commit credentials, tokens, account data, SQLite files, logs, or proprietary
   market-data captures.

## Development workflow

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
./scripts/test.sh fast
```

Run the smallest affected gate while iterating, then `./scripts/test.sh full` before a
release. See [testing.md](documentation/testing.md) for the ownership map.

## Pull requests

- Explain the behavior before and after the change.
- Include tests and screenshots for visible UI changes.
- Call out provider quota or request-count changes.
- Keep generated files, app bundles, and runtime state out of the commit.

By contributing, you agree that your contribution is licensed under the MIT License.
