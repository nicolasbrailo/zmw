#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

for dir in "$REPO_DIR"/zmw_*/; do
    [ -f "$dir/Makefile" ] || continue
    pushd "$dir"
    make rebuild_deps
    make install_svc
    popd
done
