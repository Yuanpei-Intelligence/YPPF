#!/usr/bin/env bash
# Dev Container post-create: deps, config, ensure DB (keep existing).
set -euo pipefail

cd /workspace

if [ ! -f config.json ]; then
    echo '[postCreate] Create default config.json for Compose MySQL...'
    bash scripts/default_config.sh
else
    echo '[postCreate] Keep existing config.json.'
fi

echo '[postCreate] Ensure development database (keep existing if present)...'
bash scripts/devcontainer_ensure_db.sh

echo '[postCreate] Install optional Dev Container Python packages...'
pip install -r .devcontainer/dev_requirements.txt --resume-retries 5

echo '[postCreate] Finished.'
