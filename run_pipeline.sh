#!/usr/bin/env bash
# Continuous evaluation loop: fetch batch -> GROBID -> compare -> stats. Runs until
# `touch STOP` (checked between stages), SIGTERM, or the OpenAlex cursor is exhausted.
# Typical start:  nohup ./run_pipeline.sh >> pipeline.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")"
source ./config.env
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="python3"

stopped() { [ -f STOP ] && echo "[pipeline] STOP sentinel found, exiting" && return 0 || return 1; }

echo "[pipeline] starting at $(date -u +%FT%TZ) (batch=$BATCH_SIZE workers=$WORKERS keep_pdfs=$KEEP_PDFS)"
while true; do
    stopped && exit 0
    "$PY" fetch_openalex_pdfs.py
    rc=$?
    if [ $rc -eq 3 ]; then echo "[pipeline] OpenAlex cursor exhausted, done"; exit 0; fi
    if [ $rc -ne 0 ]; then echo "[pipeline] fetch failed (rc=$rc), retrying in 300s"; sleep 300; continue; fi

    stopped && exit 0
    if ! curl -sf -m 5 "$GROBID_URL/api/isalive" >/dev/null; then
        echo "[pipeline] GROBID not responding, trying to (re)start it"
        ./run_server.sh || { echo "[pipeline] server restart failed, retrying in 300s"; sleep 300; continue; }
    fi
    "$PY" run_grobid.py || { echo "[pipeline] grobid stage failed, retrying in 300s"; sleep 300; continue; }

    stopped && exit 0
    "$PY" compare_grobid_openalex.py && "$PY" update_stats.py
    echo "[pipeline] batch complete at $(date -u +%FT%TZ)"
done
