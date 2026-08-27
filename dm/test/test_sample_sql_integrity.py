"""Regression checks for the committed development sample SQL dump."""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SQL = REPO_ROOT / 'dev_sample.sql'

# (table, fk_column, referenced_table, pk_column_in_ref)
# NULL fk values are allowed.
FK_CHECKS: list[tuple[str, str, str, str]] = [
    ('app_pool', 'activity_id', 'app_activity', 'commentbase_ptr_id'),
    ('feedback_feedback', 'person_id', 'app_naturalperson', 'id'),
    ('feedback_feedback', 'org_id', 'app_organization', 'id'),
    ('app_participation', 'activity_id', 'app_activity', 'commentbase_ptr_id'),
    ('app_participation', 'person_id', 'app_naturalperson', 'id'),
    ('app_poolrecord', 'pool_id', 'app_pool', 'id'),
    ('app_poolrecord', 'user_id', 'generic_user', 'id'),
    ('app_courserecord', 'course_id', 'app_course', 'id'),
    ('app_courserecord', 'person_id', 'app_naturalperson', 'id'),
    ('yp_library_lendrecord', 'reader_id_id', 'yp_library_reader', 'id'),
]


def _split_sql_values(inner: str) -> list[str]:
    vals: list[str] = []
    buf: list[str] = []
    in_string = False
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        nxt = inner[i + 1] if i + 1 < n else ''
        if ch == "'" and not in_string:
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if in_string:
            buf.append(ch)
            if ch == '\\' and i + 1 < n:
                buf.append(nxt)
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
        if ch == ',':
            vals.append(''.join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    vals.append(''.join(buf).strip())
    return vals


def _ids_from_inserts(sql: str, table: str, pk_column: str = 'id') -> set[int]:
    ids: set[int] = set()
    pattern = rf'INSERT INTO `{table}` \(([^)]+)\) VALUES\n(.*?);'
    for match in re.finditer(pattern, sql, re.S):
        columns = [c.strip().strip('`') for c in match.group(1).split(',')]
        if pk_column not in columns:
            # Fallback: first column for tables that use a different PK name
            # only when caller asked for default 'id'.
            if pk_column == 'id':
                pk_idx = 0
            else:
                continue
        else:
            pk_idx = columns.index(pk_column)
        for line in match.group(2).splitlines():
            line = line.strip().rstrip(',')
            if not line.startswith('('):
                continue
            vals = _split_sql_values(line[1:-1])
            if pk_idx >= len(vals):
                continue
            raw = vals[pk_idx]
            if raw != 'NULL':
                ids.add(int(raw))
    return ids


def _fk_refs(
    sql: str,
    table: str,
    fk_column: str,
) -> list[tuple[str, int]]:
    """Return list of (row_pk_or_?, fk_value) for non-NULL FK values."""
    refs: list[tuple[str, int]] = []
    pattern = rf'INSERT INTO `{table}` \(([^)]+)\) VALUES\n(.*?);'
    for match in re.finditer(pattern, sql, re.S):
        columns = [c.strip().strip('`') for c in match.group(1).split(',')]
        if fk_column not in columns:
            continue
        fk_idx = columns.index(fk_column)
        pk_idx = 0
        for line in match.group(2).splitlines():
            line = line.strip().rstrip(',')
            if not line.startswith('('):
                continue
            vals = _split_sql_values(line[1:-1])
            raw = vals[fk_idx]
            if raw == 'NULL':
                continue
            refs.append((vals[pk_idx], int(raw)))
    return refs


class SampleSqlIntegrityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.assertTrue(
            SAMPLE_SQL.is_file(),
            f'missing committed sample dump: {SAMPLE_SQL}',
        )
        cls.sql = SAMPLE_SQL.read_text(encoding='utf-8')

    def test_dump_is_insert_only(self):
        for banned in (
            'CREATE TABLE',
            'DROP TABLE',
            'ALTER TABLE',
            'TRUNCATE TABLE',
        ):
            self.assertNotIn(banned, self.sql.upper())

    def test_foreign_key_checks_disabled_then_restored(self):
        self.assertIn('SET FOREIGN_KEY_CHECKS=0', self.sql)
        self.assertIn('SET FOREIGN_KEY_CHECKS=1', self.sql)
        self.assertGreater(
            self.sql.rfind('SET FOREIGN_KEY_CHECKS=1'),
            self.sql.find('SET FOREIGN_KEY_CHECKS=0'),
        )

    def test_high_risk_foreign_keys_resolve(self):
        dangling: list[str] = []
        for table, fk_col, ref_table, ref_pk in FK_CHECKS:
            if f'INSERT INTO `{table}`' not in self.sql:
                continue
            if f'INSERT INTO `{ref_table}`' not in self.sql:
                continue
            present = _ids_from_inserts(self.sql, ref_table, ref_pk)
            # app_activity PK in dump is commentbase_ptr_id; also accept first-col
            if not present and ref_pk != 'id':
                present = _ids_from_inserts(self.sql, ref_table, 'id')
            for row_pk, fk_val in _fk_refs(self.sql, table, fk_col):
                if fk_val not in present:
                    dangling.append(
                        f'{table}.{fk_col}={fk_val} (row {row_pk}) '
                        f'not in {ref_table}.{ref_pk}'
                    )
        self.assertEqual(dangling, [], '\n'.join(dangling))

    def test_library_reader_ids_are_remapped(self):
        """External library reader/lend PKs must not appear in the dump."""
        if 'INSERT INTO `yp_library_reader`' not in self.sql:
            self.skipTest('no library readers in dump')
        reader_ids = sorted(_ids_from_inserts(self.sql, 'yp_library_reader'))
        self.assertEqual(
            reader_ids,
            list(range(1, len(reader_ids) + 1)),
            'yp_library_reader.id must be remapped to 1..N',
        )
        if 'INSERT INTO `yp_library_lendrecord`' not in self.sql:
            return
        lend_ids = sorted(_ids_from_inserts(self.sql, 'yp_library_lendrecord'))
        self.assertEqual(
            lend_ids,
            list(range(1, len(lend_ids) + 1)),
            'yp_library_lendrecord.id must be remapped to 1..N',
        )
        match = re.search(
            r'INSERT INTO `yp_library_lendrecord` \(([^)]+)\)',
            self.sql,
        )
        self.assertIsNotNone(match)
        cols = [c.strip().strip('`') for c in match.group(1).split(',')]
        reader_fk_col = (
            'reader_id_id' if 'reader_id_id' in cols else 'reader_id'
        )
        for _, fk_val in _fk_refs(
            self.sql, 'yp_library_lendrecord', reader_fk_col
        ):
            self.assertIn(fk_val, set(reader_ids))

    def test_questionnaire_sample_sheets_use_submitted_status(self):
        """Completed sample responses must not be imported as mutable drafts."""
        if 'INSERT INTO `questionnaire_answersheet`' not in self.sql:
            self.skipTest('no questionnaire answer sheets in dump')
        statuses = {
            status
            for _, status in _fk_refs(
                self.sql,
                'questionnaire_answersheet',
                'status',
            )
        }
        self.assertEqual(statuses, {1})
