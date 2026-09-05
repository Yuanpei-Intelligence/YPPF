from io import BytesIO
import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image

from birthboard.models import BirthboardRecord
from birthboard.utils import THUMBNAIL_WIDTH


class Command(BaseCommand):
    help = '为所有没有缩略图的 BirthboardRecord 补生成缩略图'

    def handle(self, *args, **options):
        records = BirthboardRecord.objects.filter(thumbnail__isnull=True, image__isnull=False).exclude(image='')
        total = records.count()
        self.stdout.write(f'找到 {total} 条记录需要补缩略图')

        success = 0
        failed = 0

        for record in records:
            try:
                if not record.image:
                    continue
                # 打开原图
                img = Image.open(record.image)
                img = img.convert('RGB')
                # 等比缩放
                w_percent = THUMBNAIL_WIDTH / float(img.width)
                thumb_height = int(float(img.height) * w_percent)
                img = img.resize((THUMBNAIL_WIDTH, thumb_height), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, format='JPEG', quality=85)
                # 文件名
                original_name = os.path.basename(record.image.name)
                name_root, _ = os.path.splitext(original_name)
                thumb_filename = f'{name_root}_thumb.jpg'
                # 保存缩略图
                record.thumbnail.save(thumb_filename, ContentFile(buf.getvalue()), save=True)
                self.stdout.write(f'  ✓ {record.id}: {original_name} -> {thumb_filename}')
                success += 1
            except Exception as e:
                self.stderr.write(f'  ✗ {record.id}: {e}')
                failed += 1

        self.stdout.write(self.style.SUCCESS(
            f'完成：成功 {success}，失败 {failed}，共 {total}'
        ))
