from pathlib import Path


def test_runtime_and_packaging_have_no_keychain_dependency() -> None:
    root = Path(__file__).parents[2]

    assert not (
        root / "src/stock_toolbox/infrastructure/secrets/keyring_store.py"
    ).exists()
    assert not (
        root / "src/stock_toolbox/infrastructure/persistence/credential_reconciler.py"
    ).exists()
    assert not (
        root / "tests/unit/infrastructure/secrets/test_keyring_store.py"
    ).exists()
    for path in (
        root / "pyproject.toml",
        root / "packaging/stock-toolbox.spec",
        root / "packaging/stock-toolbox-cli.spec",
        root / "scripts/verify_bundle.py",
    ):
        content = path.read_text(encoding="utf-8").casefold()
        assert "keyring" not in content
        assert "keychain" not in content
