import importlib
import importlib.util
from pathlib import Path

from stock_toolbox.infrastructure.providers.longbridge_oauth import (
    LongbridgeOAuthService,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment
from stock_toolbox.runtime.paths import RuntimePaths


def test_reset_clears_only_application_state_and_current_oauth_token(
    tmp_path: Path,
) -> None:
    assert importlib.util.find_spec("stock_toolbox.runtime.reset") is not None
    reset_module = importlib.import_module("stock_toolbox.runtime.reset")
    paths = RuntimePaths.resolve(RuntimeEnvironment.PRODUCTION, home=tmp_path)
    paths.data_root.mkdir(parents=True)
    paths.log_root.mkdir(parents=True)
    paths.exports_root.mkdir(parents=True)
    paths.database.write_text("business", encoding="utf-8")
    Path(f"{paths.database}-wal").write_text("wal", encoding="utf-8")
    paths.global_ai_database.write_text("ai", encoding="utf-8")
    (paths.log_root / "app.log").write_text("log", encoding="utf-8")
    exported = paths.exports_root / "result.zip"
    exported.write_text("export", encoding="utf-8")
    sync_marker = paths.data_root / "development-auto-sync"
    sync_marker.write_text("", encoding="utf-8")
    oauth = LongbridgeOAuthService(home=tmp_path)
    current = oauth.token_path("current-client")
    other = oauth.token_path("other-client")
    current.parent.mkdir(parents=True)
    current.write_text("current", encoding="utf-8")
    other.write_text("other", encoding="utf-8")

    reset_module.reset_local_state(paths, oauth, "current-client")

    assert not paths.database.exists()
    assert not Path(f"{paths.database}-wal").exists()
    assert not paths.global_ai_database.exists()
    assert not paths.log_root.exists()
    assert not current.exists()
    assert exported.read_text(encoding="utf-8") == "export"
    assert sync_marker.exists()
    assert other.read_text(encoding="utf-8") == "other"
