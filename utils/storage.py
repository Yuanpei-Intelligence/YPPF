"""Rename user uploads before they are written to media storage."""

import hashlib
import imghdr
import pathlib
import posixpath
import secrets

from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.utils.crypto import get_random_string
from django.utils.deconstruct import deconstructible

from boot.config import GLOBAL_CONFIG


__all__ = [
    'UPLOAD_FILENAME_MAX_LENGTH',
    'UPLOAD_NAME_MAX_LENGTH',
    'SaltedHashStorage',
    'encode_upload_digest',
    'UPLOAD_NONCE_HEX_LENGTH',
    'hashed_upload_path',
    'upload_basename',
]


# Basename only, including the digest prefix, nonce, extension, and a
# collision suffix.
UPLOAD_FILENAME_MAX_LENGTH = 32
# 8 random bytes, written as 16 hex characters. This is the unpredictable
# part of the name; the salted digest alone is not.
UPLOAD_NONCE_HEX_LENGTH = 16
# Django's unavailable-name suffix is "_" plus 7 random characters.
_COLLISION_SUFFIX_LENGTH = 8
# Stored relative path. Directories stay outside the 32-character basename.
UPLOAD_NAME_MAX_LENGTH = 255

_ALLOWED_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    '.tif', '.tiff', '.ico', '.rgb',
})

# imghdr labels that are safe to append when the client extension is not.
_SNIFFED_EXTENSIONS = {
    'jpeg': '.jpg',
    'png': '.png',
    'gif': '.gif',
    'bmp': '.bmp',
    'webp': '.webp',
    'tiff': '.tif',
    'rgb': '.rgb',
}


def _filename_salt() -> str:
    # Same secret as MySHA256Hasher. LazySetting caches it after first use.
    salt = GLOBAL_CONFIG.salt
    if not isinstance(salt, str) or salt == '':
        raise ImproperlyConfigured(
            'global.hash_salt must be a non-empty string'
        )
    return salt


def encode_upload_digest(data: bytes, salt: str) -> str:
    """
    Return the lowercase SHA-256 hex digest of ``data + salt``.

    ``salt`` is encoded as UTF-8 and appended, the same order as
    ``MySHA256Hasher``. The digest is lowercase so stored paths do not
    depend on filesystem case. An empty salt is rejected.

    :param data: raw file bytes
    :param salt: non-empty salt
    :return: 64-character hex digest
    :raises ImproperlyConfigured: salt is missing or empty
    :raises TypeError: data is not bytes
    """
    if not isinstance(salt, str) or salt == '':
        raise ImproperlyConfigured(
            'upload filename salt must be a non-empty string'
        )
    if not isinstance(data, bytes):
        raise TypeError('upload digest data must be bytes')
    return hashlib.sha256(data + salt.encode('utf-8')).hexdigest()


def _rewind(content) -> None:
    try:
        content.seek(0)
    except (AttributeError, OSError) as exc:
        raise SuspiciousFileOperation(
            'Uploaded file cannot be rewound after hashing'
        ) from exc


def _digest_upload(content, salt: str) -> tuple[str, bytes]:
    """Hash ``content`` as bytes-then-salt and rewind it."""
    hasher = hashlib.sha256()
    head = b''
    for chunk in content.chunks():
        if isinstance(chunk, str):
            chunk = chunk.encode('utf-8')
        if len(head) < 32:
            head += chunk[:32 - len(head)]
        hasher.update(chunk)
    hasher.update(salt.encode('utf-8'))
    _rewind(content)
    return hasher.hexdigest(), head


def _safe_extension(original_name: str, head: bytes) -> str:
    """Keep an allowlisted image extension, otherwise sniff one."""
    base = posixpath.basename(str(original_name).replace('\\', '/'))
    extension = posixpath.splitext(base)[1].lower()
    if extension in _ALLOWED_EXTENSIONS:
        return extension
    kind = imghdr.what(None, h=head)
    if kind is None:
        return ''
    return _SNIFFED_EXTENSIONS.get(kind, '')


def _upload_nonce() -> str:
    # Fresh value for every upload. It is not stored except as part of the
    # filename, so the same bytes do not produce a predictable path.
    return secrets.token_hex(UPLOAD_NONCE_HEX_LENGTH // 2)


def upload_basename(digest: str, extension: str, nonce: str) -> str:
    """
    Fit a hashed image basename into ``UPLOAD_FILENAME_MAX_LENGTH``.

    The name is the leading hex of the salted digest, then ``nonce``, then
    the extension. The nonce is what makes the name unpredictable. The
    directory is not part of the 32-character limit.

    :param digest: 64-character hex digest of the file and salt
    :param extension: lowercase extension including the dot, or empty
    :param nonce: per-upload lowercase hex nonce
    :return: basename of at most 32 characters
    :raises SuspiciousFileOperation: nonce or extension leaves no digest room
    """
    if (
            len(nonce) != UPLOAD_NONCE_HEX_LENGTH
            or any(char not in '0123456789abcdef' for char in nonce)
    ):
        raise SuspiciousFileOperation(
            'Upload nonce must be 16 lowercase hex characters'
        )
    extra = len(extension) + len(nonce)
    if extra >= UPLOAD_FILENAME_MAX_LENGTH:
        raise SuspiciousFileOperation(
            'Image extension leaves no room for a hashed filename'
        )
    room = UPLOAD_FILENAME_MAX_LENGTH - extra
    return digest[:room] + nonce + extension


def _relative_directory(name: str) -> str:
    """Return the upload_to directory, rejecting absolute paths and ``..``."""
    normalized = str(name).replace('\\', '/')
    directory, _basename = posixpath.split(normalized)
    path = pathlib.PurePosixPath(directory)
    if path.is_absolute() or '..' in path.parts:
        raise SuspiciousFileOperation(
            f'Detected path traversal attempt in {directory!r}'
        )
    return directory


def hashed_upload_path(name: str | None, content) -> str:
    """
    Build the relative media path for one new upload.

    ``upload_to`` supplies the directory. The stored basename is a truncated
    salted digest, a random nonce, and a safe extension. The client basename
    is not kept. ``content`` is left rewound so storage can write the same
    bytes.

    :param name: relative name Django generated, usually directory plus the
        client filename
    :param content: file-like upload
    :return: relative path to store in the database and on disk
    :raises SuspiciousFileOperation: the name is missing or escapes the
        storage root
    """
    if name is None:
        name = getattr(content, 'name', None)
    if not name:
        raise SuspiciousFileOperation('Uploaded file is missing a name')
    if not hasattr(content, 'chunks'):
        content = File(content, name)
    digest, head = _digest_upload(content, _filename_salt())
    directory = _relative_directory(name)
    filename = upload_basename(
        digest, _safe_extension(name, head), _upload_nonce())
    if directory:
        return f'{directory}/{filename}'
    return filename


@deconstructible(path='utils.storage.SaltedHashStorage')
class SaltedHashStorage(FileSystemStorage):
    """
    Save new files under ``hashed_upload_path``.

    Assigning an existing relative path to a ``FileField`` does not call
    ``save``, so previously stored files keep their names and URLs.
    """

    def get_alternative_name(self, file_root, file_ext):
        # Keep the collision name inside the same 32-character basename limit.
        suffix = '_' + get_random_string(_COLLISION_SUFFIX_LENGTH - 1)
        room = UPLOAD_FILENAME_MAX_LENGTH - len(file_ext) - len(suffix)
        if room < 1:
            raise SuspiciousFileOperation(
                'Storage cannot find a filename of at most '
                f'{UPLOAD_FILENAME_MAX_LENGTH} characters'
            )
        return f'{file_root[:room]}{suffix}{file_ext}'

    def save(self, name, content, max_length=None):
        if name is None:
            name = getattr(content, 'name', None)
        if not hasattr(content, 'chunks'):
            content = File(content, name)
        hashed_name = hashed_upload_path(name, content)
        return super().save(hashed_name, content, max_length=max_length)
