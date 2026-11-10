"""Loading the working copy Blur Check scores: RAW previews, companions,
sensor decode, and exposure normalization."""

import io
import math
import os
from pathlib import Path

from backend.blur.calibration import (
    BLUR_WORK_SIZE,
    COMPANION_EXTS,
    EXPOSURE_MIN_GAMMA,
    EXPOSURE_TARGET,
    SENSOR_UNSHARP,
)
from backend.exif import _RAW_FLIP_TO_ORIENTATION, _apply_orientation, _image_orientation
from backend.formats import HEIC_EXTS, RAW_EXTS

def _find_companion(filepath: str):
    stem = os.path.splitext(filepath)[0]
    for ext in COMPANION_EXTS:
        for candidate in (stem + ext, stem + ext.upper()):
            if os.path.isfile(candidate):
                return candidate
    return None


def _load_working_image(filepath: str):
    """RGB working copy, long side <= BLUR_WORK_SIZE, rotated upright."""
    return _load_working_image_with_source(filepath)[0]


def _load_working_image_with_source(filepath: str):
    """(working copy, scored_from) where scored_from is None for the file
    itself, or names what was used instead for a RAW with a tiny preview."""
    from PIL import Image, ImageFilter
    ext = Path(filepath).suffix.lower()
    img = None
    orientation = None
    scored_from = None
    if ext in RAW_EXTS:
        try:
            import rawpy
            with rawpy.imread(filepath) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        img = Image.open(io.BytesIO(thumb.data))
                    else:
                        img = Image.fromarray(thumb.data)
                    orientation = _RAW_FLIP_TO_ORIENTATION.get(raw.sizes.flip)
                except Exception:
                    img = None
                # Preview too small to judge focus: use a companion JPEG/HEIC,
                # else the sensor data (see COMPANION_EXTS in calibration.py)
                if img is None or max(img.size) < BLUR_WORK_SIZE:
                    companion = _find_companion(filepath)
                    if companion:
                        return _load_working_image(companion), 'companion: ' + os.path.basename(companion)
                    img = Image.fromarray(raw.postprocess(      # already upright
                        half_size=True, use_camera_wb=True, output_bps=8))
                    orientation = None
                    scored_from = 'RAW sensor data (preview too small)'
        except ImportError:
            img = None  # fall through to Pillow (TIFF-based RAWs)
    if img is None:
        if ext in HEIC_EXTS:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass
        img = Image.open(filepath)
        orientation = _image_orientation(img, filepath)
    img.draft('RGB', (BLUR_WORK_SIZE, BLUR_WORK_SIZE))   # fast DCT-domain downscale for JPEGs
    img = img.convert('RGB')
    img.thumbnail((BLUR_WORK_SIZE, BLUR_WORK_SIZE), Image.LANCZOS)
    if scored_from is not None:   # plain sensor decode: approximate the camera's sharpening
        radius, percent, threshold = SENSOR_UNSHARP
        img = img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))
    return _apply_orientation(img, orientation), scored_from


def _normalize_exposure(rgb):
    """Lift a dark working copy with a gamma curve (shadows lifted most), the
    way shadows/exposure would be raised in an editor. Never darkens."""
    import numpy as np
    from PIL import Image
    a = np.asarray(rgb, dtype=np.float32) / 255.0
    median = float(np.median(0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]))
    if median >= EXPOSURE_TARGET or median <= 0.002:
        return rgb
    gamma = max(EXPOSURE_MIN_GAMMA, math.log(EXPOSURE_TARGET) / math.log(median))
    return Image.fromarray(np.clip(255.0 * a ** gamma, 0, 255).astype(np.uint8))
