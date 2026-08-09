#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PYTHON=${PYTHON_BIN:-"$ROOT/.venv/bin/python"}
QMLLINT=${QMLLINT_BIN:-"$ROOT/.venv/bin/pyside6-qmllint"}
export QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen}

usage() {
    echo "regression gates:" >&2
    echo "  $0 fast|smoke|batch <rs|turning-point|extreme-deviation|desktop-qml|platform>|full|package|live [symbol] [benchmark]" >&2
    echo "utility:" >&2
    echo "  $0 benchmark" >&2
    exit 2
}

case "${1:-}" in
    fast)
        "$PYTHON" -m pytest -q -m fast
        ;;
    smoke)
        "$PYTHON" -m pytest -q \
            tests/e2e/mock \
            tests/cli \
            tests/qml
        ;;
    batch)
        case "${2:-}" in
            rs)
                "$PYTHON" -m pytest -q \
                    tests/unit/domain/rs \
                    tests/unit/analyses/rs_strength \
                    tests/unit/application/runs \
                    tests/unit/core/market_data \
                    tests/e2e/mock \
                    tests/cli
                ;;
            turning-point)
                "$PYTHON" -m pytest -q \
                    tests/unit/analyses/turning_point \
                    tests/unit/core/market_data \
                    tests/unit/infrastructure/providers \
                    tests/e2e/mock \
                    tests/cli
                ;;
            extreme-deviation)
                "$PYTHON" -m pytest -q \
                    tests/unit/analyses/extreme_deviation \
                    tests/unit/core/market_data \
                    tests/integration/persistence \
                    tests/e2e/mock \
                    tests/cli
                ;;
            desktop-qml)
                "$PYTHON" -m pytest -q \
                    tests/unit/desktop_qml
                "$PYTHON" -m pytest -q \
                    -m "not qml_app" \
                    tests/qml
                "$PYTHON" -m pytest -q \
                    -m qml_app \
                    tests/qml
                ;;
            platform)
                "$PYTHON" -m pytest -q \
                    tests/meta \
                    tests/unit/application \
                    tests/unit/infrastructure \
                    tests/unit/runtime \
                    tests/integration
                "$PYTHON" -m pytest -q \
                    -m "not qml_app" \
                    tests/qml
                "$PYTHON" -m pytest -q \
                    -m qml_app \
                    tests/qml
                ;;
            *)
                usage
                ;;
        esac
        ;;
    full)
        "$PYTHON" -m pytest -q -m "not live and not package" \
            --ignore=tests/qml
        "$PYTHON" -m pytest -q \
            -m "not live and not package and not qml_app" \
            tests/qml
        "$PYTHON" -m pytest -q \
            -m "not live and not package and qml_app" \
            tests/qml
        "$PYTHON" -m ruff check src tests scripts
        "$PYTHON" -m mypy src
        "$QMLLINT" -W 0 \
            -I src/stock_toolbox/desktop_qml/qml \
            src/stock_toolbox/desktop_qml/qml/*.qml \
            src/stock_toolbox/desktop_qml/qml/components/*.qml
        ;;
    benchmark)
        "$PYTHON" -m pytest -q tests/unit/domain/rs/test_benchmark.py
        PYTHONPATH=. "$PYTHON" scripts/benchmark_domain_rs.py
        ;;
    package)
        APP_PATH=${APP_PATH:-"$ROOT/dist/EquityLens.app"} \
            "$ROOT/scripts/run_packaged_acceptance.sh"
        ;;
    live)
        SYMBOL=${2:-IREN.US}
        BENCHMARK=${3:-SPY.US}
        RUN_LIVE_YAHOO=1 RUN_LIVE_FUTU=1 \
            "$PYTHON" -m pytest -q -m live
        "/Applications/EquityLens.app/Contents/MacOS/equitylens-cli" \
            --env production live-smoke \
            --symbol "$SYMBOL" --benchmark "$BENCHMARK" --json
        ;;
    *)
        usage
        ;;
esac
