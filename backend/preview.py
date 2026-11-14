"""Lightbox previews: upright JPEGs of any supported image, at screen size or
full resolution, with a size-capped in-memory cache.

Browsers can't display RAW at all, or HEIC/TIFF in Chrome, so every preview is
rendered here. The lightbox (js/lightbox.js) shows the screen-size version and
asks for the full-resolution one only when the photo is zoomed in.
"""

import io
import os
import threading
from collections import OrderedDict
from pathlib import Path

from backend.blur.loading import _find_companion
from backend.exif import (
    _RAW_FLIP_TO_ORIENTATION,
    _TAG_ORIENTATION,
    _apply_orientation,
    _image_orientation,
)
from backend.formats import HEIC_EXTS, RAW_EXTS, VIDEO_EXTS

PREVIEW_SIZE = 2560          # long side of the screen-size version (sharp on Retina displays)
PREVIEW_MIN_EMBEDDED = 1024  # RAW previews smaller than this (iPhone DNGs: 328 px) aren't worth showing
PREVIEW_QUALITY = 88         # JPEG quality, screen size
PREVIEW_FULL_QUALITY = 92    # JPEG quality, full resolution (zoomed in to check focus)
PREVIEW_CACHE_BYTES = 256 * 1024 * 1024
PREVIEW_SOURCE_CACHE_MAX = 5000

_preview_cache: OrderedDict = OrderedDict()   # (path, mtime, max_side) -> JPEG bytes
_preview_cache_bytes = 0
_preview_source_cache: OrderedDict = OrderedDict()   # (path, mtime) -> source description (no pixel data)
_preview_lock = threading.Lock()


def _upright_size(size, orientation):
    w, h = size
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def _resolve_source(filepath: str) -> dict:
    """Decide what a file's preview is rendered from, without decoding it:
    {'kind': 'file' | 'embedded' | 'sensor', ..., 'size': upright full-resolution (w, h)}.

    RAW files use the camera's embedded preview when it's a usable size (usually
    full resolution), else a same-name JPEG/HEIC companion, else the sensor
    data, the same order Blur Check scores them in.
    """
    from PIL import Image
    ext = Path(filepath).suffix.lower()
    if ext in VIDEO_EXTS:
        raise ValueError('Videos have no preview')
    if ext in RAW_EXTS:
        try:
            import rawpy
        except ImportError:
            rawpy = None
        if rawpy is not None:
            with rawpy.imread(filepath) as raw:
                flip = _RAW_FLIP_TO_ORIENTATION.get(raw.sizes.flip)
                try:
                    thumb = raw.extract_thumb()
                except Exception:
                    thumb = None
                if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                    if max(img.size) >= PREVIEW_MIN_EMBEDDED:
                        # Embedded previews are usually stored unrotated, with the
                        # camera's orientation recorded only in the RAW
                        orientation = img.getexif().get(_TAG_ORIENTATION)
                        if orientation in (None, 1):
                            orientation = flip
                        return {'kind': 'embedded', 'path': filepath, 'orientation': orientation,
                                'size': _upright_size(img.size, orientation)}
                companion = _find_companion(filepath)
                if companion:
                    return _resolve_source(companion)
                return {'kind': 'sensor', 'path': filepath,
                        'size': _upright_size((raw.sizes.width, raw.sizes.height), flip)}
        # No rawpy: Pillow reads some TIFF-based RAWs (often just a small thumbnail)
    if ext in HEIC_EXTS:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
    img = Image.open(filepath)
    orientation = _image_orientation(img, filepath)
    return {'kind': 'file', 'path': filepath, 'orientation': orientation,
            'size': _upright_size(img.size, orientation)}


def _source(filepath: str) -> dict:
    key = (filepath, os.path.getmtime(filepath))
    with _preview_lock:
        src = _preview_source_cache.get(key)
        if src is not None:
            _preview_source_cache.move_to_end(key)
            return src
    src = _resolve_source(filepath)   # slow-ish (RAW: ~50 ms); done outside the lock
    with _preview_lock:
        _preview_source_cache[key] = src
        if len(_preview_source_cache) > PREVIEW_SOURCE_CACHE_MAX:
            _preview_source_cache.popitem(last=False)
    return src


def _render(filepath: str, max_side: int) -> bytes:
    """JPEG bytes, upright, long side <= max_side (0: full resolution)."""
    from PIL import Image, ImageFile
    src = _source(filepath)
    ImageFile.LOAD_TRUNCATED_IMAGES = True   # damaged files still show what survived
    try:
        if src['kind'] == 'sensor':
            import rawpy
            with rawpy.imread(src['path']) as raw:
                half = bool(max_side) and max(src['size']) / 2 >= max_side
                img = Image.fromarray(raw.postprocess(      # already upright
                    half_size=half, use_camera_wb=True, output_bps=8))
            orientation = None
        else:
            if src['kind'] == 'embedded':
                import rawpy
                with rawpy.imread(src['path']) as raw:
                    img = Image.open(io.BytesIO(raw.extract_thumb().data))
            else:
                img = Image.open(src['path'])
            orientation = src['orientation']
            if max_side:
                img.draft('RGB', (max_side, max_side))   # fast DCT-domain downscale for JPEGs
        img = img.convert('RGB')
        if max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        img = _apply_orientation(img, orientation)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=PREVIEW_FULL_QUALITY if not max_side else PREVIEW_QUALITY)
        return buf.getvalue()
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False


def get_preview(filepath: str, full: bool) -> bytes:
    global _preview_cache_bytes
    max_side = 0 if full else PREVIEW_SIZE
    key = (filepath, os.path.getmtime(filepath), max_side)
    with _preview_lock:
        data = _preview_cache.get(key)
        if data is not None:
            _preview_cache.move_to_end(key)
            return data
    data = _render(filepath, max_side)   # slow; done outside the lock
    with _preview_lock:
        if key not in _preview_cache:
            _preview_cache[key] = data
            _preview_cache_bytes += len(data)
            while _preview_cache_bytes > PREVIEW_CACHE_BYTES and len(_preview_cache) > 1:
                _, old = _preview_cache.popitem(last=False)
                _preview_cache_bytes -= len(old)
    return data


def clear_preview_cache() -> int:
    global _preview_cache_bytes
    with _preview_lock:
        cleared = len(_preview_cache)
        _preview_cache.clear()
        _preview_source_cache.clear()
        _preview_cache_bytes = 0
    return cleared
