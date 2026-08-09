#!/bin/sh
set -eu

ARCHIVE=$1
DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$ARCHIVE")" && pwd)
FILENAME=$(basename -- "$ARCHIVE")
(
    cd "$DIRECTORY"
    shasum -a 256 "$FILENAME" >"$FILENAME.sha256"
)
