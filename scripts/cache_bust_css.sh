#!/bin/bash
# Stylesheets are served with a long max-age under fixed names, so browsers keep stale css after a deploy. Append
# ?v=<hash of the file> to every local href="/x.css" in the service's html files. Each file is looked up in the
# service's www dir first, then in the shared lib's www (zmw.css: run `make -C zzmw_lib/www css` first if it changed).
#
# Usage: cache_bust_css.sh <service www dir> <zzmw_lib www dir>
set -euo pipefail

WWW_DIR="$1"
LIB_WWW_DIR="$2"

for html in "$WWW_DIR"/*.html; do
  for css in $(grep -o 'href="/[^"?]*\.css' "$html" | sed 's|href="/||' | sort -u); do
    src=""
    if [ -f "$WWW_DIR/$css" ]; then
      src="$WWW_DIR/$css"
    elif [ -f "$LIB_WWW_DIR/$css" ]; then
      src="$LIB_WWW_DIR/$css"
    fi
    [ -n "$src" ] || continue
    hash=$(md5sum "$src" | cut -d' ' -f1 | head -c8)
    echo "Updating $html: /$css?v=$hash"
    sed -i "s|href=\"/$css[^\"]*\"|href=\"/$css?v=$hash\"|g" "$html"
  done
done
