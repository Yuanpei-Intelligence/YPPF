import hashlib
import posixpath
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.test import TestCase, override_settings

from app.models import HomepageImage, NaturalPerson
from boot.config import GLOBAL_CONFIG
from generic.models import User
from utils.storage import (
    UPLOAD_FILENAME_MAX_LENGTH,
    UPLOAD_NAME_MAX_LENGTH,
    UPLOAD_NONCE_HEX_LENGTH,
    SaltedHashStorage,
    encode_upload_digest,
    upload_basename,
)


PNG = b'\x89PNG\r\n\x1a\n' + b'png-bytes'
NONCE = '0123456789abcdef'


class UploadDigestTests(TestCase):
    def test_digest_is_lowercase_sha256_of_bytes_then_salt(self):
        digest = encode_upload_digest(b'avatar-bytes', 'sample-salt')
        expected = hashlib.sha256(
            b'avatar-bytes' + 'sample-salt'.encode('utf-8')).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual(digest, digest.lower())
        self.assertEqual(len(digest), 64)

    def test_different_salt_changes_digest(self):
        self.assertNotEqual(
            encode_upload_digest(b'same', 'salt-a'),
            encode_upload_digest(b'same', 'salt-b'),
        )

    def test_empty_salt_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            encode_upload_digest(b'same', '')


class _IsolatedMediaMixin:
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.settings_override = override_settings(MEDIA_ROOT=self.media)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)


class UploadStorageTests(_IsolatedMediaMixin, TestCase):

    def test_default_backend_is_salted_hash_storage(self):
        self.assertEqual(
            settings.STORAGES['default']['BACKEND'],
            'utils.storage.SaltedHashStorage',
        )
        # default_storage is a lazy proxy; touching it builds the backend.
        self.assertFalse(default_storage.exists('__upload_storage_absent__'))
        self.assertIsInstance(default_storage._wrapped, SaltedHashStorage)

    def test_every_file_field_uses_default_storage_and_fits_digest(self):
        seen = []
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, models.FileField):
                    continue
                seen.append(f'{model._meta.label}.{field.name}')
                self.assertIs(field.storage, default_storage)
                self.assertGreaterEqual(field.max_length, UPLOAD_NAME_MAX_LENGTH)
        self.assertIn('app.NaturalPerson.avatar', seen)
        self.assertIn('app.Organization.wallpaper', seen)
        self.assertIn('app.ActivityPhoto.image', seen)
        self.assertIn('app.CommentPhoto.image', seen)
        self.assertIn('app.ModifyOrganization.avatar', seen)
        self.assertIn('app.Course.photo', seen)
        self.assertIn('app.Course.QRcode', seen)
        self.assertIn('app.Prize.image', seen)
        self.assertIn('app.ActivitySummary.image', seen)
        self.assertIn('app.HomepageImage.image', seen)
        self.assertIn('achievement.AchievementType.badge', seen)
        self.assertIn('achievement.AchievementType.avatar', seen)

    def test_save_replaces_client_name_and_keeps_directory(self):
        payload = b'unique-upload-body'
        digest = encode_upload_digest(
            payload, GLOBAL_CONFIG.salt)
        filename = upload_basename(digest, '.png', NONCE)
        self.assertEqual(len(NONCE), UPLOAD_NONCE_HEX_LENGTH)
        self.assertEqual(len(filename), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertTrue(filename.endswith(NONCE + '.png'))
        self.assertNotIn(digest, filename)
        with patch('utils.storage._upload_nonce', return_value=NONCE):
            saved = default_storage.save(
                'wallpaper/My Face.PNG', ContentFile(payload))
        self.assertEqual(saved, f'wallpaper/{filename}')
        self.assertNotIn('My Face', saved)
        self.assertEqual(default_storage.open(saved).read(), payload)

    def test_unsafe_name_is_not_stored(self):
        with patch('utils.storage._upload_nonce', return_value=NONCE):
            saved = default_storage.save(
                'avatar/evil.php', ContentFile(b'<?php echo 1;'))
        self.assertRegex(saved, r'^avatar/[0-9a-f]{32}$')
        self.assertTrue(posixpath.basename(saved).endswith(NONCE))
        self.assertEqual(
            len(posixpath.basename(saved)), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertNotIn('evil', saved)
        self.assertNotIn('php', saved)

        with patch('utils.storage._upload_nonce', return_value=NONCE):
            sniffed = default_storage.save(
                'comment/2026/10/evil.html', ContentFile(PNG))
        self.assertTrue(sniffed.startswith('comment/2026/10/'))
        self.assertTrue(sniffed.endswith('.png'))
        self.assertLessEqual(
            len(posixpath.basename(sniffed)), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertNotIn('evil', sniffed)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(SuspiciousFileOperation):
            default_storage.save(
                'avatar/../../etc/passwd.png', ContentFile(PNG))

    def test_duplicate_content_does_not_reuse_or_restore_client_name(self):
        first = default_storage.save('avatar/a.jpg', ContentFile(b'dup'))
        second = default_storage.save('avatar/b.jpg', ContentFile(b'dup'))
        self.assertNotEqual(first, second)
        self.assertNotEqual(
            posixpath.basename(first)[:-4], posixpath.basename(second)[:-4])
        self.assertLessEqual(
            len(posixpath.basename(first)), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertLessEqual(
            len(posixpath.basename(second)), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertNotIn('a.jpg', first)
        self.assertNotIn('b.jpg', second)
        self.assertEqual(default_storage.open(first).read(), b'dup')
        self.assertEqual(default_storage.open(second).read(), b'dup')

    def test_longest_current_prefix_keeps_full_digest(self):
        payload = b'long-path'
        with patch('utils.storage._upload_nonce', return_value=NONCE):
            saved = default_storage.save(
                'ActivitySummary/photo/2026/10/original name.jpeg',
                ContentFile(payload),
            )
        digest = encode_upload_digest(
            payload, GLOBAL_CONFIG.salt)
        filename = upload_basename(digest, '.jpeg', NONCE)
        self.assertEqual(len(filename), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertEqual(
            saved, f'ActivitySummary/photo/2026/10/{filename}')
        self.assertLessEqual(len(saved), UPLOAD_NAME_MAX_LENGTH)
        self.assertNotIn('original', saved)


class UploadAccessTests(_IsolatedMediaMixin, TestCase):
    def test_legacy_avatar_path_remains_readable(self):
        user = User.objects.create_user(
            'upload_legacy', 'Legacy', password='pw')
        person = NaturalPerson.objects.create(user, name='Legacy')
        self.assertEqual(
            person.get_user_ava(), '/media/avatar/person_default.jpg')

        legacy = Path(self.media) / 'avatar' / 'person_old.jpg'
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'legacy-avatar')
        person.avatar = 'avatar/person_old.jpg'
        person.save()
        person.refresh_from_db()
        self.assertEqual(person.avatar.name, 'avatar/person_old.jpg')
        self.assertEqual(
            person.get_user_ava(), '/media/avatar/person_old.jpg')
        self.assertEqual(person.avatar.read(), b'legacy-avatar')

    def test_new_avatar_is_stored_and_served_by_hashed_path(self):
        user = User.objects.create_user(
            'upload_new', 'NewUser', password='pw')
        person = NaturalPerson.objects.create(user, name='NewUser')
        person.avatar = SimpleUploadedFile('../../相册.png', PNG)
        with patch('utils.storage._upload_nonce', return_value=NONCE):
            person.save()
        person.refresh_from_db()

        digest = encode_upload_digest(PNG, GLOBAL_CONFIG.salt)
        filename = upload_basename(digest, '.png', NONCE)
        self.assertEqual(len(filename), UPLOAD_FILENAME_MAX_LENGTH)
        self.assertEqual(person.avatar.name, f'avatar/{filename}')
        self.assertEqual(person.get_user_ava(), f'/media/avatar/{filename}')
        self.assertEqual(person.avatar.url, f'/media/avatar/{filename}')
        self.assertEqual(person.avatar.read(), PNG)
        self.assertTrue((Path(self.media) / person.avatar.name).is_file())

    def test_preset_path_and_copied_file_keep_stored_name(self):
        preset = HomepageImage(description='preset')
        preset.image = 'homepage_image/preset_banner.png'
        preset.save()
        preset.refresh_from_db()
        self.assertEqual(preset.image.name, 'homepage_image/preset_banner.png')

        source = HomepageImage.objects.create(
            description='source',
            image=SimpleUploadedFile('banner.png', PNG),
        )
        stored_name = source.image.name
        target = HomepageImage(description='target')
        target.image = source.image
        target.save()
        source.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(source.image.name, stored_name)
        self.assertEqual(target.image.name, stored_name)
        self.assertEqual(source.image.read(), PNG)
        self.assertEqual(target.image.read(), PNG)

    def test_account_setting_upload_and_profile_url(self):
        user = User.objects.create_user(
            'upload_page', 'PageUser', User.Type.STUDENT,
            password='pw', is_newuser=False,
        )
        person = NaturalPerson.objects.create(user, name='PageUser')
        legacy = Path(self.media) / 'avatar' / 'page_old.png'
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(PNG)
        person.avatar = 'avatar/page_old.png'
        person.save()

        self.client.force_login(user)
        settings_url = '/userAccountSetting/'
        before = self.client.get(settings_url)
        self.assertEqual(before.status_code, 200)
        self.assertContains(before, '/media/avatar/page_old.png')

        with patch('utils.storage._upload_nonce', return_value=NONCE):
            response = self.client.post(settings_url, {
                'nickname': '',
                'aboutBio': person.biography,
                'tel': '',
                'email': '',
                'major': '',
                'dorm': '',
                'gender': '男',
                'birthday': '',
                'accept_promote': '是',
                'wechat_receive_level': '接收全部消息',
                'avatar': SimpleUploadedFile('my face.png', PNG),
            })
        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        digest = encode_upload_digest(PNG, GLOBAL_CONFIG.salt)
        filename = upload_basename(digest, '.png', NONCE)
        self.assertEqual(person.avatar.name, f'avatar/{filename}')
        self.assertNotIn('my face', person.avatar.name)
        self.assertEqual(legacy.read_bytes(), PNG)

        after = self.client.get(settings_url)
        self.assertContains(after, f'/media/avatar/{filename}')
        self.assertNotContains(after, 'my face.png')
        profile = self.client.get('/stuinfo/?modinfo=success', follow=True)
        self.assertEqual(profile.status_code, 200)
        self.assertContains(profile, f'/media/avatar/{filename}')
