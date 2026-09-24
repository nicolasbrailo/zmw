#!/usr/bin/bash

set -euo pipefail

THIS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# This script will restart services in order, one by one. This is unnecessary, but it makes startup
# logs easier to follow as it's not full of servies all competing for stdout.

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

# All services use zzmw_lib, so its tests gate restarts too. ZMW_PROJECT_ROOT is injected by install_svc.sh
ZZMW_LIB_DIR="${ZMW_PROJECT_ROOT:?not set, re-run install_svc.sh to set it}/zzmw_lib"
echo "Running unit tests for zzmw_lib..."
if ! output=$(make -C "$ZZMW_LIB_DIR" test 2>&1); then
    echo "$output"
    echo "zzmw_lib has unit test failures, cowardly refusing to restart services"
    exit 1
fi

# Run unit tests before restarting
echo "Running unit tests for services:"
for svc in "${services[@]}"; do
    echo "Running unit tests for $svc..."
    if ! output=$("$THIS_SCRIPT_DIR/$svc/run_unit_tests.sh" 2>&1); then
        echo "$output"
        echo "A service has unit test failures, cowardly refusing to restart services"
        exit 1
    fi
done

echo "Will restart all services, Ctrl-C to cancel. Services: ${services[*]}"
read

# Stop all services together
echo "Stopping all services..."
for svc in "${services[@]}"; do
    sudo systemctl stop "$svc" &
done
wait
sleep 1

# Ensure system monitoring is ready first
echo "Starting zmw_servicemon..."
sudo systemctl start zmw_servicemon
sleep 1

# Start all services except zmw_dashboard and zmw_servicemon
for svc in "${services[@]}"; do
    if [ "$svc" = "zmw_dashboard" ] || [ "$svc" = "zmw_servicemon" ]; then
        continue
    fi
    echo "Starting $svc..."
    sudo systemctl start "$svc"
    # Sleep, but not too much. Services generally come up fast, and if we sleep too
    # much we'll go over the threshold to wait for deps (services will recover fine, but
    # there will be errors on the log).
    # There are 15+ services, so a sleep of 200ms should keep us below the 4/5 threshold
    # before services get impatient.
    sleep .2
done

# The dashboard depends on all other services, bring it up last
echo "Starting zmw_dashboard..."
sudo systemctl start zmw_dashboard

echo "All services restarted"
