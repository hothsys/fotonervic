"""RAW integrity check."""

import io
import os
import re
import tempfile
import threading
from pathlib import Path

from backend.formats import NEF_EXTS, TIFF_RAW_EXTS
from backend.tiff import _find_best_embedded_preview, _parse_tiff_structure

# ─── RAW checker ──────────────────────────────────────────────────────────────

_stderr_lock = threading.Lock()

def check_raw(filepath: str):
    try:
        file_size = os.path.getsize(filepath)
        ext = Path(filepath).suffix.lower()

        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        # ── Structural analysis for TIFF-based RAW (NEF / ARW) ──────
        tiff = None
        if ext in TIFF_RAW_EXTS:
            tiff = _parse_tiff_structure(filepath)
            fmt_name = 'NEF' if ext in NEF_EXTS else 'ARW'

            if not tiff['valid_header']:
                if file_size < 100:
                    return 'corrupt', (
                        f'File too small to be valid {fmt_name} '
                        f'({file_size} bytes) and has no valid TIFF header')
                return 'corrupt', (
                    f'No valid TIFF/RAW header found; '
                    f'file data appears to be completely corrupt')

            if tiff['has_exif'] and not tiff['has_image_data_tags']:
                return 'exif_only', (
                    f'{fmt_name} file has valid TIFF structure and '
                    f'EXIF/camera metadata but no image data references, '
                    f'so image content was not recovered')

            if tiff['has_image_data_tags'] and not tiff['image_data_accessible']:
                return 'partial', (
                    f'{fmt_name} file has TIFF structure and image data '
                    f'references, but image data extends beyond end of '
                    f'file, so the file is truncated')

        # ── Full decode via rawpy ────────────────────────────────────
        rawpy_stderr = ''
        try:
            import rawpy

            # Capture stderr to get corruption offset from libraw.
            # Lock required because os.dup2 is process-wide.
            with _stderr_lock:
                tmp_fd, tmp_path = tempfile.mkstemp(suffix='.txt')
                old_stderr = os.dup(2)
                os.dup2(tmp_fd, 2)
                os.close(tmp_fd)
                try:
                    with rawpy.imread(filepath) as raw:
                        _ = raw.postprocess(
                            half_size=True,
                            use_camera_wb=True,
                            output_bps=8,
                        )
                finally:
                    os.dup2(old_stderr, 2)
                    os.close(old_stderr)
                    try:
                        with open(tmp_path) as _tf:
                            rawpy_stderr = _tf.read()
                    except Exception:
                        pass
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

            return 'ok', None

        except ImportError:
            # rawpy not installed: use structural results if available
            if tiff and tiff['valid_header'] and tiff['has_image_data_tags'] \
                    and tiff['image_data_accessible']:
                return 'ok', None

            # Fall back to PIL (many RAW files are TIFF containers)
            try:
                from PIL import Image
                img = Image.open(filepath)
                img.load()
                return 'ok', None
            except Exception as e:
                err_lower = str(e).lower()
                if 'cannot identify' in err_lower or 'format' in err_lower:
                    return 'unsupported', (
                        'RAW format check requires rawpy '
                        '(pip install rawpy). '
                        'PIL also could not read this file.')
                return 'corrupt', f'RAW read error (PIL fallback): {str(e)}'

        except Exception as e:
            err = str(e)
            err_lower = err.lower()

            # rawpy failed: check corruption severity and embedded
            # JPEG previews.  Parse stderr for the corruption offset
            # so we can tell whether damage is minor (tail end) or
            # severe (early in the file).
            corrupt_at = None
            m = re.search(r'data corrupted at (\d+)', rawpy_stderr)
            if m:
                corrupt_at = int(m.group(1))

            # Minor tail corruption: if damage is in the last 5% of
            # the file AND a full-res embedded preview is intact, the
            # file is usable by Photoshop / Lightroom.
            is_minor = (corrupt_at is not None
                        and file_size > 0
                        and corrupt_at / file_size > 0.95)

            # Corruption percentage: how much of the file is damaged
            corrupt_pct = None
            if corrupt_at is not None and file_size > 0:
                corrupt_pct = round(
                    (file_size - corrupt_at) / file_size * 100, 3)

            def _pct_str():
                if corrupt_pct is not None:
                    return f' (~{corrupt_pct}% of file corrupted)'
                return ''

            preview = _find_best_embedded_preview(filepath)
            if preview:
                pw, ph, p_off, p_len = preview
                try:
                    from PIL import Image as _PImg
                    with open(filepath, 'rb') as _pf:
                        _pf.seek(p_off)
                        _pdata = _pf.read(p_len)
                    _pimg = _PImg.open(io.BytesIO(_pdata))
                    _pimg.load()
                    is_full_res = pw >= 2000 and ph >= 1500

                    if is_full_res and is_minor:
                        return 'partial', (
                            f'Minor RAW data corruption near end of '
                            f'file{_pct_str()}; file is still usable '
                            f'with intact {pw}x{ph} embedded preview')
                    elif is_full_res:
                        return 'partial', (
                            f'RAW sensor data is damaged{_pct_str()} '
                            f'but file contains a full-resolution '
                            f'{pw}x{ph} embedded preview')
                    else:
                        return 'partial', (
                            f'RAW sensor data is damaged{_pct_str()} '
                            f'and file only contains a small '
                            f'{pw}x{ph} preview thumbnail')
                except Exception:
                    pass  # preview data also damaged

            # No usable embedded preview: try plain PIL
            try:
                from PIL import Image
                img = Image.open(filepath)
                img.load()
                w, h = img.size
                if w >= 2000 and h >= 1500 and is_minor:
                    return 'partial', (
                        f'Minor RAW data corruption near end of '
                        f'file{_pct_str()}; file is still usable '
                        f'with intact {w}x{h} preview')
                if w >= 2000 and h >= 1500:
                    return 'partial', (
                        f'RAW sensor data is damaged{_pct_str()} '
                        f'but a {w}x{h} preview is readable')
                return 'partial', (
                    f'RAW sensor data is damaged{_pct_str()} and '
                    f'only a small {w}x{h} preview is readable')
            except Exception:
                pass  # PIL also failed; continue to structural analysis

            # Use structural info to classify rawpy errors for NEF/ARW
            if tiff and tiff['valid_header']:
                fmt_name = 'NEF' if ext in NEF_EXTS else 'ARW'
                if tiff['has_exif'] and not tiff['has_image_data_tags']:
                    return 'exif_only', (
                        f'{fmt_name} file has EXIF/camera metadata but '
                        f'libraw cannot decode image data, so '
                        f'image content was not recovered')
                if not tiff['image_data_accessible']:
                    return 'partial', (
                        f'{fmt_name} file has valid structure but image '
                        f'data appears truncated: {err}')

            if 'unsupported' in err_lower or 'not supported' in err_lower:
                return 'unsupported', f'RAW variant not supported by libraw: {err}'
            if any(x in err_lower
                   for x in ('corrupt', 'data', 'truncated', 'bad')):
                return 'corrupt', f'RAW data error: {err}'
            return 'corrupt', f'RAW read error: {err}'

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'
