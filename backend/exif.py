"""EXIF extraction, orientation, and the Exif Info scan."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.config import WORKER_THREADS
from backend.formats import HEIC_EXTS, RAW_EXTS, SUPPORTED_EXTENSIONS, VIDEO_EXTS
from backend.integrity import check_integrity
from backend.integrity.heic import _parse_heif_structure

# ─── EXIF extraction ──────────────────────────────────────────────────────────

_EXIF_TAGS = {
    271:   'make',
    272:   'model',
    42036: 'lens',
    36867: 'date_original',
    306:   'date',
    34855: 'iso',
    33437: 'f_number',
    33434: 'shutter',
    37386: 'focal_length',
    37385: 'flash',
    40962: 'exif_width',
    40963: 'exif_height',
}


def _fmt_rational(val):
    """Convert IFDRational or tuple to float, None on error."""
    try:
        if hasattr(val, 'numerator'):
            return float(val.numerator) / float(val.denominator)
        if isinstance(val, tuple) and len(val) == 2:
            return float(val[0]) / float(val[1]) if val[1] else None
        return float(val)
    except (ZeroDivisionError, TypeError, ValueError):
        return None


def _fmt_shutter(val):
    f = _fmt_rational(val)
    if f is None:
        return None
    if f >= 1:
        return f'{f:.0f}s'
    denom = round(1 / f)
    return f'1/{denom}s'


def _fmt_aperture(val):
    f = _fmt_rational(val)
    return f'f/{f:.1f}' if f else None


def _fmt_focal(val):
    f = _fmt_rational(val)
    return f'{f:.0f}mm' if f else None


def _fmt_date(raw):
    if not raw:
        return None
    s = str(raw).strip()
    if len(s) >= 16 and ':' in s[:10]:
        return s[:10].replace(':', '-') + ' ' + s[11:16]
    return s[:16] if len(s) >= 16 else s


def _dms_to_decimal(dms, ref) -> float | None:
    """Convert GPS degrees/minutes/seconds tuple to signed decimal degrees."""
    try:
        d, m, s = [_fmt_rational(x) for x in dms]
        if d is None or m is None or s is None:
            return None
        val = d + m / 60.0 + s / 3600.0
        if ref in ('S', 'W'):
            val = -val
        return round(val, 6)
    except (TypeError, ValueError):
        return None


def _extract_pillow_exif(img):
    """Extract EXIF dict from an open PIL Image."""
    from PIL.ExifTags import TAGS, GPSTAGS
    result = {'has_exif': False}
    try:
        exif = img.getexif()
        if not exif:
            return result
        result['has_exif'] = True
        raw = {TAGS.get(k, k): v for k, v in exif.items()}

        result['make']         = str(raw.get('Make', '') or '').strip() or None
        result['model']        = str(raw.get('Model', '') or '').strip() or None
        result['lens']         = str(raw.get('LensModel', '') or '').strip() or None
        result['iso']          = int(raw['ISOSpeedRatings']) if 'ISOSpeedRatings' in raw else None
        result['aperture']     = _fmt_aperture(raw.get('FNumber'))
        result['shutter']      = _fmt_shutter(raw.get('ExposureTime'))
        result['focal_length'] = _fmt_focal(raw.get('FocalLength'))
        result['flash']        = bool(raw.get('Flash', 0)) if 'Flash' in raw else None

        date_raw = raw.get('DateTimeOriginal') or raw.get('DateTime')
        result['date'] = _fmt_date(date_raw)

        w = raw.get('ExifImageWidth') or raw.get('PixelXDimension')
        h = raw.get('ExifImageHeight') or raw.get('PixelYDimension')
        result['exif_width']  = int(w) if w else None
        result['exif_height'] = int(h) if h else None

        # GPS: read sub-IFD (tag 0x8825 = 34853)
        result['gps_lat'] = None
        result['gps_lng'] = None
        try:
            gps_ifd = exif.get_ifd(0x8825)
            if gps_ifd:
                gps = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
                lat = _dms_to_decimal(gps.get('GPSLatitude', ()), gps.get('GPSLatitudeRef', 'N'))
                lng = _dms_to_decimal(gps.get('GPSLongitude', ()), gps.get('GPSLongitudeRef', 'E'))
                if lat is not None and lng is not None:
                    result['gps_lat'] = lat
                    result['gps_lng'] = lng
        except Exception:
            pass

    except Exception:
        pass
    return result


# EXIF Orientation tag (0x0112). Values 5-8 mean the stored pixels are rotated
# 90 degrees, so width and height swap when displayed.
_TAG_ORIENTATION = 0x0112

# LibRaw's sizes.flip uses its own codes; map them to EXIF Orientation values
_RAW_FLIP_TO_ORIENTATION = {3: 3, 5: 8, 6: 6}


def _apply_orientation(img, orientation):
    """Rotate/flip img so it displays upright for the given EXIF Orientation."""
    from PIL import Image
    method = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(orientation)
    return img.transpose(method) if method is not None else img


def _image_orientation(img, filepath: str):
    """EXIF Orientation for an opened image, accounting for pillow-heif.

    pillow-heif resets the EXIF tag to 1 (moving the real value to
    info['original_orientation']) on the assumption that libheif already
    rotated the pixels. libheif only does that when the file has an
    'irot'/'imir' property; many HEICs (e.g. Lightroom exports) carry their
    rotation only in EXIF, so use the original value for those.
    """
    orientation = img.getexif().get(_TAG_ORIENTATION)
    if orientation in (None, 1) and img.info.get('original_orientation') not in (None, 1):
        heif = _parse_heif_structure(filepath)
        if heif is not None and not heif['has_transform']:
            orientation = img.info['original_orientation']
    return orientation


def extract_exif(filepath: str) -> dict:
    """Extract EXIF metadata from any supported image or video file."""
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    ext = Path(filepath).suffix.lower()
    result = {
        'has_exif': False,
        'make': None, 'model': None, 'lens': None,
        'date': None, 'iso': None, 'aperture': None,
        'shutter': None, 'focal_length': None, 'flash': None,
        'width': None, 'height': None,
        'gps_lat': None, 'gps_lng': None,
    }

    try:
        if ext in VIDEO_EXTS:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            return result  # no EXIF for video

        if ext in HEIC_EXTS:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass

        if ext in RAW_EXTS:
            # Try getting dimensions + basic EXIF via rawpy
            try:
                import rawpy
                with rawpy.imread(filepath) as raw:
                    h, w = raw.raw_image.shape[:2]
                    if raw.sizes.flip in (5, 6):  # portrait: rotated 90 degrees
                        w, h = h, w
                    result['width']  = w
                    result['height'] = h
            except Exception:
                pass
            # Also try Pillow for embedded JPEG EXIF (some RAW formats)
            try:
                img = Image.open(filepath)
                exif_data = _extract_pillow_exif(img)
                result.update(exif_data)
                if result['width'] is None:
                    result['width'], result['height'] = img.size
            except Exception:
                pass
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            return result

        # JPEG, PNG, TIFF, WebP, HEIC, BMP, GIF
        try:
            img = Image.open(filepath)
            img_w, img_h = img.size
            if _image_orientation(img, filepath) in (5, 6, 7, 8):
                img_w, img_h = img_h, img_w  # report as displayed, not as stored
            exif_data = _extract_pillow_exif(img)
            result.update(exif_data)
            # Prefer actual image dimensions over EXIF-reported ones
            result['width']  = img_w
            result['height'] = img_h
        except Exception:
            pass

    except Exception:
        pass
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False

    return result


# ─── EXIF directory scanner (generator) ───────────────────────────────────────

exif_state = {'running': False, 'cancel': None, 'results': []}


def exif_scan_gen(root_dir: str, cancel: threading.Event):
    root = Path(root_dir).expanduser().resolve()

    if not root.exists():
        yield {'type': 'error', 'message': f'Path not found: {root_dir}'}
        return
    if not root.is_dir():
        yield {'type': 'error', 'message': f'Not a directory: {root_dir}'}
        return

    yield {'type': 'status', 'message': 'Counting files…'}
    all_files = []
    for dp, dirs, files in os.walk(root, followlinks=False):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': 0, 'issues': 0}
            return
        dirs.sort()
        for f in sorted(files):
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                all_files.append((dp, f))

    total = len(all_files)
    yield {'type': 'total', 'total': total}

    scanned = 0
    start   = time.time()

    def _exif_worker(dp, fname):
        filepath = os.path.join(dp, fname)
        file_size = 0
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            pass
        exif = extract_exif(filepath)
        exif.update(check_integrity(filepath))
        return dp, fname, filepath, file_size, exif

    batch_size = WORKER_THREADS * 4
    for batch_start in range(0, total, batch_size):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': scanned}
            return

        batch = all_files[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
            futures = {
                executor.submit(_exif_worker, dp, fname): (dp, fname)
                for dp, fname in batch
            }

            for future in as_completed(futures):
                if cancel.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    yield {'type': 'cancelled', 'scanned': scanned}
                    return

                dp, fname, filepath, file_size, exif = future.result()
                scanned += 1

                yield {
                    'type':    'scanning',
                    'file':    fname,
                    'dir':     dp,
                    'scanned': scanned,
                    'total':   total,
                }

                event = {
                    'type':      'exif_result',
                    'filepath':  filepath,
                    'filename':  fname,
                    'dir':       dp,
                    'ext':       Path(fname).suffix.lower(),
                    'file_size': file_size,
                    'scanned':   scanned,
                    'total':     total,
                    **exif,
                }
                yield event

    elapsed = time.time() - start
    yield {'type': 'complete', 'scanned': scanned, 'elapsed': round(elapsed, 1)}
