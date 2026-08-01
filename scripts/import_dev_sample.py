#!/usr/bin/env python3
"""Import repository-root ``dev_sample.sql`` into the development database.

Intended for Dev Container post-create and manual local setup. Expects schema
to already exist (run ``python manage.py migrate`` first). By default skips
import when ``generic_user`` already has rows; pass ``--force`` to reload.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pymysql


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL = REPO_ROOT / 'dev_sample.sql'


def _split_sql_statements(sql: str) -> list[str]:
    """Split a MySQL dump into executable statements.

    Handles ``--`` line comments and single-quoted string literals with
    backslash or doubled-quote escapes. Does not support delimiter changes.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    in_string = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ''

        if not in_string and ch == '-' and nxt == '-':
            # Line comment: skip to end of line.
            while i < n and sql[i] != '\n':
                i += 1
            continue

        if not in_string and ch == '#':
            while i < n and sql[i] != '\n':
                i += 1
            continue

        if ch == "'" and not in_string:
            in_string = True
            buf.append(ch)
            i += 1
            continue

        if in_string:
            buf.append(ch)
            if ch == '\\' and i + 1 < n:
                buf.append(sql[i + 1])
                i += 2
                continue
            if ch == "'" and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_string = False
            i += 1
            continue

        if ch == ';':
            statement = ''.join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    trailing = ''.join(buf).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _connect(args: argparse.Namespace) -> pymysql.Connection:
    return pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        charset='utf8mb4',
        autocommit=False,
    )


def _user_count(conn: pymysql.Connection) -> int | None:
    with conn.cursor() as cursor:
        try:
            cursor.execute('SELECT COUNT(*) FROM `generic_user`')
        except pymysql.err.ProgrammingError:
            return None
        row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def import_sql(conn: pymysql.Connection, sql_path: Path) -> int:
    sql = sql_path.read_text(encoding='utf-8')
    statements = _split_sql_statements(sql)
    executed = 0
    with conn.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
            executed += 1
    conn.commit()
    return executed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Import root-level dev_sample.sql into MySQL.',
    )
    parser.add_argument(
        '--sql',
        type=Path,
        default=DEFAULT_SQL,
        help=f'SQL file path (default: {DEFAULT_SQL})',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Import even when generic_user already has rows.',
    )
    parser.add_argument(
        '--host',
        default=os.getenv('DB_HOST', 'mysql'),
    )
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.getenv('DB_PORT', '3306')),
    )
    parser.add_argument(
        '--user',
        default=os.getenv('DB_USER', 'root'),
    )
    parser.add_argument(
        '--password',
        default=os.getenv('DB_PASSWORD', 'secret'),
    )
    parser.add_argument(
        '--database',
        default=os.getenv('DB_DATABASE', 'yppf'),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sql_path: Path = args.sql.resolve()

    if not sql_path.is_file():
        print(f'[import_dev_sample] SQL file not found: {sql_path}', file=sys.stderr)
        return 1

    print(f'[import_dev_sample] Connecting to '
          f'{args.user}@{args.host}:{args.port}/{args.database}')
    conn = _connect(args)
    try:
        count = _user_count(conn)
        if count is None:
            print(
                '[import_dev_sample] Table generic_user missing; '
                'run migrate before import.',
                file=sys.stderr,
            )
            return 1
        if count > 0 and not args.force:
            print(
                f'[import_dev_sample] Skip import: generic_user already '
                f'has {count} row(s). Use --force to reload.',
            )
            return 0

        print(f'[import_dev_sample] Importing {sql_path} ...')
        executed = import_sql(conn, sql_path)
        print(f'[import_dev_sample] Done ({executed} statements).')
        print('[import_dev_sample] Sample login: username like S000001, '
              'password test')
        return 0
    except Exception as exc:
        conn.rollback()
        print(f'[import_dev_sample] Failed: {exc}', file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
