"""Integrity checks: one module per format family, and the dispatcher every
scan (Scan Directory, Exif Info, Blur Check) uses."""

from pathlib import Path

from backend.formats import HEIC_EXTS, JPEG_EXTS, PNG_EXTS, RAW_EXTS, VIDEO_EXTS
from backend.integrity.generic import check_generic_pillow
from backend.integrity.heic import check_heic
from backend.integrity.jpeg import check_jpeg
from backend.integrity.png import check_png
from backend.integrity.raw import check_raw
from backend.integrity.video import check_video

# ─── Dispatcher ───────────────────────────────────────────────────────────────

def check_integrity(filepath: str) -> dict:
    """The file integrity check (what Scan Directory reports), as a dict so
    scans can merge it into their results. integrity is 'ok', 'partial',
    'corrupt', 'exif_only', 'empty', 'error', or 'unsupported' (couldn't be
    checked, e.g. HEIC without pillow-heif); integrity_reason explains it.
    It fully decodes the file (including RAW sensor data), so it's the slow
    part of any scan that uses it."""
    status, reason = check_image(filepath)
    return {'integrity': status, 'integrity_reason': reason}


def check_image(filepath: str):
    ext = Path(filepath).suffix.lower()
    if ext in VIDEO_EXTS:
        return check_video(filepath)
    elif ext in JPEG_EXTS:
        return check_jpeg(filepath)
    elif ext in PNG_EXTS:
        return check_png(filepath)
    elif ext in HEIC_EXTS:
        return check_heic(filepath)
    elif ext in RAW_EXTS:
        return check_raw(filepath)
    else:
        return check_generic_pillow(filepath)
