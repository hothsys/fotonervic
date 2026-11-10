"""measure_blur: combines the measures into the 0..100 blur score."""

import math
from pathlib import Path

from backend.blur.calibration import (
    BLUR_DEFAULT_THRESHOLD,
    BLUR_MIN_SIZE,
    CAL_CURVE,
    CAL_CUT_AI,
    CAL_CUT_BASIC,
    CAL_QUALITY_MEAN,
    CAL_QUALITY_STD,
    CAL_SCALE,
    CAL_SHARP_MEAN,
    CAL_SHARP_STD,
    CAL_WEIGHT_AI,
    FINE_DETAIL_CUTOFF,
    FINE_DETAIL_MAX_QUALITY_Z,
    FINE_DETAIL_SCALE,
)
from backend.blur.loading import _load_working_image_with_source, _normalize_exposure
from backend.blur.quality_model import _quality_score
from backend.blur.sharpness import _fine_detail, _hand_built_sharpness
from backend.formats import RAW_EXTS

def measure_blur(filepath: str) -> dict:
    """Return blur_score (0 sharp .. 100 blurry), its components (sharpness,
    quality), method ('ai' or 'basic'), low_detail, and error (set when the
    image couldn't be read)."""
    result = {'blur_score': None, 'sharpness': None, 'quality': None, 'method': 'basic',
              'low_detail': False, 'error': None, 'scored_from': None,
              'fine_detail': None, 'fine_detail_flag': False}
    try:
        rgb, result['scored_from'] = _load_working_image_with_source(filepath)
    except Exception as e:
        result['error'] = f'Could not read image: {e}'
        return result
    if max(rgb.size) < BLUR_MIN_SIZE:
        result['error'] = f'Image too small to judge ({rgb.size[0]}x{rgb.size[1]})'
        if Path(filepath).suffix.lower() in RAW_EXTS:
            try:
                import rawpy  # noqa: F401
            except ImportError:
                result['error'] += '; install rawpy (pip install rawpy) to check RAW files'
        return result

    rgb = _normalize_exposure(rgb)
    sharpness = _hand_built_sharpness(rgb.convert('L'))
    try:
        quality = _quality_score(rgb)
    except Exception as e:
        quality = None
        result['error'] = f'AI quality model failed: {e}'

    z_sharp = None
    if sharpness is not None:
        result['sharpness'] = round(sharpness, 1)
        z_sharp = (math.log10(1 + sharpness) - CAL_SHARP_MEAN) / CAL_SHARP_STD
    else:
        result['low_detail'] = True      # fog, sky, blank wall: no edges to judge focus on

    if quality is not None:
        result['quality'] = round(quality, 4)
        result['method'] = 'ai'
        z_quality = (quality - CAL_QUALITY_MEAN) / CAL_QUALITY_STD
        z = z_quality if z_sharp is None else CAL_WEIGHT_AI * z_quality + (1 - CAL_WEIGHT_AI) * z_sharp
        cut = CAL_CUT_AI
    elif z_sharp is not None:
        z, cut = z_sharp, CAL_CUT_BASIC
    else:
        return result                    # low detail and no model: nothing to score
    # A logistic S-curve onto 0..100 rather than a hard clamp: it keeps 50 at
    # 50 with the same steepness there (so the threshold means the same thing),
    # but never saturates, so sharp photos stay ranked instead of all tying at
    # 0 (the user's likely-blurry burst frames differ from their sharp
    # siblings only out there).
    linear = BLUR_DEFAULT_THRESHOLD - CAL_SCALE * (z - cut)
    x = max(-60.0, min(60.0, (linear - BLUR_DEFAULT_THRESHOLD) / CAL_CURVE))
    score = 100.0 / (1.0 + math.exp(-x))

    # Fine-detail floor: very little fine detail flags the photo even when both
    # measures rate it ordinary (photos above the cutoff are unaffected), unless
    # the AI model rates it above average
    fine = _fine_detail(rgb.convert('L'))
    if fine is not None:
        result['fine_detail'] = round(fine, 3)
        vouched = quality is not None and z_quality > FINE_DETAIL_MAX_QUALITY_Z
        if fine < FINE_DETAIL_CUTOFF and not vouched:
            floor = 100.0 / (1.0 + math.exp(-(FINE_DETAIL_CUTOFF - fine) / FINE_DETAIL_SCALE))
            if floor > score:
                score = floor
                result['fine_detail_flag'] = True
    result['blur_score'] = round(score, 1)
    return result
