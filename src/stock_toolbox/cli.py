"""Developer command-line entry point."""

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from stock_toolbox import __version__
from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SUPPORTED_INTERVALS as EXTREME_DEVIATION_INTERVALS,
)
from stock_toolbox.analyses.rs_strength.application.models import (
    CustomRange,
    RunRequest,
)
from stock_toolbox.analyses.turning_point.application.backtest import (
    TurningPointBacktest,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    TurningPointTradeSide,
)
from stock_toolbox.composition import build_analysis_registry, build_application
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.reliability_wire import reliability_payload
from stock_toolbox.core.settings.models import ServiceTestResult
from stock_toolbox.devtools.catalog import ScenarioCatalog, ScenarioNotFoundError
from stock_toolbox.devtools.runner import ScenarioRunner
from stock_toolbox.infrastructure.diagnostics.export import export_diagnostics
from stock_toolbox.infrastructure.diagnostics.query import diagnostic_status
from stock_toolbox.runtime.environment import RuntimeEnvironment
from stock_toolbox.runtime.paths import RuntimePaths

_ENVIRONMENT_ALIASES = {
    "production": RuntimeEnvironment.PRODUCTION,
    "dev": RuntimeEnvironment.DEVELOPMENT,
    "integration": RuntimeEnvironment.INTEGRATION,
    "scenario": RuntimeEnvironment.SCENARIO,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock-toolbox")
    parser.add_argument(
        "--env",
        choices=tuple(_ENVIRONMENT_ALIASES),
        default="dev",
    )
    parser.add_argument("--home", type=Path, default=Path.home())
    commands = parser.add_subparsers(dest="command", required=True)

    analysis = commands.add_parser("analysis")
    analysis_commands = analysis.add_subparsers(
        dest="analysis_command",
        required=True,
    )
    analysis_list = analysis_commands.add_parser("list")
    analysis_list.add_argument("--json", action="store_true")
    rs = analysis_commands.add_parser("rs-strength")
    rs_commands = rs.add_subparsers(dest="rs_command", required=True)
    rs_run = rs_commands.add_parser("run")
    rs_run.add_argument("--scenario")
    rs_run.add_argument("--watchlist-id")
    rs_run.add_argument(
        "--benchmark",
        choices=("SPY.US", "QQQ.US"),
        default="SPY.US",
    )
    rs_run.add_argument("--end-date", type=date.fromisoformat)
    rs_run.add_argument(
        "--range",
        dest="ranges",
        choices=("1W", "2W", "1M", "3M", "6M", "1Y"),
        action="append",
    )
    rs_run.add_argument("--json", action="store_true")
    rs_worker = rs_commands.add_parser("run-worker")
    rs_worker.add_argument("--watchlist-id", required=True)
    rs_worker.add_argument(
        "--benchmark",
        choices=("SPY.US", "QQQ.US"),
        default="SPY.US",
    )
    rs_worker.add_argument("--end-date", type=date.fromisoformat, required=True)
    rs_worker.add_argument(
        "--range",
        dest="ranges",
        choices=("1W", "2W", "1M", "3M", "6M", "1Y"),
        action="append",
    )
    rs_worker.add_argument("--custom-start", type=date.fromisoformat)
    rs_worker.add_argument("--custom-end", type=date.fromisoformat)
    rs_worker.add_argument("--force-yahoo", action="store_true")
    rs_history = rs_commands.add_parser("history")
    rs_history_commands = rs_history.add_subparsers(
        dest="history_command",
        required=True,
    )
    rs_history_list = rs_history_commands.add_parser("list")
    rs_history_list.add_argument("--limit", type=int, default=10)
    rs_history_list.add_argument("--json", action="store_true")
    turning = analysis_commands.add_parser("turning-point")
    turning_commands = turning.add_subparsers(
        dest="turning_command",
        required=True,
    )
    turning_run = turning_commands.add_parser("run")
    _add_turning_run_arguments(turning_run, include_scenario=True)
    turning_worker = turning_commands.add_parser("run-worker")
    _add_turning_run_arguments(turning_worker, include_scenario=False)
    turning_backtest = turning_commands.add_parser("backtest")
    turning_backtest.add_argument(
        "--symbol",
        dest="symbols",
        action="append",
        default=None,
    )
    turning_backtest.add_argument(
        "--interval",
        dest="intervals",
        choices=tuple(item.value for item in CandleInterval),
        action="append",
    )
    turning_backtest.add_argument("--end-date", type=date.fromisoformat)
    turning_backtest.add_argument(
        "--trade-side",
        choices=("left", "right", "both"),
        default="both",
    )
    turning_backtest.add_argument("--count", type=int, default=1000)
    turning_backtest.add_argument("--output", type=Path)
    turning_backtest.add_argument("--json", action="store_true")
    turning_history = turning_commands.add_parser("history")
    turning_history_commands = turning_history.add_subparsers(
        dest="turning_history_command",
        required=True,
    )
    turning_history_list = turning_history_commands.add_parser("list")
    turning_history_list.add_argument("--limit", type=int, default=10)
    turning_history_list.add_argument("--json", action="store_true")
    deviation = analysis_commands.add_parser("extreme-deviation")
    deviation_commands = deviation.add_subparsers(
        dest="deviation_command",
        required=True,
    )
    deviation_run = deviation_commands.add_parser("run")
    deviation_run.add_argument("--watchlist-id")
    deviation_run.add_argument(
        "--scenario",
        choices=("extreme-deviation-full",),
    )
    deviation_run.add_argument(
        "--intervals",
        default=",".join(item.value for item in EXTREME_DEVIATION_INTERVALS),
    )
    deviation_run.add_argument("--symbols")
    deviation_run.add_argument("--end-date", type=date.fromisoformat)
    deviation_run.add_argument("--json", action="store_true")
    deviation_worker = deviation_commands.add_parser("run-worker")
    deviation_worker.add_argument("--security-id", required=True)
    deviation_worker.add_argument(
        "--interval",
        dest="intervals",
        choices=tuple(item.value for item in EXTREME_DEVIATION_INTERVALS),
        action="append",
        required=True,
    )
    deviation_worker.add_argument("--end-date", type=date.fromisoformat, required=True)
    deviation_worker.add_argument("--force-yahoo", action="store_true")
    deviation_report = deviation_commands.add_parser("report")
    deviation_report.add_argument("--run-id", required=True)
    deviation_report.add_argument("--symbols", required=True)
    deviation_report.add_argument("--json", action="store_true")
    deviation_history = deviation_commands.add_parser("history")
    deviation_history_commands = deviation_history.add_subparsers(
        dest="deviation_history_command",
        required=True,
    )
    deviation_history_list = deviation_history_commands.add_parser("list")
    deviation_history_list.add_argument("--limit", type=int, default=10)
    deviation_history_list.add_argument("--json", action="store_true")

    scenario = commands.add_parser("scenario")
    scenario_commands = scenario.add_subparsers(dest="scenario_command", required=True)

    list_command = scenario_commands.add_parser("list")
    list_command.add_argument("--json", action="store_true")

    validate_command = scenario_commands.add_parser("validate")
    validate_command.add_argument("scenario_id")
    validate_command.add_argument("--json", action="store_true")

    run_command = scenario_commands.add_parser("run")
    run_command.add_argument("scenario_id")
    run_command.add_argument("--json", action="store_true")

    live_smoke = commands.add_parser("live-smoke")
    live_smoke.add_argument("--symbol", default="IREN.US")
    live_smoke.add_argument(
        "--benchmark",
        choices=("SPY.US", "QQQ.US"),
        default="SPY.US",
    )
    live_smoke.add_argument("--json", action="store_true")
    services = commands.add_parser("services")
    service_commands = services.add_subparsers(
        dest="service_command",
        required=True,
    )
    service_commands.add_parser("status").add_argument(
        "--json",
        action="store_true",
    )
    service_quality = service_commands.add_parser("quality")
    service_quality.add_argument(
        "--provider",
        choices=("active", "longbridge", "futu"),
        default="active",
    )
    service_quality.add_argument("--json", action="store_true")
    diagnostics = commands.add_parser("diagnostics")
    diagnostics_commands = diagnostics.add_subparsers(
        dest="diagnostics_command",
        required=True,
    )
    diagnostics_status = diagnostics_commands.add_parser("status")
    diagnostics_status.add_argument("--json", action="store_true")
    diagnostics_export = diagnostics_commands.add_parser("export")
    diagnostics_export.add_argument("--output", type=Path, required=True)
    diagnostics_export.add_argument("--json", action="store_true")
    diagnostics_clear = diagnostics_commands.add_parser("clear")
    diagnostics_clear.add_argument("--confirm", action="store_true")
    diagnostics_clear.add_argument("--json", action="store_true")
    securities = commands.add_parser("securities")
    securities_commands = securities.add_subparsers(
        dest="securities_command",
        required=True,
    )
    securities_commands.add_parser("import-worker")
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _add_turning_run_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_scenario: bool,
) -> None:
    parser.add_argument("--watchlist-id")
    if include_scenario:
        parser.add_argument(
            "--scenario",
            choices=("turning-point-full",),
        )
    parser.add_argument(
        "--interval",
        dest="intervals",
        choices=tuple(item.value for item in CandleInterval),
        action="append",
    )
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument(
        "--trade-side",
        choices=("left", "right"),
        default="right",
    )
    parser.add_argument("--force-yahoo", action="store_true")
    parser.add_argument("--json", action="store_true")


def _rs_strength_worker(
    args: argparse.Namespace,
    environment: RuntimeEnvironment,
) -> int:
    application = build_application(environment, home=args.home)

    def report(progress: object) -> None:
        feedback = getattr(progress, "feedback", None)
        _emit(
            {
                "schema_version": "rs-strength-worker-v1",
                "type": "progress",
                "stage": str(getattr(progress, "stage", "")),
                "completed": int(getattr(progress, "completed", 0)),
                "total": int(getattr(progress, "total", 0)),
                "current": str(getattr(progress, "current", "") or ""),
                "succeeded": getattr(progress, "succeeded", None),
                "failed": getattr(progress, "failed", None),
                "feedback": (
                    {
                        "kind": str(feedback.kind),
                        "failure_code": (
                            str(feedback.failure_code)
                            if feedback.failure_code is not None
                            else None
                        ),
                        "symbol": feedback.symbol,
                        "interval": feedback.interval,
                        "attempt": feedback.attempt,
                        "max_attempts": feedback.max_attempts,
                        "wait_seconds": feedback.wait_seconds,
                        "active_concurrency": feedback.active_concurrency,
                    }
                    if feedback is not None
                    else None
                ),
            }
        )

    def fallback_consent(offer: object) -> bool:
        _emit(
            {
                "schema_version": "rs-strength-worker-v1",
                "type": "fallback",
                "operation_kind": str(
                    getattr(offer, "operation_kind", "rs_strength")
                ),
                "failed_symbols": list(getattr(offer, "failed_symbols", ())),
                "intervals": list(getattr(offer, "intervals", ())),
                "failure_codes": [
                    str(item) for item in getattr(offer, "failure_codes", ())
                ],
                "completed": int(getattr(offer, "completed", 0)),
                "total": int(getattr(offer, "total", 0)),
            }
        )
        return sys.stdin.readline().strip().casefold() == "accept"

    try:
        custom_range = (
            CustomRange(args.custom_start, args.custom_end)
            if args.custom_start is not None and args.custom_end is not None
            else None
        )
        result = application.run(
            RunRequest(
                str(args.watchlist_id),
                str(args.benchmark),
                args.end_date,
                tuple(args.ranges or ()),
                custom_range,
            ),
            progress=report,
            fallback_consent=(None if args.force_yahoo else fallback_consent),
            force_yahoo=bool(args.force_yahoo),
        )
        payload: dict[str, Any] = {
            "schema_version": "rs-strength-worker-v1",
            "type": "result",
            "status": result.status.value,
            "run_id": result.run_id,
            "error_code": result.error_code,
        }
        if result.reliability is not None:
            payload["reliability"] = reliability_payload(result.reliability)
        _emit(payload)
        return 0 if result.run_id is not None else 69
    except Exception:  # noqa: BLE001 - sanitized process boundary
        _emit(
            {
                "schema_version": "rs-strength-worker-v1",
                "type": "error",
                "code": "rs_strength_worker_failed",
            }
        )
        return 69
    finally:
        application.close()


def _turning_point_worker(
    args: argparse.Namespace,
    environment: RuntimeEnvironment,
) -> int:
    application = build_application(environment, home=args.home)

    def report(progress: object) -> None:
        feedback = getattr(progress, "feedback", None)
        _emit(
            {
                "schema_version": "turning-point-worker-v1",
                "type": "progress",
                "stage": str(getattr(progress, "stage", "")),
                "completed": int(getattr(progress, "completed", 0)),
                "total": int(getattr(progress, "total", 0)),
                "current": str(getattr(progress, "current", "") or ""),
                "feedback": (
                    {
                        "kind": str(feedback.kind),
                        "failure_code": (
                            str(feedback.failure_code)
                            if feedback.failure_code is not None
                            else None
                        ),
                        "symbol": feedback.symbol,
                        "interval": feedback.interval,
                        "attempt": feedback.attempt,
                        "max_attempts": feedback.max_attempts,
                        "wait_seconds": feedback.wait_seconds,
                        "active_concurrency": feedback.active_concurrency,
                    }
                    if feedback is not None
                    else None
                ),
            }
        )

    def fallback_consent(offer: object) -> bool:
        _emit(
            {
                "schema_version": "turning-point-worker-v1",
                "type": "fallback",
                "operation_kind": str(getattr(offer, "operation_kind", "turning_point")),
                "failed_symbols": list(getattr(offer, "failed_symbols", ())),
                "intervals": list(getattr(offer, "intervals", ())),
                "failure_codes": [str(item) for item in getattr(offer, "failure_codes", ())],
                "completed": int(getattr(offer, "completed", 0)),
                "total": int(getattr(offer, "total", 0)),
            }
        )
        return sys.stdin.readline().strip().casefold() == "accept"

    try:
        result = application.run_turning_point(
            TurningPointRequest(
                str(args.watchlist_id or ""),
                tuple(
                    CandleInterval(str(raw))
                    for raw in (
                        args.intervals
                        or (
                            CandleInterval.MIN_30.value,
                            CandleInterval.MIN_60.value,
                            CandleInterval.DAY.value,
                        )
                    )
                ),
                args.end_date or datetime.now().astimezone().date(),
                trade_side=(
                    TurningPointTradeSide.LEFT_CD
                    if args.trade_side == "left"
                    else TurningPointTradeSide.RIGHT_CONFIRMED
                ),
            ),
            progress=report,
            fallback_consent=(None if args.force_yahoo else fallback_consent),
            force_yahoo=bool(args.force_yahoo),
        )
        payload: dict[str, Any] = {
            "schema_version": "turning-point-worker-v1",
            "type": "result",
            "status": result.status.value,
            "run_id": result.run_id,
            "error_code": result.error_code,
        }
        if result.reliability is not None:
            payload["reliability"] = reliability_payload(result.reliability)
        _emit(payload)
        return 0 if result.run is not None else 69
    except Exception:  # noqa: BLE001 - sanitized process boundary
        _emit(
            {
                "schema_version": "turning-point-worker-v1",
                "type": "error",
                "code": "turning_point_worker_failed",
            }
        )
        return 69
    finally:
        application.close()


def _security_import_worker(
    args: argparse.Namespace,
    environment: RuntimeEnvironment,
) -> int:
    application = build_application(environment, home=args.home)

    def report(progress: object) -> None:
        _emit(
            {
                "schema_version": "security-import-worker-v1",
                "type": "progress",
                "stage": str(getattr(progress, "stage", "")),
                "completed": int(getattr(progress, "completed", 0)),
                "total": int(getattr(progress, "total", 0)),
                "symbol": str(getattr(progress, "symbol", "")),
                "status": str(getattr(progress, "status", "")),
                "reason": str(getattr(progress, "reason", "")),
            }
        )

    try:
        result = application.import_securities(
            sys.stdin.read(),
            progress=report,
        )
        _emit(
            {
                "schema_version": "security-import-worker-v1",
                "type": "result",
                "committed": result.committed,
                "items": [
                    {
                        "symbol": item.symbol,
                        "status": item.status.value,
                        "reason": item.reason or "",
                    }
                    for item in result.items
                ],
                "duplicates": list(result.duplicate_input_symbols),
            }
        )
        return 0 if result.committed else 69
    except Exception:  # noqa: BLE001 - worker boundary is sanitized JSONL
        _emit(
            {
                "schema_version": "security-import-worker-v1",
                "type": "error",
                "code": "security_import_worker_failed",
            }
        )
        return 69
    finally:
        application.close()


def _extreme_deviation_worker(
    args: argparse.Namespace,
    environment: RuntimeEnvironment,
) -> int:
    application = build_application(environment, home=args.home)

    def report(progress: object) -> None:
        feedback = getattr(progress, "feedback", None)
        _emit(
            {
                "schema_version": "extreme-deviation-worker-v1",
                "type": "progress",
                "stage": str(getattr(progress, "stage", "")),
                "completed": int(getattr(progress, "completed", 0)),
                "total": int(getattr(progress, "total", 0)),
                "current": str(getattr(progress, "current", "") or ""),
                "cache_hits": int(getattr(progress, "cache_hits", 0)),
                "fetched": int(getattr(progress, "fetched", 0)),
                "failures": int(getattr(progress, "failures", 0)),
                "feedback": (
                    {
                        "kind": str(feedback.kind),
                        "failure_code": (
                            str(feedback.failure_code)
                            if feedback.failure_code is not None
                            else None
                        ),
                        "symbol": feedback.symbol,
                        "interval": feedback.interval,
                        "attempt": feedback.attempt,
                        "max_attempts": feedback.max_attempts,
                        "wait_seconds": feedback.wait_seconds,
                        "active_concurrency": feedback.active_concurrency,
                    }
                    if feedback is not None
                    else None
                ),
            }
        )

    def fallback_consent(offer: object) -> bool:
        _emit(
            {
                "schema_version": "extreme-deviation-worker-v1",
                "type": "fallback",
                "operation_kind": str(getattr(offer, "operation_kind", "extreme_deviation")),
                "failed_symbols": list(getattr(offer, "failed_symbols", ())),
                "intervals": list(getattr(offer, "intervals", ())),
                "failure_codes": [str(item) for item in getattr(offer, "failure_codes", ())],
                "completed": int(getattr(offer, "completed", 0)),
                "total": int(getattr(offer, "total", 0)),
            }
        )
        return sys.stdin.readline().strip().casefold() == "accept"

    try:
        result = application.run_extreme_deviation(
            ExtremeDeviationRequest(
                "",
                tuple(CandleInterval(raw) for raw in args.intervals),
                args.end_date,
                security_id=str(args.security_id),
            ),
            progress=report,
            fallback_consent=(None if args.force_yahoo else fallback_consent),
            force_yahoo=args.force_yahoo,
        )
        payload: dict[str, Any] = {
            "schema_version": "extreme-deviation-worker-v1",
            "type": "result",
            "status": result.status.value,
            "run_id": result.run_id,
            "error_code": result.error_code,
        }
        if result.reliability is not None:
            payload["reliability"] = reliability_payload(result.reliability)
        _emit(payload)
        return 0 if result.run is not None else 69
    except Exception:  # noqa: BLE001 - sanitized process boundary
        _emit(
            {
                "schema_version": "extreme-deviation-worker-v1",
                "type": "error",
                "code": "extreme_deviation_worker_failed",
            }
        )
        return 69
    finally:
        application.close()


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "cli-output-v1",
        "error": {"code": code, "message": message},
    }


def _diagnostics_command(
    args: argparse.Namespace,
    environment: RuntimeEnvironment,
) -> int:
    paths = RuntimePaths.resolve(environment, home=args.home)
    paths.log_root.mkdir(parents=True, exist_ok=True)
    if args.diagnostics_command == "status":
        status = diagnostic_status(paths.log_root)
        _emit(
            {
                "schema_version": "cli-output-v1",
                "diagnostics": {
                    "health": status.health,
                    "file_count": status.file_count,
                    "total_bytes": status.total_bytes,
                    "retention_days": 7,
                    "max_bytes": 100 * 1024 * 1024,
                    "last_event": status.last_event,
                    "warning_count": status.warning_count,
                    "error_count": status.error_count,
                    "stall_count": status.stall_count,
                    "slow_query_count": status.slow_query_count,
                },
            }
        )
        return 0
    if args.diagnostics_command == "export":
        try:
            target = export_diagnostics(
                paths.log_root,
                args.output,
                environment={
                    "app_version": __version__,
                    "environment": environment.value,
                },
            )
        except OSError:
            _emit(
                _error(
                    "DIAGNOSTICS_EXPORT_FAILED",
                    "Unable to write the diagnostics archive.",
                )
            )
            return 74
        _emit(
            {
                "schema_version": "cli-output-v1",
                "diagnostics": {"exported_to": str(target)},
            }
        )
        return 0
    if not args.confirm:
        _emit(
            _error(
                "CONFIRMATION_REQUIRED",
                "Pass --confirm to clear local diagnostic logs.",
            )
        )
        return 64
    try:
        for path in paths.log_root.glob("diagnostics-*.jsonl"):
            path.unlink(missing_ok=True)
    except OSError:
        _emit(
            _error(
                "DIAGNOSTICS_CLEAR_FAILED",
                "Unable to clear local diagnostic logs.",
            )
        )
        return 74
    _emit(
        {
            "schema_version": "cli-output-v1",
            "diagnostics": {"cleared": True},
        }
    )
    return 0


def _turning_backtest_payload(
    report: TurningPointBacktest,
) -> dict[str, Any]:
    return {
        "schema_version": "turning-point-backtest-v1",
        "analysis_type": "turning_point_backtest",
        "provider": {
            "id": report.provider_id,
            "name": report.provider_display_name,
        },
        "end_date": report.requested_end_date.isoformat(),
        "requested_candles": report.requested_count,
        "method": {
            "entry": "next_bar_open",
            "exit": "tenth_bar_close",
            "win": "exit_close_gt_entry_open",
            "overlap": "skip",
            "unsettled": "exclude",
        },
        "results": [
            {
                "symbol": cell.symbol,
                "interval": cell.interval.value,
                "trade_side": cell.trade_side.value,
                "candle_count": cell.candle_count,
                "trades": len(cell.evaluation.trades),
                "wins": cell.evaluation.wins,
                "win_rate": cell.evaluation.win_rate,
                "average_return_5": cell.evaluation.average_return_5,
                "average_return_10": cell.evaluation.average_return_10,
                "average_mfe": cell.evaluation.average_mfe,
                "average_mae": cell.evaluation.average_mae,
                "skipped_overlap": cell.evaluation.skipped_overlap,
                "unsettled": cell.evaluation.unsettled,
                "trade_dates": [
                    {
                        "signal_at": trade.signal_at.isoformat(),
                        "entry_at": trade.entry_at.isoformat(),
                        "exit_at": trade.exit_at.isoformat(),
                        "entry_price": trade.entry_price,
                        "return_5": trade.return_5,
                        "return_10": trade.return_10,
                        "mfe": trade.mfe,
                        "mae": trade.mae,
                        "won": trade.won,
                    }
                    for trade in cell.evaluation.trades
                ],
            }
            for cell in report.cells
        ],
        "errors": [
            {
                "symbol": symbol,
                "interval": interval,
                "reason": reason,
            }
            for symbol, interval, reason in report.errors
        ],
    }


def _service_check(
    name: str,
    result: ServiceTestResult,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": result.ok,
        "code": result.code,
        "details": list(result.details),
    }


def _run_live_smoke(
    environment: RuntimeEnvironment,
    *,
    home: Path,
    symbol: str,
    benchmark: str,
) -> int:
    if environment is not RuntimeEnvironment.PRODUCTION:
        _emit(
            _error(
                "LIVE_SMOKE_PRODUCTION_ONLY",
                "Live smoke is allowed only against the production configuration.",
            )
        )
        return 64
    try:
        application = build_application(
            RuntimeEnvironment.PRODUCTION,
            home=home,
        )
        settings = application.settings()
    except Exception:  # noqa: BLE001 - stable sanitized CLI boundary
        _emit(
            _error(
                "LIVE_CONFIGURATION_UNAVAILABLE",
                "The production configuration could not be loaded.",
            )
        )
        return 78
    if (
        settings.provider_mode not in {"longbridge", "futu"}
        or not settings.provider_configured
        or not settings.ai_configured
    ):
        _emit(
            _error(
                "LIVE_CREDENTIALS_NOT_CONFIGURED",
                "Configure one market-data provider and AI in desktop Settings.",
            )
        )
        return 78
    history_count_before = len(application.list_history())
    try:
        checks = (
            _service_check(
                "provider_profile",
                application.test_provider_connection(),
            ),
            _service_check(
                "market_calendar_and_bars",
                application.test_market_data_connection(
                    symbol,
                    benchmark,
                ),
            ),
            _service_check(
                "turning_point_snapshot_and_candles",
                application.test_turning_point_market_data_connection(symbol),
            ),
            _service_check(
                "extreme_deviation_supported_period_candles",
                application.test_extreme_deviation_market_data_connection(symbol),
            ),
            _service_check(
                "ai_classification",
                application.test_profile_ai_classification(symbol),
            ),
            _service_check(
                "extreme_deviation_ai_report",
                application.test_extreme_deviation_ai_connection(),
            ),
        )
        history_count_after = len(application.list_history())
    except Exception:  # noqa: BLE001 - stable sanitized CLI boundary
        _emit(
            _error(
                "LIVE_SMOKE_FAILED",
                "A live service check failed before producing a safe result.",
            )
        )
        return 69
    history_unchanged = history_count_before == history_count_after
    passed = all(bool(item["ok"]) for item in checks) and history_unchanged
    _emit(
        {
            "schema_version": "cli-output-v1",
            "result": {
                "status": "PASS" if passed else "FAIL",
                "symbol": symbol.strip().upper(),
                "benchmark": benchmark,
                "checks": list(checks),
                "history_count_before": history_count_before,
                "history_count_after": history_count_after,
                "history_unchanged": history_unchanged,
            },
        }
    )
    return 0 if passed else 69


def _run_scenario(
    environment: RuntimeEnvironment,
    *,
    scenario_id: str,
    home: Path,
) -> tuple[int, dict[str, Any]]:
    try:
        ScenarioRunner().validate_environment(environment)
    except PermissionError:
        return (
            64,
            _error(
                "DEVTOOLS_PRODUCTION_FORBIDDEN",
                "Scenario execution is forbidden in production.",
            ),
        )
    try:
        scenario = ScenarioCatalog.bundled().get(scenario_id)
    except ScenarioNotFoundError:
        return 66, _error(
            "SCENARIO_NOT_FOUND",
            "The requested scenario does not exist.",
        )
    try:
        result = ScenarioRunner().run(scenario, home=home)
    except Exception:  # noqa: BLE001 - stable sanitized CLI boundary
        return 70, _error("SCENARIO_FAILED", "Scenario execution failed.")
    return 0, {"schema_version": "cli-output-v1", "result": result}


def _analysis_command(
    args: argparse.Namespace,
    environment: RuntimeEnvironment,
) -> int:
    if args.analysis_command == "list":
        modules = build_analysis_registry().list()
        _emit(
            {
                "schema_version": "cli-output-v1",
                "analyses": [
                    {
                        "id": item.descriptor.analysis_id,
                        "name": item.descriptor.display_name,
                        "version": item.descriptor.version,
                    }
                    for item in modules
                ],
            }
        )
        return 0
    if args.analysis_command == "extreme-deviation":
        if args.deviation_command == "run-worker":
            return _extreme_deviation_worker(args, environment)
        if args.deviation_command == "run" and args.scenario:
            if environment is RuntimeEnvironment.PRODUCTION:
                _emit(
                    _error(
                        "DEVTOOLS_PRODUCTION_FORBIDDEN",
                        "Scenario execution is forbidden in production.",
                    )
                )
                return 64
            application = build_application(
                RuntimeEnvironment.SCENARIO,
                home=args.home,
                scenario_run_id=f"{args.scenario}-{uuid.uuid4()}",
            )
            imported = application.import_securities("IREN, NVDA, AMD")
            pool = application.master_data.create_watchlist("Extreme Deviation Scenario")
            securities = application.master_data.list_securities()
            pool = application.master_data.add_watchlist_members(
                pool.id,
                tuple((item.id, item.bindings[0].id) for item in securities if item.bindings),
            )
            deviation_result = application.run_extreme_deviation(
                ExtremeDeviationRequest(
                    pool.id,
                    EXTREME_DEVIATION_INTERVALS,
                    date(2026, 7, 24),
                )
            )
            deviation_run = deviation_result.run
            _emit(
                {
                    "schema_version": "cli-output-v1",
                    "analysis_type": "extreme_deviation",
                    "scenario": str(args.scenario),
                    "result": {
                        "status": deviation_result.status.value,
                        "run_id": (deviation_run.run_id if deviation_run is not None else None),
                        "imported": imported.success_count,
                        "result_count": (
                            len(deviation_run.results) if deviation_run is not None else 0
                        ),
                        "period_count": (
                            sum(len(item.periods) for item in deviation_run.results)
                            if deviation_run is not None
                            else 0
                        ),
                        "cache_fetched": (
                            deviation_run.fetched if deviation_run is not None else 0
                        ),
                    },
                }
            )
            return 0 if deviation_run is not None else 69
        application = build_application(environment, home=args.home)
        if args.deviation_command == "run":
            if args.watchlist_id is None:
                _emit(
                    _error(
                        "EXTREME_DEVIATION_WATCHLIST_REQUIRED",
                        "Provide --scenario or --watchlist-id.",
                    )
                )
                return 64
            end_date = args.end_date or application.latest_completed_trading_day()
            if end_date is None:
                _emit(
                    _error(
                        "MARKET_CALENDAR_UNAVAILABLE",
                        "The latest completed trading day is unavailable.",
                    )
                )
                return 69
            try:
                intervals = tuple(
                    CandleInterval(item.strip())
                    for item in str(args.intervals).split(",")
                    if item.strip()
                )
            except ValueError:
                _emit(
                    _error(
                        "EXTREME_DEVIATION_INTERVAL_INVALID",
                        "One or more intervals are invalid.",
                    )
                )
                return 64
            if any(item not in EXTREME_DEVIATION_INTERVALS for item in intervals):
                _emit(
                    _error(
                        "EXTREME_DEVIATION_INTERVAL_UNSUPPORTED",
                        "Extreme deviation supports 30m, 60m, 1d, and 1w only.",
                    )
                )
                return 64
            selected = tuple(
                item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()
            )
            deviation_result = application.run_extreme_deviation(
                ExtremeDeviationRequest(
                    str(args.watchlist_id),
                    intervals,
                    end_date,
                    selected,
                )
            )
            deviation_run = deviation_result.run
            _emit(
                {
                    "schema_version": "cli-output-v1",
                    "analysis_type": "extreme_deviation",
                    "result": {
                        "status": deviation_result.status.value,
                        "run_id": (deviation_run.run_id if deviation_run is not None else None),
                        "error_code": deviation_result.error_code,
                        "result_count": (
                            len(deviation_run.results) if deviation_run is not None else 0
                        ),
                        "period_count": (
                            sum(len(item.periods) for item in deviation_run.results)
                            if deviation_run is not None
                            else 0
                        ),
                    },
                }
            )
            return 0 if deviation_run is not None else 69
        if args.deviation_command == "report":
            selected = tuple(
                item.strip().upper() for item in str(args.symbols).split(",") if item.strip()
            )
            try:
                report = application.generate_extreme_deviation_report(
                    str(args.run_id),
                    selected,
                )
            except (KeyError, TypeError, ValueError, RuntimeError) as error:
                _emit(
                    _error(
                        "EXTREME_DEVIATION_REPORT_FAILED",
                        str(error),
                    )
                )
                return 69
            _emit(
                {
                    "schema_version": "cli-output-v1",
                    "analysis_type": "extreme_deviation",
                    "report": {
                        "selected_symbols": list(report.selected_symbols),
                        "model": report.model,
                        "prompt_version": report.prompt_version,
                        "content": report.content,
                        "generated_at": report.generated_at.isoformat(),
                        "input_sha256": report.input_sha256,
                    },
                }
            )
            return 0
        histories = application.list_extreme_deviation_history(limit=args.limit)
        _emit(
            {
                "schema_version": "cli-output-v1",
                "analysis_type": "extreme_deviation",
                "runs": [
                    {
                        "run_id": item["run_id"],
                        "name": item["display_name"],
                        "completed_at": (
                            item["completed_at"].isoformat()
                            if isinstance(item["completed_at"], datetime)
                            else str(item["completed_at"])
                        ),
                    }
                    for item in histories
                ],
            }
        )
        return 0
    if args.analysis_command == "turning-point":
        if args.turning_command == "run-worker":
            return _turning_point_worker(args, environment)
        if args.turning_command == "backtest":
            application = build_application(environment, home=args.home)
            end_date = args.end_date or application.latest_completed_trading_day()
            if end_date is None:
                _emit(
                    _error(
                        "MARKET_CALENDAR_UNAVAILABLE",
                        "The latest completed trading day is unavailable.",
                    )
                )
                return 69
            sides = {
                "left": (TurningPointTradeSide.LEFT_CD,),
                "right": (TurningPointTradeSide.RIGHT_CONFIRMED,),
                "both": (
                    TurningPointTradeSide.LEFT_CD,
                    TurningPointTradeSide.RIGHT_CONFIRMED,
                ),
            }[str(args.trade_side)]
            try:
                backtest = application.backtest_turning_point(
                    tuple(args.symbols or ("IREN", "NVDA", "AMD")),
                    tuple(
                        CandleInterval(str(raw))
                        for raw in (args.intervals or tuple(item.value for item in CandleInterval))
                    ),
                    end_date,
                    count=int(args.count),
                    trade_sides=sides,
                )
            except (RuntimeError, TypeError, ValueError) as error:
                _emit(
                    _error(
                        "TURNING_POINT_BACKTEST_FAILED",
                        str(error),
                    )
                )
                return 69
            payload = _turning_backtest_payload(backtest)
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            _emit(payload)
            return 0
        if args.turning_command == "run" and args.scenario:
            if environment is RuntimeEnvironment.PRODUCTION:
                _emit(
                    _error(
                        "DEVTOOLS_PRODUCTION_FORBIDDEN",
                        "Scenario execution is forbidden in production.",
                    )
                )
                return 64
            application = build_application(
                RuntimeEnvironment.SCENARIO,
                home=args.home,
                scenario_run_id=f"{args.scenario}-{uuid.uuid4()}",
            )
            imported = application.import_securities("IREN, NVDA, AMD, TQQQ, MISSING")
            pool = application.master_data.create_watchlist("Turning Point Scenario")
            securities = application.master_data.list_securities()
            pool = application.master_data.add_watchlist_members(
                pool.id,
                tuple((item.id, item.bindings[0].id) for item in securities if item.bindings),
            )
            tp_result = application.run_turning_point(
                TurningPointRequest(
                    pool.id,
                    (
                        CandleInterval.MIN_30,
                        CandleInterval.MIN_60,
                        CandleInterval.DAY,
                    ),
                    date(2026, 7, 24),
                    trade_side=(
                        TurningPointTradeSide.LEFT_CD
                        if args.trade_side == "left"
                        else TurningPointTradeSide.RIGHT_CONFIRMED
                    ),
                )
            )
            turning_run = tp_result.run
            _emit(
                {
                    "schema_version": "cli-output-v1",
                    "analysis_type": "turning_point",
                    "scenario": str(args.scenario),
                    "result": {
                        "status": tp_result.status.value,
                        "run_id": (turning_run.run_id if turning_run is not None else None),
                        "imported": imported.success_count,
                        "excluded": len(imported.excluded),
                        "unavailable": len(imported.unavailable),
                        "matched_count": (
                            turning_run.matched_count if turning_run is not None else 0
                        ),
                        "intervals": (
                            [interval.value for interval in turning_run.request.intervals]
                            if turning_run is not None
                            else []
                        ),
                        "trade_side": (
                            turning_run.request.trade_side.value
                            if turning_run is not None
                            else None
                        ),
                        "result_count": (
                            len(turning_run.results) if turning_run is not None else 0
                        ),
                    },
                }
            )
            return 0 if turning_run is not None else 69
        application = build_application(environment, home=args.home)
        if args.turning_command == "run":
            if args.watchlist_id is None:
                _emit(
                    _error(
                        "TURNING_POINT_WATCHLIST_REQUIRED",
                        "Provide --scenario or --watchlist-id.",
                    )
                )
                return 64
            end_date = args.end_date or application.latest_completed_trading_day()
            if end_date is None:
                _emit(
                    _error(
                        "MARKET_CALENDAR_UNAVAILABLE",
                        "The latest completed trading day is unavailable.",
                    )
                )
                return 69
            tp_run_result = application.run_turning_point(
                TurningPointRequest(
                    str(args.watchlist_id),
                    tuple(
                        CandleInterval(str(raw))
                        for raw in (
                            args.intervals
                            or (
                                CandleInterval.MIN_30.value,
                                CandleInterval.MIN_60.value,
                                CandleInterval.DAY.value,
                            )
                        )
                    ),
                    end_date,
                    trade_side=(
                        TurningPointTradeSide.LEFT_CD
                        if args.trade_side == "left"
                        else TurningPointTradeSide.RIGHT_CONFIRMED
                    ),
                )
            )
            turning_run = tp_run_result.run
            _emit(
                {
                    "schema_version": "cli-output-v1",
                    "analysis_type": "turning_point",
                    "result": {
                        "status": tp_run_result.status.value,
                        "run_id": (turning_run.run_id if turning_run is not None else None),
                        "error_code": tp_run_result.error_code,
                        "matched_count": (
                            turning_run.matched_count if turning_run is not None else 0
                        ),
                        "intervals": (
                            [interval.value for interval in turning_run.request.intervals]
                            if turning_run is not None
                            else []
                        ),
                        "trade_side": (
                            turning_run.request.trade_side.value
                            if turning_run is not None
                            else None
                        ),
                        "result_count": (
                            len(turning_run.results) if turning_run is not None else 0
                        ),
                    },
                }
            )
            return 0 if turning_run is not None else 69
        tp_histories = application.list_turning_point_history(limit=args.limit)
        _emit(
            {
                "schema_version": "cli-output-v1",
                "analysis_type": "turning_point",
                "runs": [
                    {
                        "run_id": item["run_id"],
                        "name": item["display_name"],
                        "completed_at": (
                            item["completed_at"].isoformat()
                            if isinstance(item["completed_at"], datetime)
                            else str(item["completed_at"])
                        ),
                    }
                    for item in tp_histories
                ],
            }
        )
        return 0
    if args.rs_command == "run-worker":
        return _rs_strength_worker(args, environment)
    if args.rs_command == "run" and args.scenario:
        code, payload = _run_scenario(
            environment,
            scenario_id=str(args.scenario),
            home=args.home,
        )
        _emit(payload)
        return code
    if args.rs_command == "run":
        if args.watchlist_id is None or args.end_date is None:
            _emit(
                _error(
                    "RS_RUN_ARGUMENTS_REQUIRED",
                    "Provide --scenario or both --watchlist-id and --end-date.",
                )
            )
            return 64
        application = build_application(environment, home=args.home)
        result = application.run(
            RunRequest(
                str(args.watchlist_id),
                str(args.benchmark),
                args.end_date,
                tuple(args.ranges or ("3M", "6M", "1Y")),
                None,
            )
        )
        _emit(
            {
                "schema_version": "cli-output-v1",
                "analysis_type": "rs_strength",
                "result": {
                    "status": result.status.value,
                    "run_id": result.run_id,
                    "error_code": result.error_code,
                    "stock_result_count": (
                        len(result.output.stock_results) if result.output is not None else 0
                    ),
                },
            }
        )
        return 0 if result.run_id is not None else 69
    application = build_application(environment, home=args.home)
    rs_histories = application.list_history(limit=args.limit)
    _emit(
        {
            "schema_version": "cli-output-v1",
            "analysis_type": "rs_strength",
            "runs": [
                {
                    "run_id": item.header.run_id,
                    "name": item.header.display_name,
                    "status": item.header.status,
                    "completed_at": item.header.completed_at.isoformat(),
                }
                for item in rs_histories
            ],
        }
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = _ENVIRONMENT_ALIASES[args.env]
    if args.command == "analysis":
        return _analysis_command(args, environment)
    if args.command == "diagnostics":
        return _diagnostics_command(args, environment)
    if args.command == "securities":
        return _security_import_worker(args, environment)
    if args.command == "live-smoke":
        return _run_live_smoke(
            environment,
            home=args.home,
            symbol=args.symbol,
            benchmark=args.benchmark,
        )
    if args.command == "services":
        application = build_application(environment, home=args.home)
        try:
            settings = application.settings()
            if args.service_command == "status":
                _emit(
                    {
                        "schema_version": "cli-output-v1",
                        "services": {
                            "provider": settings.provider_mode,
                            "provider_configured": settings.provider_configured,
                            "ai_configured": settings.ai_configured,
                            "first_run_complete": settings.first_run_complete,
                        },
                    }
                )
                return 0
            provider = args.provider
            if provider == "active":
                provider = settings.provider_mode
            if provider == "futu":
                result = application.quality_futu()
            else:
                result = (
                    application.quality_longbridge(settings.longbridge_client_id)
                    if provider == "longbridge" and settings.longbridge_client_id
                    else application.test_provider_connection()
                )
            _emit(
                {
                    "schema_version": "cli-output-v1",
                    "quality": _service_check("provider", result),
                }
            )
            return 0 if result.ok else 69
        finally:
            application.close()
    catalog = ScenarioCatalog.bundled()

    if args.scenario_command == "list":
        _emit(
            {
                "schema_version": "cli-output-v1",
                "scenarios": [
                    {"id": scenario.id, "title": scenario.title} for scenario in catalog.list()
                ],
            }
        )
        return 0

    if args.scenario_command == "validate":
        try:
            ScenarioRunner().validate_environment(environment)
        except PermissionError:
            _emit(
                _error(
                    "DEVTOOLS_PRODUCTION_FORBIDDEN",
                    "Scenario execution is forbidden in production.",
                )
            )
            return 64
        try:
            scenario = catalog.get(args.scenario_id)
        except ScenarioNotFoundError:
            _emit(_error("SCENARIO_NOT_FOUND", "The requested scenario does not exist."))
            return 66
        _emit(
            {
                "schema_version": "cli-output-v1",
                "result": {"id": scenario.id, "valid": True},
            }
        )
        return 0

    code, payload = _run_scenario(
        environment,
        scenario_id=args.scenario_id,
        home=args.home,
    )
    _emit(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
