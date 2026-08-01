#!/usr/bin/env bash
# Dev Container post-create: deps, config, reset DB + sample import.
set -euo pipefail

cd /workspace

if [ ! -f config.json ]; then
    echo '[postCreate] Create default config.json for Compose MySQL...'
    bash scripts/default_config.sh
else
    echo '[postCreate] Keep existing config.json.'
fi

echo '[postCreate] Reset development database and import sample dump...'
bash scripts/devcontainer_reset_sample_db.sh

echo '[postCreate] Install optional Dev Container Python packages...'
pip install -r .devcontainer/dev_requirements.txt --resume-retries 5

echo '[postCreate] Finished.'
