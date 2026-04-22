from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO

from django.conf import settings
from django.core.exceptions import ValidationError


IMAGE_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("jpg", b"\xff\xd8\xff"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("gif", b"GIF87a"),
    ("gif", b"GIF89a"),
    ("webp", b"RIFF"),
)
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
SQLITE_HEADER = b"SQLite format 3\x00"


def _file_size(file_obj: object) -> int:
    size = getattr(file_obj, "size", None)
    if isinstance(size, int):
        return size
    return 0


def _peek(file_obj: BinaryIO, length: int = 64) -> bytes:
    position = file_obj.tell() if hasattr(file_obj, "tell") else None
    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return file_obj.read(length)
    finally:
        if position is not None and hasattr(file_obj, "seek"):
            file_obj.seek(position)


def _extension(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def validate_uploaded_image(file_obj) -> None:
    max_size = settings.PROFILE_IMAGE_UPLOAD_MAX_BYTES
    size = _file_size(file_obj)
    if size <= 0:
        raise ValidationError("Image file is empty.")
    if size > max_size:
        raise ValidationError(f"Image file is too large. Max size is {max_size // (1024 * 1024)} MB.")

    extension = _extension(getattr(file_obj, "name", ""))
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Only JPG, PNG, GIF, and WEBP images are allowed.")

    head = _peek(file_obj)
    if extension == "webp":
        is_valid = head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    elif extension in {"jpg", "jpeg"}:
        is_valid = head.startswith(b"\xff\xd8\xff")
    elif extension == "png":
        is_valid = head.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension == "gif":
        is_valid = head.startswith((b"GIF87a", b"GIF89a"))
    else:
        is_valid = False
    if not is_valid:
        raise ValidationError("Uploaded file content is not a supported image.")


def validate_image_bytes(content: bytes) -> None:
    max_size = settings.PROFILE_IMAGE_UPLOAD_MAX_BYTES
    if not content:
        raise ValidationError("Image provider returned an empty file.")
    if len(content) > max_size:
        raise ValidationError(f"Image provider returned a file larger than {max_size // (1024 * 1024)} MB.")
    if content.startswith(b"RIFF"):
        if content[8:12] != b"WEBP":
            raise ValidationError("Image provider returned an unsupported RIFF file.")
        return
    if not any(content.startswith(signature) for image_type, signature in IMAGE_SIGNATURES if image_type != "webp"):
        raise ValidationError("Image provider returned unsupported image content.")


def validate_pyrogram_session_file(file_obj) -> None:
    max_size = settings.TELEGRAM_SESSION_UPLOAD_MAX_BYTES
    size = _file_size(file_obj)
    if size <= 0:
        raise ValidationError("Session file is empty.")
    if size > max_size:
        raise ValidationError(f"Session file is too large. Max size is {max_size // (1024 * 1024)} MB.")
    if _extension(getattr(file_obj, "name", "")) != "session":
        raise ValidationError("Only Pyrogram .session files are allowed.")
    if not _peek(file_obj, len(SQLITE_HEADER)).startswith(SQLITE_HEADER):
        raise ValidationError("Uploaded session file is not a valid Pyrogram SQLite session.")


def validate_json_object_size(value: object, *, max_bytes: int, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be a JSON object.")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValidationError(f"{field_name} is too large. Max size is {max_bytes} bytes.")
