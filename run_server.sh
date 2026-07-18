#!/usr/bin/env bash
# Start the GROBID server in the background (nohup + pidfile) and wait until healthy.
# Usage: ./run_server.sh [stop]
set -euo pipefail
cd "$(dirname "$0")"
source ./config.env
PIDFILE="grobid-server.pid"
LOG="grobid-server.log"

if [ "${1:-}" = "stop" ]; then
    if [ -f "$PIDFILE" ]; then
        PGID=$(ps -o pgid= -p "$(cat "$PIDFILE")" 2>/dev/null | tr -d ' ' || true)
        [ -n "${PGID:-}" ] && kill -TERM -- "-$PGID" 2>/dev/null || true
        rm -f "$PIDFILE"
        echo "server stopped"
    else
        echo "no pidfile; nothing to stop"
    fi
    exit 0
fi

if curl -sf -m 2 "$GROBID_URL/api/isalive" >/dev/null 2>&1; then
    echo "GROBID already running at $GROBID_URL"
    exit 0
fi

( cd "$GROBID_HOME_DIR" && setsid nohup ./gradlew run --no-daemon > "$OLDPWD/$LOG" 2>&1 & echo $! > "$OLDPWD/$PIDFILE" )
echo "starting GROBID (pid $(cat "$PIDFILE"), log $LOG)..."
for i in $(seq 1 90); do
    if curl -sf -m 2 "$GROBID_URL/api/isalive" >/dev/null 2>&1; then
        echo "GROBID is up at $GROBID_URL"
        exit 0
    fi
    sleep 10
done
echo "ERROR: GROBID did not come up within 15 min — check $LOG" >&2
exit 1
