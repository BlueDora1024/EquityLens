# Build, release, and public mirror

## Local build

`./scripts/build_app.sh` runs the full quality gate, builds the native app and CLI, verifies
the bundle, runs packaged acceptance, signs ad hoc, and creates an architecture-specific
ZIP plus SHA-256 file.

## Public mirror

The private working tree is the source of truth. Publication is one-way and allowlisted:

```bash
.venv/bin/python scripts/sync_public_repo.py /path/to/EquityLens
```

The command deletes stale public files, preserves the destination `.git` directory, copies
only `scripts/public_manifest.txt` entries, then fails closed if it finds runtime data,
logs, private paths, keys, or secret-like values. Review the public diff before committing.

## GitHub Actions

Pull requests run deterministic tests. A `v*` tag builds on two native GitHub-hosted macOS
runners: Apple silicon (`macos-15`) and Intel (`macos-15-intel`). Each produces its own app
archive and checksum. The publish job attaches both architectures to one GitHub Release.

No provider or AI credential is required or embedded by CI.
