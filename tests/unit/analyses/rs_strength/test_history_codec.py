from __future__ import annotations

import json

from stock_toolbox.analyses.rs_strength.persistence.history_codec import (
    RSHistoryCodec,
)
from tests.integration.persistence.test_history_repository import snapshot


def test_rs_history_codec_owns_module_envelope() -> None:
    codec = RSHistoryCodec()
    expected = snapshot(40)

    content = codec.dumps(expected)
    envelope = json.loads(content)

    assert envelope["analysis_type"] == codec.analysis_type
    assert envelope["analysis_version"] == codec.analysis_version
    assert envelope["result_schema_version"] == codec.result_schema_version
    assert codec.loads(content) == expected


def test_pre_094_rs_history_without_reliability_still_loads() -> None:
    codec = RSHistoryCodec()
    legacy = snapshot(41)
    assert "reliability" not in legacy.header.snapshot_extensions

    loaded = codec.loads(codec.dumps(legacy))

    assert loaded == legacy
    assert "reliability" not in loaded.header.snapshot_extensions
