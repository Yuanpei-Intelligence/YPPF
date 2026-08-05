#!/usr/bin/env bash
# Drop development DB, migrate, and import repository-root dev_sample.sql.
# Manual/destructive reset only. postCreate/postStart use
# scripts/devcontainer_ensure_db.sh and do not call this script.
set -euo pipefail

cd /workspace

# migrate needs boot.config -> ./config.json (gitignored).
if [ ! -f config.json ]; then
    echo '[resetSampleDb] Create default config.json for Compose MySQL...'
    bash scripts/default_config.sh
fi

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_PASSWORD="${DB_PASSWORD:-secret}"
DB_DATABASE="${DB_DATABASE:-yppf}"

echo "[resetSampleDb] Waiting for MySQL at ${DB_HOST}:${DB_PORT} ..."
python - <<'PY'
import os
import sys
import time

import pymysql

host = os.environ.get('DB_HOST', 'mysql')
port = int(os.environ.get('DB_PORT', '3306'))
user = os.environ.get('DB_USER', 'root')
password = os.environ.get('DB_PASSWORD', 'secret')

deadline = time.time() + 120
last_error = None
while time.time() < deadline:
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            connect_timeout=5,
        )
        conn.close()
        print('[resetSampleDb] MySQL is ready.')
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - retry until deadline
        last_error = exc
        time.sleep(2)

print(f'[resetSampleDb] MySQL not ready: {last_error}', file=sys.stderr)
sys.exit(1)
PY

echo "[resetSampleDb] WARNING: Dropping and recreating database '${DB_DATABASE}' ..."
python scripts/import_dev_sample.py --drop-database

echo '[resetSampleDb] Apply migrations...'
python manage.py migrate --noinput

echo '[resetSampleDb] Import repository-root dev_sample.sql...'
python scripts/import_dev_sample.py --force

echo '[resetSampleDb] Verify sample data...'
python - <<'PY'
import os
import sys

import pymysql

conn = pymysql.connect(
    host=os.environ.get('DB_HOST', 'mysql'),
    port=int(os.environ.get('DB_PORT', '3306')),
    user=os.environ.get('DB_USER', 'root'),
    password=os.environ.get('DB_PASSWORD', 'secret'),
    database=os.environ.get('DB_DATABASE', 'yppf'),
)
try:
    with conn.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `generic_user`')
        count = int(cursor.fetchone()[0])
finally:
    conn.close()

if count <= 0:
    print('[resetSampleDb] generic_user is empty after import.', file=sys.stderr)
    sys.exit(1)

print(f'[resetSampleDb] OK: generic_user has {count} row(s).')
PY

echo '[resetSampleDb] Superuser is not created automatically.'
echo '[resetSampleDb] To access /admin/, create one manually, for example:'
echo '[resetSampleDb]   python scripts/create_dev_superuser.py'
echo '[resetSampleDb]   # default: username=admin password=secret'
echo '[resetSampleDb] or:'
echo '[resetSampleDb]   python manage.py createsuperuser'

echo "[resetSampleDb] Finished."
