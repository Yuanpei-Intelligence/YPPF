"""把用户新上传的图片解码后重新编码，再用随机文件名保存。"""

import io
import secrets

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

__all__ = ['sanitize_uploaded_image']

_ACCEPTED_FORMATS = frozenset({
    'JPEG', 'PNG', 'GIF', 'BMP', 'TIFF', 'WEBP', 'MPO',
})
_NOT_AN_IMAGE = '上传的文件不是可用的图片'
_JPEG_QUALITY = 90
_DROPPED_INFO = ('comment', 'exif', 'xmp', 'icc_profile')


def sanitize_uploaded_image(uploaded) -> ContentFile | None:
    """解码后重新编码，返回只含随机文件名的 ContentFile。

    空上传原样返回。打不开、超出像素限制，或格式不在允许列表中时，抛出
    ValidationError。保存前按 EXIF 方向把像素转正，并丢掉注释、EXIF 和
    文件尾附加内容。PNG 仍存 PNG，GIF 保留各帧，动态 WebP 仍是动态 WebP。
    JPEG 以及 Pillow 能打开的 MPO 存 JPEG。文件名是 32 位十六进制加编码
    结果的扩展名，不带目录，也不使用客户端原名。
    """
    if not uploaded:
        return uploaded

    image = _open_image(uploaded)
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


def _upright(image: Image.Image) -> Image.Image:
    """按 EXIF 方向转正像素。没有方向标记时保持原图。"""
    transposed = ImageOps.exif_transpose(image)
    if transposed is None:
        return image
    return transposed


def _reencode(image: Image.Image) -> tuple[bytes, str]:
    """重新编码，扩展名跟用户现在在浏览器里看到的效果一致。"""
    source_format = image.format
    if source_format == 'GIF':
        return _encode_gif(image), '.gif'
    if source_format == 'WEBP' and getattr(image, 'n_frames', 1) > 1:
        return _encode_animated_webp(image), '.webp'
    if source_format == 'WEBP':
        return _encode_still_webp(_upright(image)), '.webp'
    if source_format == 'PNG':
        return _encode_png(_upright(image)), '.png'
    if source_format == 'MPO':
        image.seek(0)
        return _encode_jpeg(_upright(image)), '.jpg'
    upright = _upright(image)
    if _has_alpha(upright):
        return _encode_png(upright), '.png'
    return _encode_jpeg(upright), '.jpg'


def _encode_png(image: Image.Image) -> bytes:
    mode = 'RGBA' if _has_alpha(image) else 'RGB'
    buffer = io.BytesIO()
    _without_metadata(image, mode).save(buffer, format='PNG')
    return buffer.getvalue()


def _encode_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    _without_metadata(image, 'RGB').save(
        buffer, format='JPEG', quality=_JPEG_QUALITY)
    return buffer.getvalue()


def _encode_still_webp(image: Image.Image) -> bytes:
    mode = 'RGBA' if _has_alpha(image) else 'RGB'
    buffer = io.BytesIO()
    _without_metadata(image, mode).save(buffer, format='WEBP', lossless=True)
    return buffer.getvalue()


def _encode_gif(image: Image.Image) -> bytes:
    frames, durations, loop = _animation_frames(image)
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format='GIF', save_all=True, append_images=frames[1:],
        duration=durations, loop=loop,
    )
    return buffer.getvalue()


def _encode_animated_webp(image: Image.Image) -> bytes:
    frames, durations, loop = _animation_frames(image)
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format='WEBP', save_all=True, append_images=frames[1:],
        duration=durations, loop=loop, lossless=True,
    )
    return buffer.getvalue()


def _animation_frames(image: Image.Image) -> tuple[list[Image.Image], list[int], int]:
    """复制每一帧的像素，不带走注释和 EXIF。"""
    frames = []
    durations = []
    loop = 0
    count = getattr(image, 'n_frames', 1)
    for index in range(count):
        image.seek(index)
        if index == 0:
            loop = int(image.info.get('loop', 0) or 0)
        frame = image.copy()
        for key in _DROPPED_INFO:
            frame.info.pop(key, None)
        frames.append(frame)
        durations.append(int(image.info.get('duration') or 0))
    return frames, durations, loop


def _without_metadata(image: Image.Image, mode: str) -> Image.Image:
    """用像素新建图像，避免 save() 写回原图的注释和 EXIF。"""
    converted = image.convert(mode)
    return Image.frombytes(mode, converted.size, converted.tobytes())
