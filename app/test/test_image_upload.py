"""用户上传图片在保存前会重新编码。"""

import io
import re

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from app.image_upload import sanitize_uploaded_image

_NAME = re.compile(r'^[0-9a-f]{32}\.(jpg|png)$')


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

    def test_png_named_as_php_is_stored_as_png(self):
        image = Image.new('RGB', (2, 2), (1, 2, 3))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        uploaded = SimpleUploadedFile(
            'index.php', buffer.getvalue() + b'<?php echo 1;')

        result = sanitize_uploaded_image(uploaded)
        encoded = result.read()

        self.assertRegex(result.name, r'^[0-9a-f]{32}\.png$')
        self.assertNotIn(b'<?php', encoded)
        self.assertEqual(Image.open(io.BytesIO(encoded)).format, 'PNG')

    def test_animated_gif_keeps_only_the_first_frame(self):
        first = Image.new('RGB', (2, 2), (255, 0, 0))
        second = Image.new('RGB', (2, 2), (0, 255, 0))
        buffer = io.BytesIO()
        first.save(
            buffer, format='GIF', save_all=True,
            append_images=[second], loop=0, duration=100,
        )
        uploaded = SimpleUploadedFile('motion.gif', buffer.getvalue())

        result = sanitize_uploaded_image(uploaded)
        reopened = Image.open(io.BytesIO(result.read()))

        self.assertRegex(result.name, _NAME)
        self.assertEqual(getattr(reopened, 'n_frames', 1), 1)
        self.assertEqual(reopened.size, (2, 2))
        red, green, blue = reopened.convert('RGB').getpixel((0, 0))
        self.assertGreater(red, 250)
        self.assertLess(green, 5)
        self.assertLess(blue, 5)

    def test_none_stays_none(self):
        self.assertIsNone(sanitize_uploaded_image(None))
