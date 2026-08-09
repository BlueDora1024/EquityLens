#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE_APP=${EQUITYLENS_SOURCE_APP:-${STOCK_TOOLBOX_SOURCE_APP:-"$ROOT/dist/EquityLens.app"}}
INSTALL_ROOT=${STOCK_TOOLBOX_INSTALL_ROOT:-"/Applications"}
DESTINATION="$INSTALL_ROOT/EquityLens.app"
OLD_APP="$INSTALL_ROOT/RS Radar.app"
LEGACY_PRODUCT_APP="$INSTALL_ROOT/股票分析百宝箱.app"
SYNC_MARKER=${STOCK_TOOLBOX_SYNC_MARKER:-"$HOME/Library/Application Support/EquityLens/development-auto-sync"}
STAGE="$INSTALL_ROOT/.EquityLens.installing.$$"
BACKUP="$INSTALL_ROOT/.EquityLens.previous.$$"
ENABLE_SYNC=0

case "${1:-}" in
    "")
        ;;
    --enable-sync)
        ENABLE_SYNC=1
        ;;
    --disable-sync)
        rm -f "$SYNC_MARKER"
        echo "EquityLens 自动同步已关闭。"
        exit 0
        ;;
    *)
        echo "usage: $0 [--enable-sync|--disable-sync]" >&2
        exit 2
        ;;
esac

if [ ! -d "$SOURCE_APP" ]; then
    echo "source application does not exist: $SOURCE_APP" >&2
    exit 1
fi

mkdir -p "$INSTALL_ROOT"
rm -rf "$STAGE" "$BACKUP"

cleanup() {
    rm -rf "$STAGE"
}
trap cleanup EXIT HUP INT TERM

/usr/bin/ditto "$SOURCE_APP" "$STAGE"
if [ "${STOCK_TOOLBOX_SKIP_SIGNATURE_VERIFY:-0}" != "1" ]; then
    /usr/bin/codesign --verify --deep --strict --verbose=2 "$STAGE"
fi

if [ -e "$DESTINATION" ]; then
    mv "$DESTINATION" "$BACKUP"
fi
if ! mv "$STAGE" "$DESTINATION"; then
    if [ -e "$BACKUP" ]; then
        mv "$BACKUP" "$DESTINATION"
    fi
    echo "unable to replace installed EquityLens application" >&2
    exit 1
fi

if [ "${STOCK_TOOLBOX_SKIP_SIGNATURE_VERIFY:-0}" != "1" ]; then
    /usr/bin/codesign --verify --deep --strict --verbose=2 "$DESTINATION"
fi
if [ "${STOCK_TOOLBOX_SKIP_BUNDLE_VERIFY:-0}" != "1" ]; then
    "$ROOT/.venv/bin/python" "$ROOT/scripts/verify_bundle.py" "$DESTINATION"
fi

rm -rf "$BACKUP"
rm -rf "$OLD_APP"
rm -rf "$LEGACY_PRODUCT_APP"

if [ "$ENABLE_SYNC" -eq 1 ]; then
    mkdir -p "$(dirname -- "$SYNC_MARKER")"
    : >"$SYNC_MARKER"
fi

echo "Installed EquityLens at $DESTINATION"
