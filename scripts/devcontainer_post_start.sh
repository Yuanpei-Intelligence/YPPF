#!/usr/bin/env bash
# Dev Container post-start: ensure sample DB if this container never reset it.
#
# postCreateCommand is skipped by some rebuild/restart paths. A container-local
# marker in /tmp is cleared when the app container is recreated, so rebuild
# still wipes and re-imports even when postCreate did not run. Plain restart
# keeps /tmp and therefore keeps existing data.
set -euo pipefail

cd /workspace

MARKER="${YPPF_SAMPLE_DB_MARKER:-/tmp/yppf_sample_db.initialized}"

if [ -f "$MARKER" ]; then
    echo "[postStart] Sample DB already initialized for this container (${MARKER}); skip."
    exit 0
fi

echo '[postStart] Sample DB marker missing; resetting and importing sample dump...'
echo '[postStart] WARNING: Existing yppf data will be wiped.'
bash scripts/devcontainer_reset_sample_db.sh

echo '[postStart] Finished.'
