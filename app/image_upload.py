"""把用户新上传的图片解码后重新编码，再用随机文件名保存。"""

import io
import secrets

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

__all__ = ['sanitize_uploaded_image']

_ACCEPTED_FORMATS = frozenset({
    'JPEG', 'PNG', 'GIF', 'BMP', 'TIFF', 'WEBP',
})
_NOT_AN_IMAGE = '上传的文件不是可用的图片'
_JPEG_QUALITY = 90


def sanitize_uploaded_image(uploaded) -> ContentFile | None:
    """解码后重新编码，返回只含随机文件名的 ContentFile。

    空上传原样返回，让调用方继续走“没传图片”的分支。打不开、超出像素
    限制，或格式不在 JPEG、PNG、GIF、BMP、TIFF、WEBP 中时，抛出
    ValidationError。GIF 只保留第一帧。有透明通道或源文件是 PNG 时存 PNG，
    否则存 JPEG。文件名是 32 位十六进制加编码结果的扩展名，不带目录，
    也不使用客户端原名。
    """
    if not uploaded:
        return uploaded

    image = _open_image(uploaded)
    if getattr(image, 'n_frames', 1) > 1:
        image.seek(0)
    encoded, extension = _reencode(image)
    content = ContentFile(encoded)
    content.name = secrets.token_hex(16) + extension
    return content


def _open_image(uploaded) -> Image.Image:
    # 前面的图片头检查可能已经把读指针移到末尾。
    if hasattr(uploaded, 'seek'):
        uploaded.seek(0)
    try:
        image = Image.open(uploaded)
        image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ValidationError(_NOT_AN_IMAGE) from None
    if image.format not in _ACCEPTED_FORMATS:
        raise ValidationError(_NOT_AN_IMAGE)
    return image


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ('RGBA', 'LA', 'PA', 'RGBa'):
        return True
    return 'transparency' in image.info


def _reencode(image: Image.Image) -> tuple[bytes, str]:
    """重新编码。新图不带原图的 info、EXIF 或注释。

    有透明通道，或源文件本身是 PNG 时存 PNG。其余存 JPEG。
    PNG 不转成 JPEG，这样客户端把 PNG 命名成 `.php` 时扩展名仍是 `.png`。
    """
    buffer = io.BytesIO()
    if _has_alpha(image) or image.format == 'PNG':
        mode = 'RGBA' if _has_alpha(image) else 'RGB'
        _without_metadata(image, mode).save(buffer, format='PNG')
        return buffer.getvalue(), '.png'
    _without_metadata(image, 'RGB').save(
        buffer, format='JPEG', quality=_JPEG_QUALITY)
    return buffer.getvalue(), '.jpg'


def _without_metadata(image: Image.Image, mode: str) -> Image.Image:
    """用像素新建图像，避免 save() 写回原图的注释和 EXIF。"""
    converted = image.convert(mode)
    return Image.frombytes(mode, converted.size, converted.tobytes())
