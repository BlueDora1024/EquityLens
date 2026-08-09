from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from stock_toolbox.analyses.rs_strength.application.report import (
    DISCLAIMER,
    build_report_payload,
    normalize_report_text,
    system_prompt,
)
from stock_toolbox.infrastructure.persistence.history_records import (
    HistoryClassificationRecord,
    HistoryMemberRecord,
    HistoryRangeRecord,
    HistorySnapshotRecord,
    HistoryStockResultRecord,
)
from tests.integration.persistence.test_history_repository import snapshot


def _uid(number: int) -> str:
    return f"71000000-0000-4000-8000-{number:012d}"


def _large_snapshot() -> HistorySnapshotRecord:
    base = snapshot(1)
    ranges = tuple(
        HistoryRangeRecord(
            run_range_id=_uid(100 + ordinal),
            run_id=base.header.run_id,
            ordinal=ordinal,
            range_key=key,
            label=label,
            kind=kind,
            requested_start_date=date(2025 + ordinal, 1, 1),
            requested_end_date=date(2026, 7, 24),
            actual_start_date=date(2025 + ordinal, 1, 2),
            actual_end_date=date(2026, 7, 23),
            benchmark_start_close=Decimal(100),
            benchmark_end_close=Decimal(110),
            base_weight=weight,
            normalized_weight=weight / Decimal(6),
        )
        for ordinal, (key, label, kind, weight) in enumerate(
            (
                ("3M", "近 3 个月", "PRESET_3M", Decimal(1)),
                ("6M", "近 6 个月", "PRESET_6M", Decimal(2)),
                ("1Y", "近 1 年", "PRESET_1Y", Decimal(3)),
            )
        )
    )
    members = tuple(
        HistoryMemberRecord(
            id=_uid(200 + ordinal),
            run_id=base.header.run_id,
            ordinal=ordinal,
            source_membership_id=f"membership-{ordinal}",
            source_security_id=f"security-{ordinal}",
            source_binding_id=f"binding-{ordinal}",
            canonical_symbol=f"S{ordinal:02d}.US",
            market="US",
            company_name=f"证券 {ordinal:02d}",
            classification_snapshot_key=f"C{ordinal % 3}",
            source_classification_id=f"classification-{ordinal % 3}",
            participating_classification_name=f"分类 {ordinal % 3}",
            participating_classification_normalized_name=f"classification {ordinal % 3}",
        )
        for ordinal in range(40)
    )
    stock_results = tuple(
        HistoryStockResultRecord(
            id=_uid(1000 + range_item.ordinal * 100 + member.ordinal),
            run_id=base.header.run_id,
            run_member_id=member.id,
            run_range_id=range_item.run_range_id,
            stock_start_close=Decimal(100),
            stock_end_close=Decimal(110),
            benchmark_start_close=Decimal(100),
            benchmark_end_close=Decimal(105),
            stock_return=Decimal(member.ordinal - 20) / Decimal(100),
            benchmark_return=Decimal("0.05"),
            rs_percentage_points=(
                Decimal(member.ordinal - 20)
                * (Decimal(-1) if range_item.ordinal == 0 else Decimal(1))
            ),
        )
        for range_item in ranges
        for member in members
        if not (range_item.ordinal == 2 and member.ordinal == 0)
    )
    classifications = tuple(
        HistoryClassificationRecord(
            id=_uid(2000 + ordinal),
            run_id=base.header.run_id,
            classification_snapshot_key=f"C{ordinal}",
            classification_name=f"分类 {ordinal}",
            composite_score=Decimal(80 - ordinal * 30),
            multi_period_status=("SUSTAINED_STRONG" if ordinal == 0 else "DIVERGENT"),
            reason=f"reason-{ordinal}",
        )
        for ordinal in range(3)
    )
    return HistorySnapshotRecord(
        header=replace(
            base.header,
            member_count=40,
            valid_member_count=40,
            snapshot_extensions={},
        ),
        ranges=ranges,
        members=members,
        stock_results=stock_results,
        classification_period_results=(),
        classification_results=classifications,
        failures=(),
    )


def test_report_payload_is_bounded_deduplicated_and_stable() -> None:
    expected = _large_snapshot()

    payload = build_report_payload(expected)

    assert payload == build_report_payload(expected)
    assert all(len(item["strongest"]) == 15 for item in payload["ranges"])
    assert all(len(item["weakest"]) == 15 for item in payload["ranges"])
    assert len(payload["composite"]["strongest"]) == 20
    assert len(payload["composite"]["weakest"]) == 20
    securities = payload["securities"]
    assert len({item["symbol"] for item in securities}) == len(securities)
    assert all(not item["symbol"].endswith(".US") for item in securities)
    assert payload["metadata"]["failed_member_count"] == 0
    assert len(payload["scored_classifications"]) == 3
    assert payload["insufficient_sample_classifications"] == []


def test_report_payload_normalizes_missing_range_weights() -> None:
    payload = build_report_payload(_large_snapshot())
    first = next(item for item in payload["securities"] if item["symbol"] == "S00")

    assert first["covered_range_count"] == 2
    assert first["composite_rs"] == "-6.6667"


def test_report_prompt_rejects_invented_causes_and_requires_disclaimer() -> None:
    prompt = system_prompt()

    assert "不得虚构行情、新闻或基本面原因" in prompt
    assert "数据直接支持" in prompt
    assert "相对强弱的推断" in prompt
    assert "每个小点最多三句话" in prompt
    assert "样本不足分类只允许在最后的数据说明中用一句话集中列出" in prompt
    assert "一、总体结论" in prompt
    assert "1. 最强方向" in prompt
    assert "五、短期强度跃迁" in prompt
    assert "不得据此认定主力进场" in prompt
    assert DISCLAIMER in prompt


def test_report_payload_ranks_loose_short_term_jumps_without_hard_gate() -> None:
    payload = build_report_payload(_large_snapshot())

    jumps = payload["short_term_rank_jumps"]["securities"]
    assert len(jumps) <= 10
    assert jumps[0] == {
        "symbol": "S00",
        "short_range": "3M",
        "short_rank": 1,
        "short_total": 40,
        "short_rs": "20",
        "long_range": "6M",
        "long_rank": 40,
        "long_total": 40,
        "long_rs": "-20",
        "rank_improvement": "1",
    }
    assert all(Decimal(item["rank_improvement"]) > 0 for item in jumps)


def test_report_payload_says_no_jump_when_only_one_range_exists() -> None:
    payload = build_report_payload(snapshot(1))

    assert payload["short_term_rank_jumps"] == {
        "securities": [],
        "classifications": [],
        "summary": "本次没有可比较的正向短期排名跃迁",
    }


def test_report_text_is_projected_as_plain_text() -> None:
    raw = (
        "## 总体结论\n"
        "**强势分类**\n"
        "* 半导体\n"
        "- 数据中心\n"
        "`观察条件`\n\n\n\n"
        "RS 相对强弱复盘，不构成投资建议。"
    )

    assert normalize_report_text(raw) == (
        "总体结论\n强势分类\n• 半导体\n• 数据中心\n观察条件\n\nRS 相对强弱复盘，不构成投资建议。"
    )
    assert "不要使用 Markdown" in system_prompt()


def test_small_pool_never_places_one_security_on_both_sides() -> None:
    payload = build_report_payload(snapshot(1))

    assert payload["ranges"][0]["strongest"] == [{"symbol": "IREN", "rs": "20"}]
    assert payload["ranges"][0]["weakest"] == []
    assert payload["composite"]["strongest"] == [
        {"symbol": "IREN", "rs": "20", "covered_range_count": 1}
    ]
    assert payload["composite"]["weakest"] == []
    assert payload["scored_classifications"] == []
    assert payload["insufficient_sample_classifications"] == [
        {
            "name": "AI Data Center",
            "valid_member_count": 1,
            "required_member_count": 3,
        }
    ]
