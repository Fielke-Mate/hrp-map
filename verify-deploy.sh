#!/usr/bin/env bash
# Confirm what is actually SERVED, not what the Pages status API claims.
#
# The legacy Pages build reported "building" for ~10 minutes after a deploy had
# already gone live, so status is not a reliable signal. This fetches the real
# file with a cache-buster and checks a marker string from the local copy.
set -u
URL="https://fielke-mate.github.io/hrp-map/index.html"
MARKER="${1:-$(grep -o 'const TRACK=\[[^,]*,[^,]*,' index.html | head -1)}"
for i in $(seq 1 40); do
  BODY=$(curl -sS "${URL}?cb=$(date +%s)" 2>/dev/null || true)
  if [ -n "$BODY" ] && printf '%s' "$BODY" | grep -qF "$MARKER"; then
    echo "live after $((i*15))s  ($(printf '%s' "$BODY" | wc -c) bytes)"
    exit 0
  fi
  sleep 15
done
echo "not live after 10 minutes"; exit 1
