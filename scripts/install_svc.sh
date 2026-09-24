#!/usr/bin/bash

set -euo pipefail

if [ -z "${1+x}" ]; then
  echo "Missing arg: target service path"
  exit 1
fi

SRC_ROOT=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ZMW_PROJECT_ROOT=$( dirname "$SRC_ROOT" )
TGT_SVC_SRC=$( readlink -f "$1" )
TGT_SVC_NAME=$( basename "$TGT_SVC_SRC" )
SVC_RUN_BASE="/home/$USER/run/baticasa"
TGT_SVC_RUN="$SVC_RUN_BASE/$TGT_SVC_NAME"

if [ -z "${2+x}" ]; then
  EXEC_START="pipenv run python3 $TGT_SVC_SRC/$TGT_SVC_NAME.py"
else
  EXEC_START="$2 pipenv run python3 $TGT_SVC_SRC/$TGT_SVC_NAME.py"
fi

echo "Installing service $TGT_SVC_NAME from $TGT_SVC_SRC"

function ensure_file() {
  FN="$1"
  if [ ! -f "$TGT_SVC_SRC/$FN" ]; then
    echo "$TGT_SVC_SRC doesn't look like a service, no $FN found"
    exit 1
  fi
}

ensure_file "$TGT_SVC_NAME.py"
ensure_file Pipfile.lock
ensure_file Pipfile

make -C "$TGT_SVC_SRC" test

# Check if this service already exists
if [ -f "$TGT_SVC_RUN/stop.sh" ]; then
  echo "Service $TGT_SVC_NAME already exists, stopping old service first..."
  "$TGT_SVC_RUN/stop.sh"
fi

# Create target run dir and its virtual env
mkdir -p "$TGT_SVC_RUN"

if [ -f "$TGT_SVC_RUN/config.json" ]; then
  echo "$TGT_SVC_SRC already has a config.json file, will not create new one"
elif [ ! -f "$TGT_SVC_SRC/config.json" ] && [ -f "$TGT_SVC_SRC/config.template.json" ]; then
  echo "$TGT_SVC_SRC doesn't have a config.json file, create one from the template"
  exit 1
elif [ ! -f "$TGT_SVC_SRC/config.json" ] && [ ! -f "$TGT_SVC_SRC/config.template.json" ]; then
  echo "$TGT_SVC_SRC doesn't have configs, assuming it doesn't need one"
else
  mv "$TGT_SVC_SRC/config.json" "$TGT_SVC_RUN/config.json"
fi

pushd "$TGT_SVC_RUN"
cp "$TGT_SVC_SRC/Pipfile" .
cp "$TGT_SVC_SRC/Pipfile.lock" .

PIPENV_VENV_IN_PROJECT=1 pipenv sync
popd

read -r -d '' SVC_TMPL <<EOF || true
[Unit]
Description=$TGT_SVC_NAME
After=mosquitto.target
Wants=mosquitto.target

[Service]
ExecStartPre=/usr/bin/mkdir -m 740 -p "$TGT_SVC_RUN"
Environment=
ExecStart=$EXEC_START
WorkingDirectory=/home/$USER/run/baticasa/$TGT_SVC_NAME
Restart=always
RestartSec=10s
User=$USER

[Install]
WantedBy=multi-user.target
EOF

read -r -d '' RESTART_AND_LOGS_TMPL <<EOF || true
  set -euo pipefail
  SCRIPT_DIR="\$(cd -- "\$(dirname -- "\${BASH_SOURCE[0]}")" && pwd)"
  # Run tests for this service on restart. Because of set -e, this will prevent restart if test fails
  make -C "$TGT_SVC_SRC" test
  sudo systemctl restart '$TGT_SVC_NAME' && "\$SCRIPT_DIR/logs.sh"
EOF

echo "$SVC_TMPL" > "$TGT_SVC_RUN/$TGT_SVC_NAME.service"
echo "$RESTART_AND_LOGS_TMPL" > "$TGT_SVC_RUN/restart_and_logs.sh"
chmod +x "$TGT_SVC_RUN/restart_and_logs.sh"
echo "make -C '$TGT_SVC_SRC' test" > "$TGT_SVC_RUN/run_unit_tests.sh"
chmod +x "$TGT_SVC_RUN/run_unit_tests.sh"
echo "sudo systemctl stop '$TGT_SVC_NAME'" > "$TGT_SVC_RUN/stop.sh"
chmod +x "$TGT_SVC_RUN/stop.sh"
echo "sudo systemctl start '$TGT_SVC_NAME'" > "$TGT_SVC_RUN/start.sh"
chmod +x "$TGT_SVC_RUN/start.sh"
cp "$SRC_ROOT/journal_parse.jq" "$SVC_RUN_BASE/journal_parse.jq"
echo "journalctl --follow --output=json --unit '$TGT_SVC_NAME' | jq --arg basepath '$ZMW_PROJECT_ROOT' -r -f '$SVC_RUN_BASE/journal_parse.jq'" > "$TGT_SVC_RUN/logs.sh"
chmod +x "$TGT_SVC_RUN/logs.sh"
cp "$SRC_ROOT/use_https_here.sh" "$TGT_SVC_RUN/use_https_here.sh"
chmod +x "$TGT_SVC_RUN/use_https_here.sh"
cp "$SRC_ROOT/config_apply.py" "$SRC_ROOT/config_merge.py" "$SRC_ROOT/logs.sh" "$SRC_ROOT/services_status.sh" "$SRC_ROOT/restart_all.sh" "$SVC_RUN_BASE/"
chmod +x "$SVC_RUN_BASE/"*.sh

# Add a variable to logs.sh to let it know where the project root is, so that jq can print journal logs and strip the full path
sed -i "2i ZMW_PROJECT_ROOT='$ZMW_PROJECT_ROOT'" "$SVC_RUN_BASE/logs.sh"
# Same for restart_all.sh, so it can find and run the zzmw_lib tests
sed -i "2i ZMW_PROJECT_ROOT='$ZMW_PROJECT_ROOT'" "$SVC_RUN_BASE/restart_all.sh"

if [ ! -f "/etc/systemd/system/$TGT_SVC_NAME.service" ]; then
  sudo ln -s "$TGT_SVC_RUN/$TGT_SVC_NAME.service" "/etc/systemd/system/$TGT_SVC_NAME.service" || true
fi
sudo systemctl daemon-reload

sudo systemctl enable "$TGT_SVC_NAME"
sudo systemctl start "$TGT_SVC_NAME"

