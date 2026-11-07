"""用户上传图片在保存前会重新编码。"""

import io
import posixpath
import re
import tempfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image, ImageOps

from app.image_upload import sanitize_uploaded_image

_NAME = re.compile(r'^[0-9a-f]{32}\.(jpg|png|gif|webp)$')


def _upload(name: str, image: Image.Image, fmt: str, **save_kwargs):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_kwargs)
    return SimpleUploadedFile(name, buffer.getvalue())


class SanitizeUploadedImageTests(SimpleTestCase):

    def test_jpeg_and_transparent_png_get_random_names(self):
        jpeg = _upload(
            'holiday.JPG', Image.new('RGB', (3, 4), (8, 16, 32)), 'JPEG')
        png = _upload(
            'logo.png', Image.new('RGBA', (2, 2), (0, 0, 0, 0)), 'PNG')

        jpeg_result = sanitize_uploaded_image(jpeg)
        png_result = sanitize_uploaded_image(png)

        self.assertRegex(jpeg_result.name, _NAME)
        self.assertTrue(jpeg_result.name.endswith('.jpg'))
        self.assertNotEqual(jpeg_result.name, 'holiday.JPG')
        self.assertRegex(png_result.name, _NAME)
        self.assertTrue(png_result.name.endswith('.png'))
        self.assertNotEqual(jpeg_result.name, png_result.name)
        self.assertEqual(Image.open(io.BytesIO(jpeg_result.read())).size, (3, 4))
        reopened = Image.open(io.BytesIO(png_result.read()))
        self.assertEqual(reopened.size, (2, 2))
        self.assertIn('A', reopened.mode)

    def test_trailing_bytes_and_comment_are_removed(self):
        image = Image.new('RGB', (3, 4), (10, 20, 30))
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', comment=b'SECRET-COMMENT')
        payload = buffer.getvalue() + b'TRAILER-SECRET'
        uploaded = SimpleUploadedFile('note.jpg', payload)

        result = sanitize_uploaded_image(uploaded)
        encoded = result.read()

        self.assertNotIn(b'SECRET-COMMENT', encoded)
        self.assertNotIn(b'TRAILER-SECRET', encoded)
        self.assertEqual(Image.open(io.BytesIO(encoded)).size, (3, 4))

    def test_text_disguised_as_image_or_script_is_rejected(self):
        for name in ('note.jpg', 'shell.php'):
            uploaded = SimpleUploadedFile(name, b'plain text')
            with self.assertRaises(ValidationError):
                sanitize_uploaded_image(uploaded)

    def test_png_named_as_php_follows_alpha(self):
        opaque = Image.new('RGB', (2, 2), (1, 2, 3))
        transparent = Image.new('RGBA', (2, 2), (1, 2, 3, 0))
        opaque_file = io.BytesIO()
        transparent_file = io.BytesIO()
        opaque.save(opaque_file, format='PNG')
        transparent.save(transparent_file, format='PNG')

        opaque_result = sanitize_uploaded_image(SimpleUploadedFile(
            'index.php', opaque_file.getvalue() + b'<?php echo 1;'))
        transparent_result = sanitize_uploaded_image(SimpleUploadedFile(
            'index.php', transparent_file.getvalue() + b'<?php echo 1;'))
        opaque_bytes = opaque_result.read()
        transparent_bytes = transparent_result.read()

        self.assertRegex(opaque_result.name, r'^[0-9a-f]{32}\.png$')
        self.assertRegex(transparent_result.name, r'^[0-9a-f]{32}\.png$')
        self.assertNotIn(b'<?php', opaque_bytes)
        self.assertNotIn(b'<?php', transparent_bytes)
        self.assertEqual(Image.open(io.BytesIO(opaque_bytes)).format, 'PNG')
        self.assertEqual(Image.open(io.BytesIO(transparent_bytes)).format, 'PNG')
        self.assertEqual(
            Image.open(io.BytesIO(opaque_bytes)).getpixel((0, 0)), (1, 2, 3))

    def test_animated_gif_keeps_later_frames(self):
        first = Image.new('RGB', (2, 2), (255, 0, 0))
        second = Image.new('RGB', (2, 2), (0, 255, 0))
        buffer = io.BytesIO()
        first.save(
            buffer, format='GIF', save_all=True, append_images=[second],
            loop=0, duration=[40, 80], comment=b'SECRET-GIF',
        )
        uploaded = SimpleUploadedFile(
            'motion.gif', buffer.getvalue() + b'TRAILER-SECRET')

        result = sanitize_uploaded_image(uploaded)
        encoded = result.read()
        reopened = Image.open(io.BytesIO(encoded))
        reopened.seek(1)

        self.assertRegex(result.name, _NAME)
        self.assertTrue(result.name.endswith('.gif'))
        self.assertEqual(reopened.n_frames, 2)
        self.assertEqual(reopened.convert('RGB').getpixel((0, 0)), (0, 255, 0))
        self.assertNotIn(b'SECRET-GIF', encoded)
        self.assertNotIn(b'TRAILER-SECRET', encoded)

    def test_partial_gif_keeps_each_frame_disposal(self):
        canvas = (6, 6)
        first = Image.new('RGB', canvas, (255, 0, 0))
        second = Image.new('RGBA', canvas, (0, 0, 0, 0))
        second.paste(Image.new('RGBA', (2, 2), (0, 255, 0, 255)), (4, 4))
        third = Image.new('RGBA', canvas, (0, 0, 0, 0))
        third.paste(Image.new('RGBA', (2, 2), (0, 0, 255, 255)), (0, 0))
        buffer = io.BytesIO()
        first.save(
            buffer, format='GIF', save_all=True, append_images=[second, third],
            duration=[100, 100, 100], loop=0, disposal=[2, 2, 2],
            transparency=0, comment=b'SECRET-GIF',
        )
        payload = buffer.getvalue() + b'<?php'
        source = Image.open(io.BytesIO(payload))
        uploaded = SimpleUploadedFile('delta.gif', payload)

        result = sanitize_uploaded_image(uploaded)
        encoded = result.read()
        reopened = Image.open(io.BytesIO(encoded))

        self.assertTrue(result.name.endswith('.gif'))
        self.assertEqual(reopened.n_frames, source.n_frames)
        for index in range(source.n_frames):
            source.seek(index)
            reopened.seek(index)
            self.assertEqual(reopened.disposal_method, source.disposal_method)
        source.seek(2)
        reopened.seek(2)
        source_pixel = source.convert('RGBA').getpixel((5, 5))
        saved_pixel = reopened.convert('RGBA').getpixel((5, 5))
        corner = reopened.convert('RGBA').getpixel((0, 0))
        self.assertEqual(source_pixel[3], 0)
        self.assertEqual(saved_pixel[3], 0)
        self.assertGreater(corner[2], 200)
        self.assertNotIn(b'SECRET-GIF', encoded)
        self.assertNotIn(b'<?php', encoded)

    def test_jpeg2000_and_avif_are_reencoded(self):
        jpeg2000 = _upload(
            'scan.jp2', Image.new('RGB', (8, 6), (1, 2, 3)), 'JPEG2000')
        jpeg2000 = SimpleUploadedFile(
            'scan.jp2', jpeg2000.read() + b'<?php')
        opaque_avif = _upload(
            'photo.avif', Image.new('RGB', (8, 6), (4, 5, 6)), 'AVIF')
        alpha = Image.new('RGBA', (4, 4), (9, 8, 7, 128))
        alpha_file = io.BytesIO()
        alpha.save(alpha_file, format='AVIF')
        alpha_avif = SimpleUploadedFile('sticker.avif', alpha_file.getvalue())

        jpeg2000_result = sanitize_uploaded_image(jpeg2000)
        opaque_result = sanitize_uploaded_image(opaque_avif)
        alpha_result = sanitize_uploaded_image(alpha_avif)
        jpeg2000_bytes = jpeg2000_result.read()
        alpha_image = Image.open(io.BytesIO(alpha_result.read()))

        self.assertTrue(jpeg2000_result.name.endswith('.jpg'))
        self.assertTrue(opaque_result.name.endswith('.jpg'))
        self.assertTrue(alpha_result.name.endswith('.png'))
        self.assertEqual(
            Image.open(io.BytesIO(jpeg2000_bytes)).size, (8, 6))
        self.assertNotIn(b'<?php', jpeg2000_bytes)
        self.assertIn('A', alpha_image.mode)
        self.assertLess(alpha_image.getpixel((0, 0))[3], 255)

    def test_exif_orientation_is_applied_to_pixels(self):
        image = Image.new('RGB', (20, 40), (0, 0, 180))
        image.paste(Image.new('RGB', (20, 10), (220, 0, 0)), (0, 0))
        exif = Image.Exif()
        exif[0x0112] = 6
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', exif=exif.tobytes(), quality=95)
        uploaded = SimpleUploadedFile('phone.jpg', buffer.getvalue())
        expected = ImageOps.exif_transpose(Image.open(io.BytesIO(buffer.getvalue())))

        result = sanitize_uploaded_image(uploaded)
        reopened = Image.open(io.BytesIO(result.read()))

        self.assertTrue(result.name.endswith('.jpg'))
        self.assertEqual(reopened.size, expected.size)
        self.assertEqual(reopened.size, (40, 20))
        self.assertNotEqual(reopened.getexif().get(0x0112), 6)
        right = reopened.getpixel((reopened.size[0] - 1, 0))
        left = reopened.getpixel((0, 0))
        self.assertGreater(right[0], 180)
        self.assertLess(right[1], 40)
        self.assertLess(left[0], 40)
        self.assertGreater(left[2], 140)

    def test_animated_webp_keeps_later_frames(self):
        first = Image.new('RGB', (8, 8), (255, 0, 0))
        second = Image.new('RGB', (8, 8), (0, 0, 255))
        buffer = io.BytesIO()
        first.save(
            buffer, format='WEBP', save_all=True, append_images=[second],
            duration=[40, 40], loop=0,
        )
        payload = buffer.getvalue()
        source = Image.open(io.BytesIO(payload))
        source.seek(1)
        expected = source.convert('RGB').getpixel((0, 0))
        uploaded = SimpleUploadedFile('motion.webp', payload + b'<?php')

        result = sanitize_uploaded_image(uploaded)
        encoded = result.read()
        reopened = Image.open(io.BytesIO(encoded))
        reopened.seek(1)

        self.assertTrue(result.name.endswith('.webp'))
        self.assertEqual(reopened.n_frames, 2)
        self.assertEqual(reopened.convert('RGB').getpixel((0, 0)), expected)
        self.assertNotEqual(expected[0], 255)
        self.assertNotIn(b'<?php', encoded)

    def test_mpo_is_accepted_as_jpeg(self):
        first = Image.new('RGB', (8, 6), (10, 20, 30))
        second = Image.new('RGB', (8, 6), (200, 0, 0))
        buffer = io.BytesIO()
        first.save(
            buffer, format='MPO', save_all=True, append_images=[second])
        uploaded = SimpleUploadedFile('camera.mpo', buffer.getvalue() + b'<?php')

        result = sanitize_uploaded_image(uploaded)
        encoded = result.read()
        reopened = Image.open(io.BytesIO(encoded))

        self.assertTrue(result.name.endswith('.jpg'))
        self.assertEqual(reopened.size, (8, 6))
        self.assertNotIn(b'<?php', encoded)

    def test_none_stays_none(self):
        self.assertIsNone(sanitize_uploaded_image(None))

    def test_collision_keeps_the_full_random_basename(self):
        fixed = '0123456789abcdef' * 2
        image = Image.new('RGB', (2, 2), (4, 5, 6))
        directory = tempfile.mkdtemp()
        storage = FileSystemStorage(location=directory)
        prefix = 'ActivitySummary/photo/2026/11/'
        with patch('app.image_upload.secrets.token_hex', return_value=fixed):
            first = sanitize_uploaded_image(_upload('a.jpg', image, 'JPEG'))
            second = sanitize_uploaded_image(_upload('b.jpg', image, 'JPEG'))

        self.assertEqual(first.name, fixed + '.jpg')
        self.assertEqual(second.name, first.name)
        saved_first = storage.save(prefix + first.name, ContentFile(first.read()))
        saved_second = storage.save(
            prefix + second.name, ContentFile(second.read()), max_length=100)
        second_base = posixpath.basename(saved_second)

        self.assertNotEqual(saved_first, saved_second)
        self.assertIn(fixed, second_base)
        self.assertLessEqual(len(saved_second), 100)
        self.assertTrue(second_base.endswith('.jpg'))
