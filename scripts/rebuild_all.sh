#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Optional: resume from a given service, e.g. ./rebuild_all.sh zmw_homeboard
# Skips every service alphabetically before it (glob order is sorted).
START="${1:-}"
started=1
[ -n "$START" ] && started=0

for dir in "$REPO_DIR"/zmw_*/; do
    [ -f "$dir/Makefile" ] || continue
    if [ "$started" -eq 0 ]; then
        [ "$(basename "$dir")" = "$START" ] && started=1 || continue
    fi
    pushd "$dir"
    make rebuild_deps
    make install_svc
    popd
done

if [ "$started" -eq 0 ]; then
    echo "ERROR: start service '$START' not found; nothing was rebuilt" >&2
    exit 1
fi
