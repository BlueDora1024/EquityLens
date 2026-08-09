#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PYTHON=${PYTHON_BIN:-"$ROOT/.venv/bin/python"}
PYINSTALLER=${PYINSTALLER_BIN:-"$ROOT/.venv/bin/pyinstaller"}
APP="$ROOT/dist/EquityLens.app"
TARGET_ARCH=${EQUITYLENS_TARGET_ARCH:-$(uname -m)}
case "$TARGET_ARCH" in
    arm64|x86_64) ;;
    *)
        echo "unsupported build architecture: $TARGET_ARCH" >&2
        exit 2
        ;;
esac
export EQUITYLENS_TARGET_ARCH="$TARGET_ARCH"
VERSION=$("$PYTHON" -c \
    'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["project"]["version"])' \
    "$ROOT/pyproject.toml")

prune_build_artifacts() {
    current_archive="EquityLens-v${VERSION}-${TARGET_ARCH}.zip"
    current_manifest="EquityLens-v${VERSION}-manifest.json"
    find "$ROOT/dist" -maxdepth 1 -type f \
        \( -name 'EquityLens-v*-*.zip' \
        -o -name 'EquityLens-v*-*.zip.sha256' \
        -o -name 'EquityLens-v*-manifest.json' \) \
        ! -name "$current_archive" \
        ! -name "${current_archive}.sha256" \
        ! -name "$current_manifest" \
        -delete
    rm -rf \
        "$ROOT/build/stock-toolbox" \
        "$ROOT/build/stock-toolbox-cli" \
        "$ROOT/build/RSStrength.iconset" \
        "$ROOT/build/StockAnalysisToolbox.iconset" \
        "$ROOT/dist/EquityLens"
    rm -f "$ROOT/dist/equitylens"
}

PYTHON_BIN="$PYTHON" "$ROOT/scripts/test.sh" full
"$PYTHON" "$ROOT/scripts/build_icon.py"

rm -rf "$ROOT/build/stock-toolbox" "$ROOT/build/stock-toolbox-cli"
rm -rf "$ROOT/dist/EquityLens" "$APP"
rm -f "$ROOT/dist/equitylens"

"$PYINSTALLER" --noconfirm --clean \
    --workpath "$ROOT/build/stock-toolbox" \
    --distpath "$ROOT/dist" \
    "$ROOT/packaging/stock-toolbox.spec"
"$PYINSTALLER" --noconfirm --clean \
    --workpath "$ROOT/build/stock-toolbox-cli" \
    --distpath "$ROOT/dist" \
    "$ROOT/packaging/stock-toolbox-cli.spec"

cp "$ROOT/dist/equitylens" "$APP/Contents/MacOS/equitylens-cli"
ln -s "equitylens-cli" "$APP/Contents/MacOS/stock-toolbox"
ln -s "equitylens-cli" "$APP/Contents/MacOS/rs-radar-cli"
chmod 755 "$APP/Contents/MacOS/equitylens-cli"

codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

"$PYTHON" "$ROOT/scripts/verify_bundle.py" --write-manifest "$APP"
APP_PATH="$APP" "$ROOT/scripts/run_packaged_acceptance.sh"

ARCHIVE="$ROOT/dist/EquityLens-v${VERSION}-${TARGET_ARCH}.zip"
rm -f "$ARCHIVE" "$ARCHIVE.sha256"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ARCHIVE"
"$ROOT/scripts/write_sha256.sh" "$ARCHIVE"

SYNC_MARKER=${STOCK_TOOLBOX_SYNC_MARKER:-"$HOME/Library/Application Support/EquityLens/development-auto-sync"}
LEGACY_SYNC_MARKER="$HOME/Library/Application Support/RS Radar/development-auto-sync"
if [ -f "$SYNC_MARKER" ] || [ -f "$LEGACY_SYNC_MARKER" ]; then
    sh "$ROOT/scripts/install_app.sh" --enable-sync
fi

prune_build_artifacts
