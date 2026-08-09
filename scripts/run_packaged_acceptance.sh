#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP=${APP_PATH:-"$ROOT/dist/EquityLens.app"}
CLI="$APP/Contents/MacOS/equitylens-cli"
LEGACY_CLI="$APP/Contents/MacOS/rs-radar-cli"
GUI="$APP/Contents/MacOS/EquityLens"
CLI_HOME=
GUI_HOME=
PRODUCTION_HOME=
GUI_PID=
PRODUCTION_PID=
TURNING_JSON=
LEGACY_JSON=

cleanup() {
    status=$?
    trap - EXIT
    if [ -n "$GUI_PID" ]; then
        if kill -0 "$GUI_PID" 2>/dev/null; then
            kill -TERM "$GUI_PID" 2>/dev/null || true
        fi
        wait "$GUI_PID" 2>/dev/null || true
    fi
    if [ -n "$PRODUCTION_PID" ]; then
        if kill -0 "$PRODUCTION_PID" 2>/dev/null; then
            kill -TERM "$PRODUCTION_PID" 2>/dev/null || true
        fi
        wait "$PRODUCTION_PID" 2>/dev/null || true
    fi
    [ -z "$CLI_HOME" ] || rm -rf "$CLI_HOME"
    [ -z "$GUI_HOME" ] || rm -rf "$GUI_HOME"
    [ -z "$PRODUCTION_HOME" ] || rm -rf "$PRODUCTION_HOME"
    [ -z "$TURNING_JSON" ] || rm -f "$TURNING_JSON"
    [ -z "$LEGACY_JSON" ] || rm -f "$LEGACY_JSON"
    rm -f \
        /tmp/stock-toolbox-turning-point.json \
        /tmp/stock-toolbox-legacy-cli.json
    exit "$status"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

"$ROOT/.venv/bin/python" "$ROOT/scripts/verify_bundle.py" "$APP"

CLI_HOME=$(mktemp -d /tmp/stock-toolbox-packaged-cli.XXXXXX)
TURNING_JSON=$(mktemp /tmp/stock-toolbox-turning-point.XXXXXX)
LEGACY_JSON=$(mktemp /tmp/stock-toolbox-legacy-cli.XXXXXX)
(
    cd /tmp
    "$CLI" --env dev --home "$CLI_HOME" \
        analysis rs-strength run --scenario full-workflow --json
)
CLI_DB=$(find "$CLI_HOME" -name RSRadar.scenario.sqlite3 -type f | head -1)
[ "$(sqlite3 "$CLI_DB" 'PRAGMA quick_check;')" = "ok" ]
[ "$(sqlite3 "$CLI_DB" \
    "SELECT count(*) FROM analysis_runs WHERE analysis_type='rs_strength';")" = "1" ]
for name in full-workflow.json full-workflow.md full-workflow.zip; do
    [ "$(find "$CLI_HOME" -name "$name" -type f | wc -l | tr -d ' ')" = "1" ]
done
(
    cd /tmp
    "$CLI" --env scenario --home "$CLI_HOME" \
        analysis turning-point run --scenario turning-point-full --json \
        >"$TURNING_JSON"
)
"$ROOT/.venv/bin/python" -m json.tool "$TURNING_JSON" >/dev/null
grep -q '"matched_count":' "$TURNING_JSON"
(
    cd /tmp
    "$LEGACY_CLI" --env dev --home "$CLI_HOME" scenario list --json \
        >"$LEGACY_JSON"
)
"$ROOT/.venv/bin/python" -m json.tool "$LEGACY_JSON" >/dev/null

GUI_HOME=$(mktemp -d /tmp/stock-toolbox-packaged-gui.XXXXXX)
GUI_LOG="$GUI_HOME/gui.log"
(
    cd /tmp
    HOME="$GUI_HOME" QT_QPA_PLATFORM=offscreen \
        exec "$GUI" --env scenario --scenario-run-id packaged-gui \
        >"$GUI_LOG" 2>&1
) &
GUI_PID=$!
sleep 4
kill -0 "$GUI_PID"
[ "${PACKAGED_ACCEPTANCE_FORCE_FAILURE_AFTER_GUI_START:-0}" != "1" ] || false
GUI_DB=$(find "$GUI_HOME" -name RSRadar.scenario.sqlite3 -type f | head -1)
[ "$(sqlite3 "$GUI_DB" 'PRAGMA quick_check;')" = "ok" ]

# A downloaded release must start with an empty production profile, even on a
# machine that still has data from an older product name.
PRODUCTION_HOME=$(mktemp -d /tmp/equitylens-packaged-production.XXXXXX)
PRODUCTION_LOG="$PRODUCTION_HOME/gui.log"
(
    cd /tmp
    HOME="$PRODUCTION_HOME" QT_QPA_PLATFORM=offscreen \
        exec "$GUI" --env production >"$PRODUCTION_LOG" 2>&1
) &
PRODUCTION_PID=$!
sleep 4
kill -0 "$PRODUCTION_PID"
kill -TERM "$PRODUCTION_PID" 2>/dev/null || true
wait "$PRODUCTION_PID" 2>/dev/null || true
PRODUCTION_PID=
PRODUCTION_DB="$PRODUCTION_HOME/Library/Application Support/EquityLens/RSRadar.sqlite3"
PRODUCTION_CONFIG_DB="$PRODUCTION_HOME/Library/Application Support/EquityLens/RSRadar.config.sqlite3"
[ -f "$PRODUCTION_DB" ]
[ -f "$PRODUCTION_CONFIG_DB" ]
[ "$(sqlite3 "$PRODUCTION_DB" 'PRAGMA quick_check;')" = "ok" ]
for table in global_securities classifications calculation_watchlists analysis_runs; do
    [ "$(sqlite3 "$PRODUCTION_DB" "SELECT count(*) FROM $table;")" = "0" ]
done
[ "$(sqlite3 "$PRODUCTION_CONFIG_DB" 'SELECT count(*) FROM global_ai_configuration;')" = "0" ]
[ ! -e "$PRODUCTION_HOME/Library/Application Support/Stock Analysis Toolbox" ]
[ ! -e "$PRODUCTION_HOME/Library/Application Support/RS Radar" ]

printf 'packaged_acceptance=passed\n'
