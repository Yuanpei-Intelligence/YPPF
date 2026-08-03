#!/usr/bin/env bash
# Dev Container post-start: ensure DB without wiping existing data.
#
# Some rebuild paths skip postCreate; postStart still runs ensure logic.
# Existing populated databases are kept; empty databases get sample import.
# Destructive reset: bash scripts/devcontainer_reset_sample_db.sh
set -euo pipefail

cd /workspace

# Mirror postCreate: migrate/import need config.json (gitignored).
if [ ! -f config.json ]; then
    echo '[postStart] Create default config.json for Compose MySQL...'
    bash scripts/default_config.sh
else
    echo '[postStart] Keep existing config.json.'
fi

echo '[postStart] Ensure development database (keep existing if present)...'
bash scripts/devcontainer_ensure_db.sh

echo '[postStart] Finished.'
