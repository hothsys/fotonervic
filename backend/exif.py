"""EXIF extraction, orientation, and the Exif Info scan."""

import os
import re
import threading
import time
from pathlib import Path

from backend.jobs import run_in_threads
from backend.exiftool import read_metadata
from backend.formats import HEIC_EXTS, RAW_EXTS, SUPPORTED_EXTENSIONS, VIDEO_EXTS
from backend.integrity import check_integrity
from backend.integrity.heic import _parse_heif_structure

# ─── EXIF extraction ──────────────────────────────────────────────────────────
# Metadata is read by ExifTool (backend/exiftool.py). The functions below are
# the basic built-in fallback for when it isn't available yet (e.g. while the
# app downloads it): Pillow's EXIF for JPEG, HEIC, TIFF, PNG, and the RAW files
# Pillow can open. RAW metadata is otherwise left to ExifTool, which keeps up
# with new cameras; don't extend this reader for new formats.

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
    """Exposure time the way cameras show it: 1/250s below 0.3 s, else
    seconds (0.3s, 1.3s, 30s)."""
    f = _fmt_rational(val)
    if not f or f <= 0:
        return None
    if f >= 0.3:
        return f'{f:.1f}'.rstrip('0').rstrip('.') + 's'
    return f'1/{round(1 / f)}s'


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


def _fmt_lens_spec(spec):
    """'24-70mm f/2.8-4' from LensSpecification / DNG LensInfo (min focal,
    max focal, min f-number at min focal, min f-number at max focal)."""
    try:
        f1, f2, a1, a2 = (_fmt_rational(v) for v in spec)
    except (TypeError, ValueError):
        return None
    if not f1:
        return None
    focal = f'{f1:.0f}mm' if not f2 or round(f1) == round(f2) else f'{f1:.0f}-{f2:.0f}mm'
    if not a1:
        return focal
    aperture = f'f/{a1:g}' if not a2 or a1 == a2 else f'f/{a1:g}-{a2:g}'
    return f'{focal} {aperture}'


def _clean_str(val):
    if isinstance(val, bytes):
        val = val.decode('utf-8', 'replace')
    s = str(val or '').split('\x00')[0].strip()   # C strings: anything after NUL is padding/garbage
    return s or None


# EXIF tags, by number. Exposure settings, lens, and capture time live in the
# Exif sub-IFD (0x8769), not in IFD0; some RAW formats put a few of them in
# IFD0, so each lookup tries the sub-IFD first, then IFD0.
_TAG_EXIF_IFD = 0x8769
_TAG_GPS_IFD = 0x8825
def _exif_fields(ifd0: dict, sub: dict, gps: dict) -> dict:
    """Normalized EXIF fields from the IFD0, Exif sub-IFD, and GPS sub-IFD
    tag dicts (keys are tag numbers)."""
    def tag(num):
        val = sub.get(num)
        return val if val is not None else ifd0.get(num)

    result = {'has_exif': bool(ifd0 or sub or gps)}
    if not result['has_exif']:
        return result

    result['make']  = _clean_str(ifd0.get(271))
    result['model'] = _clean_str(ifd0.get(272))
    result['lens']  = (_clean_str(tag(42036))                               # LensModel
                       or _fmt_lens_spec(tag(42034) or ifd0.get(50736)))    # LensSpecification / DNG LensInfo

    iso = tag(34855)                                 # PhotographicSensitivity (ISOSpeedRatings)
    if isinstance(iso, (tuple, list)):
        iso = iso[0] if iso else None
    if not iso or iso == 65535:                      # 65535: too high for the field; see ISOSpeed
        iso = tag(34867) or tag(34866)               # ISOSpeed, RecommendedExposureIndex
    try:
        result['iso'] = int(iso) if iso else None
    except (TypeError, ValueError):
        result['iso'] = None

    f_number = _fmt_rational(tag(33437)) if tag(33437) is not None else None
    if not f_number and tag(37378) is not None:      # ApertureValue (APEX)
        apex = _fmt_rational(tag(37378))
        f_number = 2 ** (apex / 2) if apex is not None else None
    result['aperture'] = _fmt_aperture(round(f_number, 1)) if f_number else None

    exposure = _fmt_rational(tag(33434)) if tag(33434) is not None else None
    if not exposure and tag(37377) is not None:      # ShutterSpeedValue (APEX)
        apex = _fmt_rational(tag(37377))
        exposure = 2 ** -apex if apex is not None else None
    result['shutter'] = _fmt_shutter(exposure) if exposure else None

    result['focal_length'] = _fmt_focal(tag(37386))
    flash = tag(37385)
    try:
        result['flash'] = bool(int(flash) & 1) if flash is not None else None   # bit 0: fired
    except (TypeError, ValueError):
        result['flash'] = None

    result['date'] = _fmt_date(_clean_str(tag(36867) or tag(36868) or ifd0.get(306)))  # taken, digitized, modified

    w, h = tag(40962), tag(40963)                    # PixelXDimension / PixelYDimension
    result['exif_width']  = int(w) if isinstance(w, int) and w else None
    result['exif_height'] = int(h) if isinstance(h, int) and h else None

    result['gps_lat'] = None
    result['gps_lng'] = None
    if gps:
        lat = _dms_to_decimal(gps.get(2, ()), _clean_str(gps.get(1)) or 'N')
        lng = _dms_to_decimal(gps.get(4, ()), _clean_str(gps.get(3)) or 'E')
        if lat is not None and lng is not None and (lat or lng):
            result['gps_lat'] = lat
            result['gps_lng'] = lng
    return result


def _exif_dirs(exif):
    """(IFD0, Exif sub-IFD, GPS sub-IFD) tag dicts from a PIL Image.Exif."""
    ifd0 = dict(exif)
    dirs = [ifd0]
    for pointer in (_TAG_EXIF_IFD, _TAG_GPS_IFD):
        try:
            dirs.append(dict(exif.get_ifd(pointer)))
        except Exception:
            dirs.append({})
    return tuple(dirs)


def _extract_pillow_exif(img):
    """Extract EXIF fields from an open PIL Image."""
    try:
        return _exif_fields(*_exif_dirs(img.getexif()))
    except Exception:
        return {'has_exif': False}


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


# Editors that strip camera metadata on export (e.g. Lightroom's "Include:
# Copyright Only") leave their own signature: an XMP toolkit, and sometimes the
# app's name (CreatorTool / Software). Saying so beats a bare "No EXIF".
_CAPTURE_FIELDS = ('make', 'model', 'date', 'iso', 'aperture', 'shutter', 'focal_length')


def _editor_name(value):
    """'Adobe Photoshop Lightroom Classic' from 'Adobe Photoshop Lightroom
    Classic 13.3.1 (Macintosh)'; None for values that aren't an app name
    (e.g. an iPhone's Software field, which is just the iOS version)."""
    # Cut at the version number ("13.3.1", "v2", "Ver.1.00"); camera firmware
    # strings like "Ver.1.00" leave nothing, so they don't count as an editor
    name = re.split(r'(?i)\s*\b(?:ver(?:sion)?|v)?\.?\s*\d', _clean_str(value) or '', maxsplit=1)[0].strip(' (,')
    return name if re.search(r'[A-Za-z]{3}', name) else None


def _metadata_note(fields: dict, toolkit, creator, software):
    """(kind, note) explaining missing camera metadata, or (None, None):
    'export' when an editor wrote the file without any camera metadata (e.g.
    Lightroom's "Include: Copyright Only"); 'no_camera' when the file just has
    no camera make or model (typical of photos saved from messaging or social
    apps, which strip them; also screenshots and scans)."""
    if not any(fields.get(k) for k in _CAPTURE_FIELDS):
        editor = _editor_name(creator) or _editor_name(software)
        if editor:
            return 'export', f'Camera metadata removed on export ({editor})'
        if 'adobe' in (_clean_str(toolkit) or '').lower():
            return 'export', 'Camera metadata removed on export (Lightroom or Photoshop)'
    if not (fields.get('make') or fields.get('model')):
        return 'no_camera', 'No camera details in this file'
    return None, None


def _exiftool_fields(meta: dict) -> dict:
    """Normalized fields from ExifTool's tags (see EXIFTOOL_TAGS)."""
    def num(key):
        val = meta.get(key)
        return val if isinstance(val, (int, float)) and not isinstance(val, bool) else None

    lens = _clean_str(meta.get('LensID'))
    if lens and lens.lower().startswith('unknown'):   # ExifTool couldn't decode the lens ID
        lens = None
    iso = re.match(r'\d+', str(meta.get('ISO', '')))
    flash = num('Flash')
    date = next((d for d in (_clean_str(meta.get(k)) for k in ('DateTimeOriginal', 'CreationDate', 'CreateDate', 'ModifyDate'))
                 if d and not d.startswith('0000')), None)   # see EXIFTOOL_TAGS
    lat, lng = num('GPSLatitude'), num('GPSLongitude')
    fields = {
        'make':         _clean_str(meta.get('Make')),
        'model':        _clean_str(meta.get('Model')),
        'lens':         lens or _clean_str(meta.get('LensModel')),
        'date':         _fmt_date(date),
        'iso':          int(iso.group()) if iso and int(iso.group()) else None,
        'aperture':     _fmt_aperture(round(num('FNumber'), 1)) if num('FNumber') else None,
        'shutter':      _fmt_shutter(num('ExposureTime')),
        'focal_length': _fmt_focal(num('FocalLength')),
        'flash':        bool(int(flash) & 1) if flash is not None else None,   # bit 0: fired
        'gps_lat':      round(lat, 6) if lat is not None and lng is not None and (lat or lng) else None,
        'gps_lng':      round(lng, 6) if lat is not None and lng is not None and (lat or lng) else None,
    }
    fields['has_exif'] = any(v is not None for v in fields.values())
    return fields


def extract_exif(filepath: str) -> dict:
    """Metadata of any supported image or video file. Read by ExifTool when
    it's available (backend/exiftool.py), else by the basic built-in reader;
    dimensions always come from the file itself (as displayed, so they match
    thumbnails). metadata_source says which reader was used."""
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
        'metadata_source': None,
        'metadata_note': None,
        'metadata_note_kind': None,
    }

    meta = read_metadata(filepath)            # None without ExifTool
    by_exiftool = bool(meta) and _exiftool_fields(meta)['has_exif']
    signature = ({'toolkit': meta.get('XMPToolkit'), 'creator': meta.get('CreatorTool'),
                  'software': meta.get('Software')} if meta else {})
    if by_exiftool:
        result.update(_exiftool_fields(meta))
        result['metadata_source'] = 'exiftool'

    def builtin(fields):
        # Built-in reader: only when ExifTool isn't available or found nothing
        if not by_exiftool and fields.get('has_exif'):
            result.update(fields)
            result['metadata_source'] = 'built-in'

    try:
        if ext in VIDEO_EXTS:
            if meta:   # only ExifTool reads video metadata
                w, h = meta.get('ImageWidth'), meta.get('ImageHeight')
                if isinstance(w, int) and isinstance(h, int) and w and h:
                    if meta.get('Rotation') in (90, 270):   # recorded in portrait
                        w, h = h, w
                    result['width'], result['height'] = w, h
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            return result

        if ext in HEIC_EXTS:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass

        if ext in RAW_EXTS:
            if not by_exiftool:
                try:                              # Pillow opens some TIFF-based RAWs (e.g. NEF)
                    with Image.open(filepath) as img:
                        builtin(_extract_pillow_exif(img))
                except Exception:
                    pass
            # Dimensions of the decoded image (LibRaw's sizes exclude the
            # masked sensor border that raw_image includes)
            try:
                import rawpy
                with rawpy.imread(filepath) as raw:
                    w, h = raw.sizes.width, raw.sizes.height
                    if raw.sizes.flip in (5, 6):  # portrait: rotated 90 degrees
                        w, h = h, w
                    result['width']  = w
                    result['height'] = h
            except Exception:
                pass
            if result['width'] is None:
                try:
                    with Image.open(filepath) as img:
                        result['width'], result['height'] = img.size
                except Exception:
                    pass
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            return result

        # JPEG, PNG, TIFF, WebP, HEIC, BMP, GIF
        try:
            with Image.open(filepath) as img:
                img_w, img_h = img.size
                if _image_orientation(img, filepath) in (5, 6, 7, 8):
                    img_w, img_h = img_h, img_w  # report as displayed, not as stored
                if not by_exiftool:
                    builtin(_extract_pillow_exif(img))
                    xmp = img.info.get('xmp') or b''
                    if isinstance(xmp, str):
                        xmp = xmp.encode('utf-8', 'replace')
                    creator = re.search(rb'CreatorTool="([^"]*)"|<xmp:CreatorTool>([^<]*)<', xmp)
                    signature = {
                        'toolkit': 'Adobe XMP Core' if b'Adobe XMP Core' in xmp else None,
                        'creator': (creator.group(1) or creator.group(2)).decode('utf-8', 'replace') if creator else None,
                        'software': img.getexif().get(305),
                    }
            # Prefer actual image dimensions over EXIF-reported ones
            result['width']  = img_w
            result['height'] = img_h
        except Exception:
            pass

    except Exception:
        pass
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False

    if ext not in VIDEO_EXTS and ext not in RAW_EXTS and result['width']:
        result['metadata_note_kind'], result['metadata_note'] = _metadata_note(
            result, **(signature or {'toolkit': None, 'creator': None, 'software': None}))
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

    # Check files on a pool of worker threads, kept busy (backend/jobs.py)
    for dp, fname, filepath, file_size, exif in run_in_threads(_exif_worker, all_files, cancel):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': scanned}
            return
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
