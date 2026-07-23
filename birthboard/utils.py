import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

MODE_COST = [35, 60, 10000]
MIN_COST_PER_SENDER = 2

# 缩略图宽度（2x 适配 Retina 屏）
THUMBNAIL_WIDTH = 480


def calculate_per_cost(mode: int, sender_count: int) -> int:
    """根据投放模式和送出人数计算每人扣费。"""
    if mode < 0 or mode >= len(MODE_COST):
        mode = 0
    if sender_count <= 0:
        sender_count = 1
    per = MODE_COST[mode] // sender_count
    if per < MIN_COST_PER_SENDER:
        per = MIN_COST_PER_SENDER
    return per


def generate_thumbnail(image_field, thumbnail_width=THUMBNAIL_WIDTH):
    """为 ImageField 文件生成缩略图，返回 ContentFile 或 None。"""
    if not image_field:
        return None
    try:
        img = Image.open(image_field)
        img = img.convert('RGB')
        # 等比缩放
        w_percent = thumbnail_width / float(img.width)
        thumb_height = int(float(img.height) * w_percent)
        img = img.resize((thumbnail_width, thumb_height), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=85)
        # 缩略图文件名：原文件名加 _thumb 后缀
        original_name = os.path.basename(image_field.name)
        name_root, _ = os.path.splitext(original_name)
        thumb_filename = f'{name_root}_thumb.jpg'
        return ContentFile(buf.getvalue(), name=thumb_filename)
    except Exception:
        return None