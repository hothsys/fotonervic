"""Thumbnails for Exif Info and Blur Check cards, with an in-memory LRU cache."""

import io
import threading
from collections import OrderedDict
from pathlib import Path

from backend.exif import (
    _RAW_FLIP_TO_ORIENTATION,
    _TAG_ORIENTATION,
    _apply_orientation,
    _image_orientation,
)
from backend.formats import HEIC_EXTS, RAW_EXTS, VIDEO_EXTS

# Thumbnail cache: OrderedDict used as simple LRU (max 1000 entries)


_thumbnail_cache: OrderedDict = OrderedDict()
_THUMBNAIL_CACHE_MAX = 1000
# Requests run on several threads, and /api/clear-cache empties the cache
_thumbnail_lock = threading.Lock()
_THUMBNAIL_SIZE = 300  # max px on either axis


def _generate_thumbnail(filepath: str) -> bytes | None:
    """Return JPEG thumbnail bytes, or None on failure."""
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    ext = Path(filepath).suffix.lower()
    try:
        img = None
        orientation = None

        if ext in VIDEO_EXTS:
            return None  # caller renders a video-icon placeholder

        if ext in HEIC_EXTS:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass

        if ext in RAW_EXTS:
            try:
                import rawpy
                with rawpy.imread(filepath) as raw:
                    try:
                        thumb = raw.extract_thumb()
                        import rawpy as _rp
                        if thumb.format == _rp.ThumbFormat.JPEG:
                            img = Image.open(io.BytesIO(thumb.data))
                            orientation = img.getexif().get(_TAG_ORIENTATION)
                        else:
                            img = Image.fromarray(thumb.data)
                        # Embedded previews are usually stored unrotated, with
                        # the camera's orientation recorded only in the RAW
                        if orientation in (None, 1):
                            orientation = _RAW_FLIP_TO_ORIENTATION.get(raw.sizes.flip)
                    except Exception:
                        # postprocess() applies the RAW's orientation itself
                        rgb = raw.postprocess(
                            use_camera_wb=True, half_size=True, output_bps=8)
                        img = Image.fromarray(rgb)
            except Exception:
                pass

        if img is None:
            img = Image.open(filepath)
            orientation = _image_orientation(img, filepath)

        # Shrink first (fast JPEG draft decode), then rotate. The saved
        # thumbnail carries no EXIF, so the browser can't rotate it for us.
        img.thumbnail((_THUMBNAIL_SIZE, _THUMBNAIL_SIZE), Image.LANCZOS)
        img = _apply_orientation(img, orientation)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=72, optimize=True)
        buf.seek(0)
        return buf.read()

    except Exception:
        return None
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False
