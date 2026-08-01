#!/usr/bin/env python3
"""Create or refresh the local development Django superuser.

Default credentials: username ``admin``, password ``secret``.
Intended for Dev Container sample-DB setup after migrate/import.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Create or update the development superuser.',
    )
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password', default='secret')
    parser.add_argument('--name', default='admin')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'boot.settings')
    import django

    django.setup()

    from generic.models import User

    user = User.objects.filter(username=args.username).first()
    if user is None:
        user = User.objects.create_superuser(
            username=args.username,
            name=args.name,
            password=args.password,
        )
        created = True
    else:
        user.set_password(args.password)
        user.name = args.name
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.active = True
        created = False

    # Skip first-login / agreement redirect for local admin use.
    user.is_newuser = False
    user.save()

    if not user.check_password(args.password):
        print('[create_dev_superuser] Password verification failed.', file=sys.stderr)
        return 1
    if not (user.is_superuser and user.is_staff):
        print('[create_dev_superuser] Superuser flags missing.', file=sys.stderr)
        return 1

    action = 'created' if created else 'updated'
    print(
        f'[create_dev_superuser] Superuser {action}: '
        f'username={args.username!r} password={args.password!r}',
    )
    print('[create_dev_superuser] Ready for /admin/.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
