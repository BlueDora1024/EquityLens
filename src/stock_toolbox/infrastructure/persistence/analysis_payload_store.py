"""Generic JSON history store for independent analysis tools."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRun,
)
from stock_toolbox.analyses.turning_point.application.history import (
    project_turning_point_history,
)
from stock_toolbox.analyses.turning_point.application.models import TurningPointRun
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.types import (
    canonical_decimal_text,
    canonical_instant,
    canonical_json,
    parse_canonical_instant,
    parse_canonical_json,
)


class AnalysisPayloadStore:
    def __init__(self, factory: SQLiteConnectionFactory) -> None:
        self._factory = factory

    def save_turning_point(self, run: TurningPointRun) -> None:
        payload = _jsonable(run)
        if not isinstance(payload, dict):
            raise TypeError("turning-point payload must be an object")
        self._save(
            run.run_id,
            "turning_point",
            "2.0.0",
            run.operation_id,
            (
                "PARTIAL"
                if any(item.status != "READY" for item in run.results)
                else "READY"
            ),
            run.provider_id,
            f"{run.watchlist_name} · {len(run.request.intervals)} 周期",
            run.completed_at,
            payload,
        )

    def save_extreme_deviation(self, run: ExtremeDeviationRun) -> None:
        payload = _jsonable(run)
        if not isinstance(payload, dict):
            raise TypeError("extreme-deviation payload must be an object")
        self._save(
            run.run_id,
            "extreme_deviation",
            "1.0.0",
            run.operation_id,
            ("PARTIAL" if any(item.status != "READY" for item in run.results) else "READY"),
            run.provider_id,
            f"{run.watchlist_name} · {len(run.request.intervals)} 周期",
            run.completed_at,
            payload,
        )

    def _save(
        self,
        run_id: str,
        analysis_type: str,
        analysis_version: str,
        operation_id: str,
        status: str,
        provider_id: str,
        display_name: str,
        completed_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        connection = self._factory.open_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO analysis_payload_runs("
                "run_id,analysis_type,analysis_version,operation_id,status,"
                "provider_id,display_name,completed_at_utc,payload_json"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    analysis_type,
                    analysis_version,
                    operation_id,
                    status,
                    provider_id,
                    display_name,
                    canonical_instant(completed_at),
                    canonical_json(payload),
                ),
            )
            connection.execute(
                "DELETE FROM analysis_payload_runs WHERE run_id IN ("
                "SELECT run_id FROM analysis_payload_runs "
                "WHERE analysis_type=? AND pinned=0 "
                "ORDER BY completed_at_utc DESC,run_id DESC LIMIT -1 OFFSET 10"
                ")",
                (analysis_type,),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def list(self, analysis_type: str, *, limit: int = 10) -> tuple[dict[str, Any], ...]:
        connection = self._factory.open_reader()
        try:
            rows = connection.execute(
                "SELECT run_id,display_name,completed_at_utc,pinned,note,payload_json "
                "FROM analysis_payload_runs WHERE analysis_type=? "
                "ORDER BY pinned DESC,completed_at_utc DESC,run_id DESC LIMIT ?",
                (analysis_type, max(1, limit)),
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "run_id": str(row["run_id"]),
                "display_name": str(row["display_name"]),
                "completed_at": parse_canonical_instant(row["completed_at_utc"]),
                "pinned": bool(row["pinned"]),
                "note": str(row["note"]),
                "payload": parse_canonical_json(row["payload_json"]),
            }
            for row in rows
        )

    def get_payload(
        self,
        run_id: str,
        analysis_type: str,
    ) -> dict[str, Any]:
        connection = self._factory.open_reader()
        try:
            row = connection.execute(
                "SELECT payload_json FROM analysis_payload_runs WHERE run_id=? AND analysis_type=?",
                (run_id, analysis_type),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(run_id)
        payload = parse_canonical_json(row["payload_json"])
        if not isinstance(payload, dict):
            raise TypeError("analysis payload is invalid")
        return payload

    def attach_ai_report(
        self,
        run_id: str,
        analysis_type: str,
        report: dict[str, Any],
    ) -> None:
        connection = self._factory.open_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM analysis_payload_runs WHERE run_id=? AND analysis_type=?",
                (run_id, analysis_type),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            payload = parse_canonical_json(row["payload_json"])
            if not isinstance(payload, dict):
                raise TypeError("analysis payload is invalid")
            reports = payload.get("ai_reports", [])
            if not isinstance(reports, list):
                raise TypeError("analysis reports are invalid")
            payload["ai_reports"] = [*reports, report]
            connection.execute(
                "UPDATE analysis_payload_runs SET payload_json=? "
                "WHERE run_id=? AND analysis_type=?",
                (canonical_json(payload), run_id, analysis_type),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def export(self, run_id: str, format_name: str) -> str:
        connection = self._factory.open_reader()
        try:
            row = connection.execute(
                "SELECT analysis_type,payload_json FROM analysis_payload_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(run_id)
        payload = parse_canonical_json(row["payload_json"])
        if format_name == "json":
            return canonical_json(payload)
        if str(row["analysis_type"]) == "extreme_deviation":
            return _export_extreme_deviation(payload, format_name)
        return _export_turning_point(payload, format_name)

    def set_pinned(self, run_id: str, pinned: bool) -> None:
        connection = self._factory.open_writer()
        try:
            cursor = connection.execute(
                "UPDATE analysis_payload_runs SET pinned=? WHERE run_id=?",
                (int(pinned), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        finally:
            connection.close()

    def delete(self, run_id: str) -> None:
        connection = self._factory.open_writer()
        try:
            cursor = connection.execute(
                "DELETE FROM analysis_payload_runs WHERE run_id=?",
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        finally:
            connection.close()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _jsonable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _export_extreme_deviation(
    payload: dict[str, Any],
    format_name: str,
) -> str:
    rows: list[dict[str, Any]] = []
    sources = payload.get("source_by_symbol", {})
    sources = sources if isinstance(sources, dict) else {}
    requested_window = _window_text(payload.get("requested_date_window"))
    actual_window = _window_text(payload.get("actual_date_window"))
    for result in payload.get("results", []):
        consensus = result.get("consensus", {})
        for period in result.get("periods", []):
            score = period.get("score") or {}
            rows.append(
                {
                    "symbol": result.get("symbol", ""),
                    "source": sources.get(result.get("symbol", ""), ""),
                    "requested_date_window": requested_window,
                    "actual_date_window": actual_window,
                    "classification": result.get("classification_name", ""),
                    "consensus": consensus.get("kind", ""),
                    "interval": period.get("interval", ""),
                    "score": score.get("score", ""),
                    "label": score.get("label", ""),
                    "confidence": score.get("confidence", ""),
                    "error": period.get("error_code", "") or "",
                }
            )
    if format_name == "csv":
        output = io.StringIO()
        fields = (
            "symbol",
            "classification",
            "consensus",
            "interval",
            "score",
            "label",
            "confidence",
            "error",
            "source",
            "requested_date_window",
            "actual_date_window",
        )
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    if format_name == "markdown":
        lines = [
            "# 极值偏离结果",
            "",
            f"- 请求日期窗口：{requested_window or '未记录'}",
            f"- 实际日期窗口：{actual_window or '未记录'}",
            "",
            "| 代码 | 来源 | 本次参评分类 | 多周期结论 | 周期 | 评分 | 等级 | 置信度 | 错误 |",
            "|---|---|---|---|---|---:|---|---|---|",
        ]
        lines.extend(
            "| {symbol} | {source} | {classification} | {consensus} | {interval} | "
            "{score} | {label} | {confidence} | {error} |".format(**item)
            for item in rows
        )
        return "\n".join(lines)
    raise ValueError("unsupported export format")


def _export_turning_point(
    payload: dict[str, Any],
    format_name: str,
) -> str:
    projection = project_turning_point_history(payload)
    sources = payload.get("source_by_symbol", {})
    sources = sources if isinstance(sources, dict) else {}
    requested_window = _window_text(payload.get("requested_date_window"))
    actual_window = _window_text(payload.get("actual_date_window"))
    rows: list[dict[str, Any]] = []
    for item in projection["rows"]:
        common = {
            "trade_side": projection["trade_side"],
            "symbol": item["symbol"],
            "source": sources.get(item["symbol"], ""),
            "requested_date_window": requested_window,
            "actual_date_window": actual_window,
            "company_name": item["company_name"],
            "classification_name": item["classification_name"],
            "attention_score": item["attention_score"],
            "attention_level": item["attention_level"],
            "conclusion": item["conclusion"],
            "risk_flags": " / ".join(item["risk_flags"]),
        }
        for period in item["period_results"]:
            if period["decision"] != "MATCHED":
                continue
            rows.append(
                {
                    **common,
                    "interval": period["interval"],
                    "signal": period["signal_label"],
                    "signal_at": period["signal_at"] or "",
                    "enhanced_at": period["enhanced_at"] or "",
                    "crossed_at": period["crossed_at"] or "",
                    "last_price": _value_or_blank(period["last_price"]),
                    "volume_ratio": _value_or_blank(period["volume_ratio"]),
                    "quality_score": _value_or_blank(period["quality_score"]),
                }
            )
    fields = (
        "trade_side",
        "symbol",
        "source",
        "requested_date_window",
        "actual_date_window",
        "company_name",
        "classification_name",
        "interval",
        "signal",
        "signal_at",
        "enhanced_at",
        "crossed_at",
        "last_price",
        "volume_ratio",
        "quality_score",
        "attention_score",
        "attention_level",
        "conclusion",
        "risk_flags",
    )
    if format_name == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    if format_name == "markdown":
        lines = [
            "# 拐点筛选结果",
            "",
            f"交易侧：{projection['trade_side_label']}",
            f"请求日期窗口：{requested_window or '未记录'}",
            f"实际日期窗口：{actual_window or '未记录'}",
            "",
            "| 代码 | 来源 | 名称 | 本次参评分类 | 周期 | 信号 | 关注度 | 档位 | 结论 |",
            "|---|---|---|---|---|---|---:|---|---|",
        ]
        lines.extend(
            "| {symbol} | {source} | {company_name} | {classification_name} | "
            "{interval} | {signal} | {attention_score} | "
            "{attention_level} | {conclusion} |".format(**item)
            for item in rows
        )
        return "\n".join(lines)
    raise ValueError("unsupported export format")


def _window_text(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return ""
    return f"{value[0]} — {value[1]}"


def _value_or_blank(value: Any) -> Any:
    return "" if value is None else value
