#!/usr/bin/env bash
# Thin wrapper around scripts/devcontainer_ensure_db.py for Dev Container hooks.
set -euo pipefail
cd /workspace
PYTHONUNBUFFERED=1 python scripts/devcontainer_ensure_db.py
