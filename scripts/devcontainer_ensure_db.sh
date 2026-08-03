#!/usr/bin/env bash
# Thin wrapper around scripts/devcontainer_ensure_db.py for Dev Container hooks.
set -euo pipefail
cd /workspace

# migrate needs boot.config -> ./config.json (gitignored).
if [ ! -f config.json ]; then
    echo '[ensureDb] Create default config.json for Compose MySQL...'
    bash scripts/default_config.sh
fi

PYTHONUNBUFFERED=1 python scripts/devcontainer_ensure_db.py
