#!/usr/bin/bash

set -euo pipefail

THIS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
PROJECT_DIR=$(dirname "$THIS_SCRIPT_DIR")

# Update each service's README.md with MQTT section from get_mqtt_description()
echo "Updating service READMEs with MQTT sections..."
python3 "$THIS_SCRIPT_DIR/update_readme_mqtt.py"
echo ""

READMES=$(ls "$PROJECT_DIR"/zmw_*/README.md)

if [[ ! -f "$PROJECT_DIR/README.md" ]]; then
    echo "ERROR: README.md not found in $PROJECT_DIR"
    exit 1
fi

AUTO_GEN_CONTENT_SEP_LN=$(grep -n "^# Supported Services$" "$PROJECT_DIR/README.md" | cut -d: -f1)
if [[ -z "$AUTO_GEN_CONTENT_SEP_LN" ]]; then
    echo "Can't parse README.md"
    exit 1
fi
echo "This script will remove all content after line $AUTO_GEN_CONTENT_SEP_LN. Are you sure?"
read

# Truncate README.md after the separator line
head -n "$AUTO_GEN_CONTENT_SEP_LN" "$PROJECT_DIR/README.md" > "$PROJECT_DIR/README.md.tmp"

# Append each readme with fixed image paths
for readme in $READMES; do
    subdir=$(basename "$(dirname "$readme")")
    echo "" >> "$PROJECT_DIR/README.md.tmp"
    # Fix relative image paths: ![...](path) -> ![...](subdir/path)
    # Preserves absolute URLs (http://, https://), absolute paths (/), and anchors (#)
    sed -e "s|](\./|]($subdir/|g" \
        -e "s|](http://|](__HTTP__|g" \
        -e "s|](https://|](__HTTPS__|g" \
        -e "s|](/|](__ABS__|g" \
        -e "s|](#|](__ANCHOR__|g" \
        -e "s|](\([^_)]\)|]($subdir/\1|g" \
        -e "s|__HTTP__|http://|g" \
        -e "s|__HTTPS__|https://|g" \
        -e "s|__ABS__|/|g" \
        -e "s|__ANCHOR__|#|g" \
        "$readme" >> "$PROJECT_DIR/README.md.tmp"
done

# Replace original with updated version
mv "$PROJECT_DIR/README.md.tmp" "$PROJECT_DIR/README.md"

echo "README.md updated successfully"
