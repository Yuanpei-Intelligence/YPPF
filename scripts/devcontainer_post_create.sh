#!/usr/bin/env bash
# Dev Container post-create: deps, config, migrate, sample DB import.
set -euo pipefail

cd /workspace

echo '[postCreate] Install optional Dev Container Python packages...'
pip install -r .devcontainer/dev_requirements.txt --resume-retries 5

if [ ! -f config.json ]; then
    echo '[postCreate] Create default config.json for Compose MySQL...'
    bash scripts/default_config.sh
else
    echo '[postCreate] Keep existing config.json.'
fi

echo '[postCreate] Apply migrations...'
python manage.py migrate --noinput

echo '[postCreate] Import repository-root dev_sample.sql (skip if populated)...'
python scripts/import_dev_sample.py

echo '[postCreate] Finished.'
