#!/usr/bin/bash

set -euo pipefail

THIS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Find all directories containing a service file of the same name
services=()
for dir in "$THIS_SCRIPT_DIR"/*/; do
    name="$(basename $dir)"
    if [ -f "${dir}${name}.service" ]; then
        services+=("$name")
    fi
done

if [ ${#services[@]} -eq 0 ]; then
    echo "No services found"
    exit 1
fi

# Build -u flags for each service
unit_args=()
for svc in "${services[@]}"; do
    unit_args+=("-u" "$svc")
done

# 'werkzeug/_internal.py:97' -> Filter out GET logs from flask
journalctl --follow --output=json "${unit_args[@]}" | \
  jq --arg basepath "$ZMW_PROJECT_ROOT" -r -f "$THIS_SCRIPT_DIR/journal_parse.jq" | \
  egrep -v 'werkzeug/_internal.py:97'
