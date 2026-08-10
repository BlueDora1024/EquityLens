from __future__ import annotations

from stock_toolbox.infrastructure.updates.models import BuildIdentity
from stock_toolbox.infrastructure.updates.service import (
    asset_names_for,
    is_newer_version,
    parse_release,
    parse_sha256,
    summarize_release_notes,
)


def test_versions_compare_semantically() -> None:
    assert is_newer_version("1.10.0", "1.9.9") is True
    assert is_newer_version("v1.1.0", "1.1.0") is False
    assert is_newer_version("latest", "1.0.0") is False


def test_release_selects_only_the_matching_architecture_assets() -> None:
    payload = {
        "tag_name": "v1.1.0",
        "name": "EquityLens 1.1.0",
        "body": "## 更新内容\n- 自动检查更新\n- 安全原位替换",
        "published_at": "2026-08-10T08:00:00Z",
        "html_url": "https://github.com/BlueDora1024/EquityLens/releases/tag/v1.1.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "EquityLens-v1.1.0-arm64.zip", "browser_download_url": "https://example/arm.zip", "size": 10},
            {"name": "EquityLens-v1.1.0-arm64.zip.sha256", "browser_download_url": "https://example/arm.sha", "size": 64},
            {"name": "EquityLens-v1.1.0-x86_64.zip", "browser_download_url": "https://example/intel.zip", "size": 11},
            {"name": "EquityLens-v1.1.0-x86_64.zip.sha256", "browser_download_url": "https://example/intel.sha", "size": 64},
        ],
    }

    release = parse_release(payload, architecture="x86_64")

    assert release.tag == "v1.1.0"
    assert release.archive.name.endswith("x86_64.zip")
    assert release.checksum.name.endswith("x86_64.zip.sha256")
    assert release.notes == ("自动检查更新", "安全原位替换")


def test_asset_names_are_versioned_and_architecture_specific() -> None:
    assert asset_names_for("v1.1.0", "arm64") == (
        "EquityLens-v1.1.0-arm64.zip",
        "EquityLens-v1.1.0-arm64.zip.sha256",
    )


def test_release_notes_are_plain_concise_lines() -> None:
    body = "# 标题\n\n- **自动更新**：后台检查\n- 修复卡顿\n\n更多信息见 [文档](https://example.com)。"
    assert summarize_release_notes(body, limit=2) == (
        "自动更新：后台检查",
        "修复卡顿",
    )


def test_sha256_parser_accepts_standard_sidecar_format() -> None:
    digest = "a" * 64
    assert parse_sha256(f"{digest}  EquityLens-v1.1.0-arm64.zip\n") == digest


def test_build_identity_has_user_facing_summary() -> None:
    identity = BuildIdentity("1.1.0", "v1.1.0", "1234567890abcdef", "arm64")
    assert identity.short_sha == "1234567890ab"
