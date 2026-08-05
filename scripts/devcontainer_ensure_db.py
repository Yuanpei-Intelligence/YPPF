#!/usr/bin/env python3
"""Ensure the development database is usable without wiping existing data.

- Empty / missing schema: migrate, then import sample dump.
- Already populated: keep data and apply migrations.
- Does not create a Django superuser; print a manual-create hint instead.

Destructive reset remains:
``bash scripts/devcontainer_reset_sample_db.sh``
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pymysql


REPO_ROOT = Path(__file__).resolve().parents[1]


def _db_kwargs(*, with_database: bool = True) -> dict:
    kwargs = {
        'host': os.environ.get('DB_HOST', 'mysql'),
        'port': int(os.environ.get('DB_PORT', '3306')),
        'user': os.environ.get('DB_USER', 'root'),
        'password': os.environ.get('DB_PASSWORD', 'secret'),
        'connect_timeout': 5,
        'charset': 'utf8mb4',
    }
    if with_database:
        kwargs['database'] = os.environ.get('DB_DATABASE', 'yppf')
    return kwargs


def wait_for_mysql(timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    host = _db_kwargs(with_database=False)['host']
    port = _db_kwargs(with_database=False)['port']
    print(f'[ensureDb] Waiting for MySQL at {host}:{port} ...')
    while time.time() < deadline:
        try:
            conn = pymysql.connect(**_db_kwargs(with_database=False))
            conn.close()
            print('[ensureDb] MySQL is ready.')
            return
        except Exception as exc:  # noqa: BLE001 - retry until deadline
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f'MySQL not ready: {last_error}')


def count_generic_users() -> int:
    """Return generic_user count, or 0 if DB/table is missing."""
    try:
        conn = pymysql.connect(**_db_kwargs(with_database=True))
    except pymysql.err.OperationalError as exc:
        if getattr(exc, 'args', (None,))[0] == 1049:
            return 0
        raise
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute('SELECT COUNT(*) FROM `generic_user`')
            except pymysql.err.ProgrammingError:
                return 0
            row = cursor.fetchone()
            return int(row[0]) if row is not None else 0
    finally:
        conn.close()


def run(cmd: list[str]) -> None:
    print(f'[ensureDb] $ {" ".join(cmd)}')
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def verify_sample_db() -> None:
    conn = pymysql.connect(**_db_kwargs(with_database=True))
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM `generic_user`')
            count = int(cursor.fetchone()[0])
    finally:
        conn.close()

    if count <= 0:
        raise RuntimeError('generic_user is empty after import.')
    print(f'[ensureDb] OK: generic_user has {count} row(s).')


def _hint_create_superuser() -> None:
    print('[ensureDb] Superuser is not created automatically.')
    print('[ensureDb] To access /admin/, create one manually, for example:')
    print('[ensureDb]   python scripts/create_dev_superuser.py')
    print('[ensureDb]   # default: username=admin password=secret')
    print('[ensureDb] or:')
    print('[ensureDb]   python manage.py createsuperuser')


def ensure_existing() -> None:
    count = count_generic_users()
    print(f'[ensureDb] Existing database detected ({count} user row(s)).')
    print('[ensureDb] Keeping existing data (no DROP / no sample re-import).')
    print('[ensureDb] To wipe and reload sample data, run:')
    print('[ensureDb]   bash scripts/devcontainer_reset_sample_db.sh')
    print('[ensureDb] Apply pending migrations...')
    run(['python', 'manage.py', 'migrate', '--noinput'])
    _hint_create_superuser()
    print('[ensureDb] Finished (reused existing database).')


def ensure_empty() -> None:
    print('[ensureDb] Empty database detected; importing sample dump...')
    print('[ensureDb] Apply migrations...')
    run(['python', 'manage.py', 'migrate', '--noinput'])
    print('[ensureDb] Import repository-root dev_sample.sql...')
    run(['python', 'scripts/import_dev_sample.py', '--force'])
    print('[ensureDb] Verify sample data...')
    verify_sample_db()
    _hint_create_superuser()
    print('[ensureDb] Finished (initialized from sample dump).')


def main() -> int:
    os.chdir(REPO_ROOT)
    try:
        wait_for_mysql()
        if count_generic_users() > 0:
            ensure_existing()
        else:
            ensure_empty()
    except Exception as exc:
        print(f'[ensureDb] Failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
