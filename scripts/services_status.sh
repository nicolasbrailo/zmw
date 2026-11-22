#!/usr/bin/bash

set -euo pipefail

# Same as install_svc.sh
SVC_RUN_BASE="${SVC_RUN_BASE:-/home/$USER/run/baticasa}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'  # No Color

function check_svc_status() {
  SVCS="$@"
  for SVC in $SVCS; do
    RUNNING=$( systemctl show "$SVC" -pActiveState,SubState --value | paste -sd ' ' - )
    TS=$( systemctl show "$SVC" -pActiveEnterTimestamp --value | paste -sd ' ' - )
    MPID=$( systemctl show "$SVC" -pMainPID --value | paste -sd ' ' - )

    if [[ "$RUNNING" == *running* ]]; then
      COLOR="$GREEN"
    elif [[ "$RUNNING" == *dead* ]]; then
      COLOR="$RED"
    else
      COLOR="$NC"
    fi

    printf "$COLOR$SVC\t$RUNNING$NC\tpid=$MPID\t$TS\n"
  done | column -t
}

# Find services by their WorkingDirectory (install_svc.sh sets it to the service's run dir) instead of scanning the
# run dirs, so this works from a sandbox that can't see them (eg servicemon)
services=()
while read -r name; do
    services+=("$name")
done < <(systemctl list-unit-files --type=service --no-legend --plain | cut -d' ' -f1 | grep -v '@' |
         xargs systemctl show -p Id -p WorkingDirectory | paste -d' ' - - - |
         sed -n "s|^Id=\(.*\)\.service WorkingDirectory=$SVC_RUN_BASE/.*|\1|p" | sort)

check_svc_status "${services[@]}"

