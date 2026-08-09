#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "${PYTHON_BIN:-}" ]; then
    PYTHON=$PYTHON_BIN
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    GIT_COMMON=$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || true)
    SHARED_VENV=$(dirname "$GIT_COMMON")/.venv/bin/python
    if [ -n "$GIT_COMMON" ] && [ -x "$SHARED_VENV" ]; then
        PYTHON=$SHARED_VENV
    else
        PYTHON=python3
    fi
fi
TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/stock-toolbox-scenarios.XXXXXX")
trap 'rm -rf "$TEMP_ROOT"' EXIT HUP INT TERM

list_scenarios() {
    printf '%s\n' \
        timeout-recovery \
        repeated-429 \
        auth-fatal \
        quota-fatal \
        exactly-80-partial \
        below-80-failure \
        database-busy \
        disk-blocked \
        user-cancel \
        ai-old-report
}

run_scenario() {
    scenario_id=$1
    PYTHONPATH="$ROOT/src" "$PYTHON" -m stock_toolbox.cli \
        --env scenario \
        --home "$TEMP_ROOT/$scenario_id" \
        scenario run "$scenario_id" --json
}

case "${1:-}" in
    --list)
        list_scenarios
        ;;
    all)
        list_scenarios | while IFS= read -r scenario_id; do
            run_scenario "$scenario_id"
        done
        ;;
    timeout-recovery|repeated-429|auth-fatal|quota-fatal|exactly-80-partial|below-80-failure|database-busy|disk-blocked|user-cancel|ai-old-report)
        run_scenario "$1"
        ;;
    *)
        echo "usage: $0 --list|all|$(list_scenarios | paste -sd '|' -)" >&2
        exit 2
        ;;
esac
