# Testing and regression gates

Use the smallest gate that owns the changed behavior. Run the full gate only before a
release or after a cross-cutting change.

| Scope | Command |
| --- | --- |
| deterministic inner loop | `./scripts/test.sh fast` |
| RS Strength | `./scripts/test.sh batch rs` |
| Turning Point | `./scripts/test.sh batch turning-point` |
| Extreme Deviation | `./scripts/test.sh batch extreme-deviation` |
| QML and desktop bridges | `./scripts/test.sh batch desktop-qml` |
| providers, persistence, runtime | `./scripts/test.sh batch platform` |
| complete release gate | `./scripts/test.sh full` |
| packaged bundle | `./scripts/test.sh package` |

Live provider tests are explicit because they consume network resources and may depend on
user-side authorization. They are not a substitute for deterministic adapter contracts.

A release must also pass bundle identity, executable architecture, ad-hoc signature,
packaged CLI, QML startup, and public-repository secret scanning.
