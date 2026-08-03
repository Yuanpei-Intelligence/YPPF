#!/usr/bin/env python3
"""Import repository-root ``dev_sample.sql`` into the development database.

Intended for Dev Container post-create and manual local setup. Expects schema
to already exist (run ``python manage.py migrate`` first) before importing.

By default skips import when ``generic_user`` already has rows. Pass
``--force`` to truncate tables present in the dump and reload. Pass
``--drop-database`` alone to DROP and recreate the target database (then
migrate before importing).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Sequence

import pymysql


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL = REPO_ROOT / 'dev_sample.sql'
_DB_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
_INSERT_TABLE_RE = re.compile(
    r'^\s*INSERT\s+INTO\s+`([^`]+)`',
    re.IGNORECASE | re.MULTILINE,
)


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


def _validate_database_name(name: str) -> str:
    if not _DB_NAME_RE.fullmatch(name):
        raise ValueError(
            f'Invalid database name {name!r}; '
            'expected letters, digits, or underscore only.',
        )
    return name


def drop_and_recreate_database(args: argparse.Namespace) -> None:
    """DROP and recreate the target database (destructive).

    Connects without selecting the target schema so DROP is allowed.
    """
    db_name = _validate_database_name(args.database)
    conn = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        charset='utf8mb4',
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS `{db_name}`')
            cursor.execute(
                f'CREATE DATABASE `{db_name}` '
                f'CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci',
            )
    finally:
        conn.close()


def _user_count(conn: pymysql.Connection) -> int | None:
    with conn.cursor() as cursor:
        try:
            cursor.execute('SELECT COUNT(*) FROM `generic_user`')
        except pymysql.err.ProgrammingError:
            return None
        row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def _tables_in_sql(sql: str) -> list[str]:
    """Return unique table names targeted by INSERT statements, in order."""
    seen: set[str] = set()
    tables: list[str] = []
    for match in _INSERT_TABLE_RE.finditer(sql):
        table = match.group(1)
        if table not in seen:
            seen.add(table)
            tables.append(table)
    return tables


def _existing_tables(conn: pymysql.Connection, tables: Sequence[str]) -> list[str]:
    if not tables:
        return []
    with conn.cursor() as cursor:
        cursor.execute('SHOW TABLES')
        present = {row[0] for row in cursor.fetchall()}
    return [table for table in tables if table in present]


def truncate_tables(conn: pymysql.Connection, tables: Sequence[str]) -> int:
    """Truncate existing tables with foreign-key checks disabled."""
    targets = _existing_tables(conn, tables)
    if not targets:
        return 0
    with conn.cursor() as cursor:
        cursor.execute('SET FOREIGN_KEY_CHECKS=0')
        try:
            for table in targets:
                cursor.execute(f'TRUNCATE TABLE `{table}`')
        finally:
            cursor.execute('SET FOREIGN_KEY_CHECKS=1')
    conn.commit()
    return len(targets)


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
        help=(
            'Reload sample data: truncate tables present in the SQL dump, '
            'then import (keeps schema and other tables).'
        ),
    )
    parser.add_argument(
        '--drop-database',
        action='store_true',
        help=(
            'Drop and recreate the target database, then exit. '
            'Run migrate before importing.'
        ),
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

    if args.drop_database:
        print(
            f'[import_dev_sample] Dropping and recreating database '
            f'{args.database!r} on {args.host}:{args.port} ...',
        )
        try:
            drop_and_recreate_database(args)
        except Exception as exc:
            print(f'[import_dev_sample] Failed: {exc}', file=sys.stderr)
            return 1
        print(
            '[import_dev_sample] Database recreated. '
            'Run migrate, then import without --drop-database.',
        )
        return 0

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

        if args.force and count > 0:
            sql_text = sql_path.read_text(encoding='utf-8')
            tables = _tables_in_sql(sql_text)
            cleared = truncate_tables(conn, tables)
            print(
                f'[import_dev_sample] --force: truncated {cleared} '
                f'table(s) from dump before import.',
            )

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
