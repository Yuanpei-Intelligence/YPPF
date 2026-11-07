"""用户上传图片在保存前会重新编码。"""

import io
import re

from django.core.exceptions import ValidationError
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
