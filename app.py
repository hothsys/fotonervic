#!/usr/bin/env python3
"""
Photo Integrity Scanner
Recursively scans directories for corrupt or partial image files.
Detects: truncated files, missing image data, corrupt headers,
and files with EXIF metadata but no recoverable image content.
"""

import os
import sys
import json
import time
import struct
import threading
import csv
import io
import re
import subprocess
import webbrowser
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── Auto-install dependencies on first run ─────────────────────────────────

def _ensure_dependencies():
    """Install missing packages from requirements.txt automatically."""
    required = {
        'PIL':         'Pillow>=10.0.0',
        'rawpy':       'rawpy>=0.18.0',
        'pillow_heif': 'pillow-heif>=0.13.0',
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print(f'Installing missing dependencies: {", ".join(missing)}')
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '--quiet'] + missing,
        )
        print('Dependencies installed successfully.')

_ensure_dependencies()

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Global scan state ───────────────────────────────────────────────────────

scan_state = {
    'running': False,
    'cancelled': False,
    'results': [],
}

# ─── Supported formats ────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    # JPEG family
    '.jpg', '.jpeg', '.jpe', '.jfif',
    # PNG
    '.png',
    # HEIC / HEIF (Apple)
    '.heic', '.heif',
    # Nikon RAW
    '.nef', '.nrw',
    # Sony RAW
    '.arw', '.srf', '.sr2',
    # Canon RAW
    '.cr2', '.cr3',
    # Adobe DNG
    '.dng',
    # Fujifilm RAW
    '.raf',
    # Panasonic RAW
    '.rw2',
    # Olympus RAW
    '.orf',
    # Pentax RAW
    '.pef',
    # Samsung RAW
    '.srw',
    # TIFF
    '.tif', '.tiff',
    # WebP
    '.webp',
    # BMP
    '.bmp',
    # GIF
    '.gif',
    # Video — MP4 / MOV / AVI / MPEG
    '.mp4', '.m4v', '.mov',
    '.avi',
    '.mpg', '.mpeg',
}

JPEG_EXTS  = {'.jpg', '.jpeg', '.jpe', '.jfif'}
PNG_EXTS   = {'.png'}
HEIC_EXTS  = {'.heic', '.heif'}
RAW_EXTS   = {'.nef', '.nrw', '.arw', '.srf', '.sr2', '.cr2', '.cr3',
               '.dng', '.raf', '.rw2', '.orf', '.pef', '.srw'}
NEF_EXTS   = {'.nef', '.nrw'}
ARW_EXTS   = {'.arw', '.srf', '.sr2'}
TIFF_RAW_EXTS = NEF_EXTS | ARW_EXTS

VIDEO_EXTS = {'.mp4', '.m4v', '.mov', '.avi', '.mpg', '.mpeg'}
MP4_EXTS   = {'.mp4', '.m4v', '.mov'}
AVI_EXTS   = {'.avi'}
MPEG_EXTS  = {'.mpg', '.mpeg'}

# ─── JPEG checker ─────────────────────────────────────────────────────────────

def check_jpeg(filepath: str):
    try:
        file_size = os.path.getsize(filepath)

        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        if file_size < 4:
            return 'corrupt', f'File too small to be valid JPEG ({file_size} bytes)'

        with open(filepath, 'rb') as f:
            soi = f.read(2)
            if soi != b'\xff\xd8':
                return 'corrupt', 'Missing JPEG SOI marker — not a valid JPEG file'

            # Scan for APP1/EXIF segment
            header_chunk = f.read(min(2048, file_size - 2))
            has_exif = b'Exif\x00\x00' in header_chunk
            has_jfif = b'JFIF\x00' in header_chunk

            # Check for SOS (Start of Scan) marker — presence means image data exists
            f.seek(2)
            full_header = f.read(min(65536, file_size))
            has_sos = b'\xff\xda' in full_header

        # Specific case: has EXIF but no image scan data at all
        if has_exif and not has_sos:
            return 'exif_only', \
                'File contains EXIF/metadata but no image scan data — ' \
                'image content was not recovered'

        if not has_sos:
            return 'partial', \
                'No image scan data (SOS marker) found — image may be a bare header'

        # Full Pillow decode — the definitive test.
        # If .load() decompresses every pixel without error, the image
        # is complete regardless of whether an EOI marker is present.
        # (Many cameras/apps append large amounts of data after EOI.)
        try:
            from PIL import Image, ImageFile
            # Do NOT set LOAD_TRUNCATED_IMAGES so truncated files raise exceptions
            img = Image.open(filepath)
            img.load()
            return 'ok', None

        except Exception as e:
            err_msg = str(e)
            err_lower = err_msg.lower()
            if 'truncated' in err_lower or 'incomplete' in err_lower:
                return 'partial', f'Image data is truncated: {err_msg}'
            return 'corrupt', f'Decode error: {err_msg}'

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except OSError as e:
        return 'error', f'OS error: {str(e)}'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'


# ─── PNG checker ──────────────────────────────────────────────────────────────

PNG_SIG = b'\x89PNG\r\n\x1a\n'

def check_png(filepath: str):
    try:
        file_size = os.path.getsize(filepath)

        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        if file_size < 8:
            return 'corrupt', f'File too small to be valid PNG ({file_size} bytes)'

        with open(filepath, 'rb') as f:
            sig = f.read(8)
            if sig != PNG_SIG:
                return 'corrupt', 'Invalid PNG signature bytes'

            # Read first chunk (should be IHDR)
            length_bytes = f.read(4)
            chunk_type   = f.read(4)
            if chunk_type != b'IHDR':
                return 'corrupt', f'First PNG chunk is not IHDR (got {chunk_type})'

            # Check for IEND in the last 20 bytes
            f.seek(-20, 2)
            tail = f.read(20)

        if b'IEND' not in tail:
            return 'partial', \
                'Missing PNG IEND chunk — file is truncated (image data incomplete)'

        try:
            from PIL import Image
            img = Image.open(filepath)
            img.load()
            return 'ok', None
        except Exception as e:
            err_lower = str(e).lower()
            if 'truncated' in err_lower or 'decompression' in err_lower:
                return 'partial', f'PNG data truncated or corrupt: {str(e)}'
            return 'corrupt', f'Decode error: {str(e)}'

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'


# ─── HEIC / HEIF checker ──────────────────────────────────────────────────────

def check_heic(filepath: str):
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        # Try pillow-heif first
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            from PIL import Image
            img = Image.open(filepath)
            img.load()
            return 'ok', None
        except ImportError:
            pass  # Fall through to plain PIL attempt

        # Try plain PIL (works if system has HEIF support)
        try:
            from PIL import Image
            img = Image.open(filepath)
            img.load()
            return 'ok', None
        except Exception as e:
            err_lower = str(e).lower()
            if 'format' in err_lower or 'cannot identify' in err_lower:
                return 'unsupported', \
                    'HEIC/HEIF support unavailable — install pillow-heif ' \
                    '(pip install pillow-heif). File structure not verified.'
            if 'truncated' in err_lower:
                return 'partial', f'Truncated HEIC file: {str(e)}'
            return 'corrupt', f'HEIC decode error: {str(e)}'

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'


# ─── TIFF structure parser (for NEF / ARW) ──────────────────────────────────

# TIFF tag IDs relevant for RAW integrity analysis
_TAG_STRIP_OFFSETS     = 0x0111
_TAG_STRIP_BYTE_COUNTS = 0x0117
_TAG_TILE_OFFSETS      = 0x0144
_TAG_TILE_BYTE_COUNTS  = 0x0145
_TAG_SUB_IFDS          = 0x014A
_TAG_EXIF_IFD          = 0x8769
_TAG_MAKERNOTE         = 0x927C

# TIFF data type sizes (bytes per element) indexed by type code 1-12
_TIFF_TYPE_SIZES = {1:1, 2:1, 3:2, 4:4, 5:8, 6:1, 7:1, 8:2, 9:4, 10:8, 11:4, 12:8}


def _parse_tiff_structure(filepath: str) -> dict:
    """Analyse the TIFF container structure of a RAW file.

    Returns a dict describing what was found without reading image data.
    """
    result = {
        'valid_header': False,
        'byte_order': None,
        'ifd_count': 0,
        'has_exif': False,
        'has_makernote': False,
        'has_image_data_tags': False,
        'image_data_accessible': True,
        'has_sub_ifds': False,
        'file_size': 0,
        'error': None,
    }

    try:
        file_size = os.path.getsize(filepath)
        result['file_size'] = file_size

        if file_size < 8:
            result['error'] = 'File too small for TIFF header'
            return result

        with open(filepath, 'rb') as f:
            # ── Header ──────────────────────────────────────────────
            header = f.read(8)
            if len(header) < 8:
                result['error'] = 'Incomplete TIFF header'
                return result

            byte_order = header[0:2]
            if byte_order == b'II':
                endian = '<'
            elif byte_order == b'MM':
                endian = '>'
            else:
                result['error'] = f'Invalid byte order marker: {byte_order!r}'
                return result

            result['byte_order'] = byte_order.decode('ascii')

            magic = struct.unpack(f'{endian}H', header[2:4])[0]
            if magic != 42:
                result['error'] = f'Invalid TIFF magic number: {magic}'
                return result

            result['valid_header'] = True
            first_ifd_offset = struct.unpack(f'{endian}I', header[4:8])[0]

            # ── Walk IFD chain ──────────────────────────────────────
            visited_offsets = set()
            ifd_offset = first_ifd_offset
            found_strip_offsets = []
            found_strip_counts = []
            found_tile_offsets = []
            found_tile_counts = []
            sub_ifd_offsets = []  # collected for later traversal

            def _parse_ifd(f, ifd_off):
                """Parse one IFD, returning (next_ifd_offset, sub_ifd_list).
                Updates result dict and found_* lists as side effects."""
                nonlocal found_strip_offsets, found_strip_counts
                nonlocal found_tile_offsets, found_tile_counts

                if ifd_off in visited_offsets:
                    return 0, []
                if ifd_off + 2 > file_size:
                    result['error'] = f'IFD offset {ifd_off} past EOF'
                    return 0, []
                visited_offsets.add(ifd_off)

                f.seek(ifd_off)
                count_bytes = f.read(2)
                if len(count_bytes) < 2:
                    result['error'] = 'Truncated IFD entry count'
                    return 0, []

                entry_count = struct.unpack(f'{endian}H', count_bytes)[0]
                if entry_count > 1000:
                    result['error'] = f'Unreasonable IFD entry count: {entry_count}'
                    return 0, []

                entries_size = entry_count * 12
                if ifd_off + 2 + entries_size + 4 > file_size:
                    result['error'] = 'IFD entries extend past EOF'
                    entries_data = f.read(min(entries_size, file_size - f.tell()))
                else:
                    entries_data = f.read(entries_size)

                result['ifd_count'] += 1
                local_sub_ifds = []

                for i in range(min(entry_count, len(entries_data) // 12)):
                    entry = entries_data[i*12:(i+1)*12]
                    tag = struct.unpack(f'{endian}H', entry[0:2])[0]
                    dtype = struct.unpack(f'{endian}H', entry[2:4])[0]
                    count = struct.unpack(f'{endian}I', entry[4:8])[0]

                    if tag == _TAG_EXIF_IFD:
                        result['has_exif'] = True
                    elif tag == _TAG_MAKERNOTE:
                        result['has_makernote'] = True
                    elif tag == _TAG_SUB_IFDS:
                        result['has_sub_ifds'] = True
                        # Read SubIFD offsets
                        type_size = _TIFF_TYPE_SIZES.get(dtype, 4)
                        total_bytes = count * type_size
                        if total_bytes <= 4:
                            local_sub_ifds.append(
                                struct.unpack(f'{endian}I', entry[8:12])[0])
                        else:
                            ptr = struct.unpack(f'{endian}I', entry[8:12])[0]
                            if ptr + total_bytes <= file_size:
                                pos = f.tell()
                                f.seek(ptr)
                                for _ in range(count):
                                    d = f.read(4)
                                    if len(d) == 4:
                                        local_sub_ifds.append(
                                            struct.unpack(f'{endian}I', d)[0])
                                f.seek(pos)
                    elif tag == _TAG_STRIP_OFFSETS:
                        result['has_image_data_tags'] = True
                        _collect_offsets(f, entry, endian, dtype, count,
                                         file_size, found_strip_offsets)
                    elif tag == _TAG_STRIP_BYTE_COUNTS:
                        _collect_offsets(f, entry, endian, dtype, count,
                                         file_size, found_strip_counts)
                    elif tag == _TAG_TILE_OFFSETS:
                        result['has_image_data_tags'] = True
                        _collect_offsets(f, entry, endian, dtype, count,
                                         file_size, found_tile_offsets)
                    elif tag == _TAG_TILE_BYTE_COUNTS:
                        _collect_offsets(f, entry, endian, dtype, count,
                                         file_size, found_tile_counts)

                # Read next IFD offset
                next_ifd = 0
                next_offset_pos = ifd_off + 2 + entries_size
                if next_offset_pos + 4 <= file_size:
                    f.seek(next_offset_pos)
                    next_bytes = f.read(4)
                    if len(next_bytes) == 4:
                        next_ifd = struct.unpack(f'{endian}I', next_bytes)[0]

                return next_ifd, local_sub_ifds

            # Walk main IFD chain
            max_ifds = 20
            ifd_offset = first_ifd_offset
            while ifd_offset != 0 and result['ifd_count'] < max_ifds:
                next_ifd, subs = _parse_ifd(f, ifd_offset)
                sub_ifd_offsets.extend(subs)
                ifd_offset = next_ifd

            # Walk SubIFDs (e.g. ARW stores RAW strip data here)
            for soff in sub_ifd_offsets:
                if result['ifd_count'] >= max_ifds:
                    break
                _parse_ifd(f, soff)  # ignore next/sub from SubIFDs

            # ── Check image data accessibility ──────────────────────
            if found_strip_offsets and found_strip_counts:
                for off, sz in zip(found_strip_offsets, found_strip_counts):
                    if off + sz > file_size:
                        result['image_data_accessible'] = False
                        break
            elif found_tile_offsets and found_tile_counts:
                for off, sz in zip(found_tile_offsets, found_tile_counts):
                    if off + sz > file_size:
                        result['image_data_accessible'] = False
                        break
            elif result['has_image_data_tags']:
                # Had offset tags but couldn't read the counts — ambiguous
                pass

    except Exception as e:
        result['error'] = str(e)

    return result


def _collect_offsets(f, entry, endian, dtype, count, file_size, out_list):
    """Read offset/count values from a TIFF IFD entry into out_list."""
    type_size = _TIFF_TYPE_SIZES.get(dtype, 4)
    total_bytes = count * type_size

    if total_bytes <= 4:
        # Value fits in the entry's value/offset field
        raw = entry[8:8 + total_bytes]
    else:
        # Value is at an offset
        offset = struct.unpack(f'{endian}I', entry[8:12])[0]
        if offset + total_bytes > file_size:
            return
        pos = f.tell()
        f.seek(offset)
        raw = f.read(total_bytes)
        f.seek(pos)

    fmt_char = 'I' if type_size == 4 else ('H' if type_size == 2 else 'B')
    try:
        for i in range(count):
            val = struct.unpack(f'{endian}{fmt_char}',
                                raw[i*type_size:(i+1)*type_size])[0]
            out_list.append(val)
    except struct.error:
        pass


# ─── Embedded preview extraction ─────────────────────────────────────────────

_TAG_IMAGE_WIDTH       = 0x0100
_TAG_IMAGE_LENGTH      = 0x0101
_TAG_COMPRESSION       = 0x0103
_TAG_JPEG_IF_OFFSET    = 0x0201
_TAG_JPEG_IF_LENGTH    = 0x0202

def _find_best_embedded_preview(filepath: str):
    """Scan all TIFF IFDs and SubIFDs for the largest embedded JPEG preview.

    NEF stores previews in SubIFDs; ARW stores them in main IFDs (IFD2).
    This function checks both.

    Returns (width, height, jpeg_offset, jpeg_length) of the biggest
    preview found, or None if no usable preview exists.
    """
    try:
        file_size = os.path.getsize(filepath)
        if file_size < 8:
            return None

        with open(filepath, 'rb') as f:
            header = f.read(8)
            byte_order = header[0:2]
            if byte_order == b'II':
                endian = '<'
            elif byte_order == b'MM':
                endian = '>'
            else:
                return None

            magic = struct.unpack(f'{endian}H', header[2:4])[0]
            if magic != 42:
                return None

            first_ifd = struct.unpack(f'{endian}I', header[4:8])[0]

            best = None  # (width, height, offset, length)

            def _read_ifd_val(entry):
                """Read the scalar value from a TIFF IFD entry,
                respecting the data type (SHORT vs LONG)."""
                dtype = struct.unpack(f'{endian}H', entry[2:4])[0]
                if dtype == 3:  # SHORT — 2 bytes
                    return struct.unpack(f'{endian}H', entry[8:10])[0]
                return struct.unpack(f'{endian}I', entry[8:12])[0]

            def _check_ifd_for_preview(ifd_off):
                """Check a single IFD for JPEG preview data."""
                nonlocal best
                if ifd_off + 2 > file_size:
                    return
                f.seek(ifd_off)
                raw = f.read(2)
                if len(raw) < 2:
                    return
                ec = struct.unpack(f'{endian}H', raw)[0]
                if ec > 500:
                    return

                width = height = compression = jpeg_off = jpeg_len = 0
                for _ in range(ec):
                    entry = f.read(12)
                    if len(entry) < 12:
                        break
                    tag = struct.unpack(f'{endian}H', entry[0:2])[0]
                    val = _read_ifd_val(entry)

                    if tag == _TAG_IMAGE_WIDTH:
                        width = val
                    elif tag == _TAG_IMAGE_LENGTH:
                        height = val
                    elif tag == _TAG_COMPRESSION:
                        compression = val
                    elif tag == _TAG_JPEG_IF_OFFSET:
                        jpeg_off = val
                    elif tag == _TAG_JPEG_IF_LENGTH:
                        jpeg_len = val

                # Compression 6 = old-style JPEG, 7 = new-style JPEG
                if compression in (6, 7) and jpeg_off and jpeg_len:
                    if jpeg_off + jpeg_len <= file_size:
                        pixels = width * height if width and height else 0
                        if not best or pixels > best[0] * best[1]:
                            # If width/height not in IFD, decode JPEG header
                            if not width or not height:
                                pos = f.tell()
                                f.seek(jpeg_off)
                                jdata = f.read(min(jpeg_len, 65536))
                                f.seek(pos)
                                try:
                                    from PIL import Image as _Img
                                    tmp = _Img.open(io.BytesIO(jdata))
                                    width, height = tmp.size
                                except Exception:
                                    width = height = 0
                            if width and height:
                                best = (width, height, jpeg_off, jpeg_len)

            # Walk main IFD chain and collect SubIFD offsets
            sub_ifd_offsets = []
            ifd_offset = first_ifd
            visited = set()
            for _ in range(10):
                if not ifd_offset or ifd_offset in visited:
                    break
                if ifd_offset + 2 > file_size:
                    break
                visited.add(ifd_offset)

                # Check this main IFD for preview (ARW IFD2)
                _check_ifd_for_preview(ifd_offset)

                # Re-read to collect SubIFD pointers
                f.seek(ifd_offset)
                raw = f.read(2)
                if len(raw) < 2:
                    break
                entry_count = struct.unpack(f'{endian}H', raw)[0]
                if entry_count > 1000:
                    break

                for _ in range(entry_count):
                    entry = f.read(12)
                    if len(entry) < 12:
                        break
                    tag = struct.unpack(f'{endian}H', entry[0:2])[0]
                    dtype = struct.unpack(f'{endian}H', entry[2:4])[0]
                    count = struct.unpack(f'{endian}I', entry[4:8])[0]

                    if tag == _TAG_SUB_IFDS:
                        type_size = _TIFF_TYPE_SIZES.get(dtype, 4)
                        total = count * type_size
                        if total <= 4:
                            sub_ifd_offsets.append(
                                struct.unpack(f'{endian}I', entry[8:12])[0])
                        else:
                            ptr = struct.unpack(f'{endian}I', entry[8:12])[0]
                            if ptr + total <= file_size:
                                pos = f.tell()
                                f.seek(ptr)
                                for __ in range(count):
                                    d = f.read(4)
                                    if len(d) == 4:
                                        sub_ifd_offsets.append(
                                            struct.unpack(f'{endian}I', d)[0])
                                f.seek(pos)

                # Next IFD
                raw = f.read(4)
                if len(raw) < 4:
                    break
                ifd_offset = struct.unpack(f'{endian}I', raw)[0]

            # Check SubIFDs for previews (NEF)
            for soff in sub_ifd_offsets:
                _check_ifd_for_preview(soff)

            return best
    except Exception:
        return None


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
                    f'No valid TIFF/RAW header found — '
                    f'file data appears to be completely corrupt')

            if tiff['has_exif'] and not tiff['has_image_data_tags']:
                return 'exif_only', (
                    f'{fmt_name} file has valid TIFF structure and '
                    f'EXIF/camera metadata but no image data references '
                    f'— image content was not recovered')

            if tiff['has_image_data_tags'] and not tiff['image_data_accessible']:
                return 'partial', (
                    f'{fmt_name} file has TIFF structure and image data '
                    f'references, but image data extends beyond end of '
                    f'file — file is truncated')

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
            # rawpy not installed — use structural results if available
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

            # rawpy failed — check corruption severity and embedded
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

            # Corruption percentage — how much of the file is damaged
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
                            f'file{_pct_str()} — file is still usable '
                            f'with intact {pw}x{ph} embedded preview')
                    elif is_full_res:
                        return 'partial', (
                            f'RAW sensor data is damaged{_pct_str()} '
                            f'but file contains a full-resolution '
                            f'{pw}x{ph} embedded preview')
                    else:
                        return 'partial', (
                            f'RAW sensor data is damaged{_pct_str()} '
                            f'— file only contains a small '
                            f'{pw}x{ph} preview thumbnail')
                except Exception:
                    pass  # preview data also damaged

            # No usable embedded preview — try plain PIL
            try:
                from PIL import Image
                img = Image.open(filepath)
                img.load()
                w, h = img.size
                if w >= 2000 and h >= 1500 and is_minor:
                    return 'partial', (
                        f'Minor RAW data corruption near end of '
                        f'file{_pct_str()} — file is still usable '
                        f'with intact {w}x{h} preview')
                if w >= 2000 and h >= 1500:
                    return 'partial', (
                        f'RAW sensor data is damaged{_pct_str()} '
                        f'but a {w}x{h} preview is readable')
                return 'partial', (
                    f'RAW sensor data is damaged{_pct_str()} — '
                    f'only a small {w}x{h} preview is readable')
            except Exception:
                pass  # PIL also failed — continue to structural analysis

            # Use structural info to classify rawpy errors for NEF/ARW
            if tiff and tiff['valid_header']:
                fmt_name = 'NEF' if ext in NEF_EXTS else 'ARW'
                if tiff['has_exif'] and not tiff['has_image_data_tags']:
                    return 'exif_only', (
                        f'{fmt_name} file has EXIF/camera metadata but '
                        f'libraw cannot decode image data — '
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


# ─── Generic PIL checker (TIFF, WebP, BMP, GIF) ───────────────────────────────

def check_generic_pillow(filepath: str):
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        from PIL import Image
        img = Image.open(filepath)
        img.load()
        return 'ok', None

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        err_lower = str(e).lower()
        if 'truncated' in err_lower or 'incomplete' in err_lower:
            return 'partial', f'Image data truncated: {str(e)}'
        return 'corrupt', f'Decode error: {str(e)}'


# ─── MP4 / MOV / M4V checker (ISO Base Media File Format) ───────────────────

# Known ISOBMFF atom types (for validation)
_KNOWN_ATOMS = {
    b'ftyp', b'moov', b'mdat', b'free', b'skip', b'wide',
    b'pnot', b'moof', b'mfra', b'meta', b'styp', b'sidx',
    b'ssix', b'prft', b'uuid', b'pdin',
}


def check_mp4(filepath: str):
    try:
        file_size = os.path.getsize(filepath)

        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        if file_size < 8:
            return 'corrupt', f'File too small to be valid MP4/MOV ({file_size} bytes)'

        with open(filepath, 'rb') as f:
            has_ftyp = False
            has_moov = False
            has_mdat = False
            offset = 0
            atoms_checked = 0
            max_atoms = 500

            while offset < file_size and atoms_checked < max_atoms:
                f.seek(offset)
                header = f.read(8)
                if len(header) < 8:
                    break

                size = struct.unpack('>I', header[0:4])[0]
                atom_type = header[4:8]

                # 64-bit extended size
                if size == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        return 'partial', \
                            'Truncated atom header — file cut off mid-atom'
                    size = struct.unpack('>Q', ext)[0]

                # size 0 means atom extends to EOF (valid for last atom)
                if size == 0:
                    size = file_size - offset

                if size < 8:
                    # First atom invalid — not an MP4/MOV file
                    if atoms_checked == 0:
                        return 'corrupt', \
                            'No valid MP4/MOV container structure found'
                    break

                # Validate first atom looks like a real ISOBMFF atom
                if atoms_checked == 0:
                    if atom_type not in _KNOWN_ATOMS:
                        return 'corrupt', \
                            'No valid MP4/MOV container structure found'

                # Unknown atom after essential atoms found — trailing garbage,
                # stop walking (cameras occasionally write junk after moov)
                if atom_type not in _KNOWN_ATOMS and has_moov:
                    break

                if atom_type == b'ftyp':
                    has_ftyp = True
                elif atom_type == b'moov':
                    has_moov = True
                elif atom_type == b'mdat':
                    has_mdat = True

                # Check if atom extends past EOF — only flag essential atoms;
                # garbage trailers with implausible sizes are silently ignored
                if offset + size > file_size:
                    if atom_type not in _KNOWN_ATOMS:
                        break  # trailing junk, not a truncation
                    atom_name = atom_type.decode('ascii', errors='replace')
                    return 'partial', (
                        f'File is truncated — {atom_name!r} atom declares '
                        f'{size:,} bytes but only '
                        f'{file_size - offset:,} remain in file')

                offset += size
                atoms_checked += 1

        if atoms_checked == 0:
            return 'corrupt', 'No valid MP4/MOV container structure found'

        if not has_moov:
            return 'corrupt', (
                'No moov atom (metadata/index) — file is unplayable. '
                'The moov atom may have been at the end of the file '
                'and lost to truncation')

        if has_moov and not has_mdat:
            return 'partial', (
                'Has moov (metadata) but no mdat (media data) — '
                'video content is missing')

        return 'ok', None

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'


# ─── AVI checker (RIFF container) ───────────────────────────────────────────

def check_avi(filepath: str):
    try:
        file_size = os.path.getsize(filepath)

        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        if file_size < 12:
            return 'corrupt', \
                f'File too small to be valid AVI ({file_size} bytes)'

        with open(filepath, 'rb') as f:
            header = f.read(12)

            # RIFF header + AVI type
            if header[0:4] != b'RIFF':
                return 'corrupt', 'Missing RIFF header — not a valid AVI file'

            riff_type = header[8:12]
            if riff_type not in (b'AVI ', b'AVIX'):
                return 'corrupt', (
                    f'RIFF type is {riff_type!r}, not AVI — '
                    f'not a valid AVI file')

            # Declared RIFF size (excludes the 8-byte RIFF header itself)
            riff_size = struct.unpack('<I', header[4:8])[0]
            declared_size = riff_size + 8

            # Scan for key sub-chunks in the first portion of the file
            # AVI uses LIST chunks with sub-types
            scan_limit = min(file_size, 256 * 1024)  # first 256 KB
            f.seek(12)
            scan_data = f.read(scan_limit - 12)

            has_hdrl = b'hdrl' in scan_data
            has_movi = b'movi' in scan_data

            if not has_hdrl:
                return 'corrupt', (
                    'Missing AVI header list (hdrl) — '
                    'file structure is invalid')

            # Check truncation: file significantly smaller than declared
            if file_size < declared_size - 2:
                pct = round((1 - file_size / declared_size) * 100, 1)
                if not has_movi:
                    return 'partial', (
                        f'File is truncated ({file_size:,} of '
                        f'{declared_size:,} bytes, ~{pct}% missing) '
                        f'and video data (movi) is missing')
                return 'partial', (
                    f'File is truncated — {file_size:,} of '
                    f'{declared_size:,} declared bytes '
                    f'(~{pct}% of data missing)')

            if not has_movi:
                return 'partial', (
                    'Has AVI header but no video data chunk (movi) — '
                    'video content is missing')

            return 'ok', None

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'


# ─── MPEG Program Stream checker ────────────────────────────────────────────

# Valid MPEG-PS start code IDs
_MPEG_START_CODES = set(range(0xB9, 0x100))  # 0xB9..0xFF


def check_mpeg(filepath: str):
    try:
        file_size = os.path.getsize(filepath)

        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        if file_size < 12:
            return 'corrupt', \
                f'File too small to be valid MPEG ({file_size} bytes)'

        with open(filepath, 'rb') as f:
            # Check for MPEG pack start code (00 00 01 BA)
            header = f.read(4)
            if header != b'\x00\x00\x01\xba':
                # Could be an MPEG elementary stream — check for any
                # valid start code
                if header[:3] == b'\x00\x00\x01' \
                        and header[3] in _MPEG_START_CODES:
                    pass  # valid MPEG start code, continue
                else:
                    return 'corrupt', (
                        'No MPEG start code found — '
                        'not a valid MPEG file')

            # Scan first 64 KB for valid start codes to confirm
            # this is a real MPEG file (not just random data that
            # happens to start with 00 00 01)
            f.seek(0)
            scan_size = min(file_size, 65536)
            scan_data = f.read(scan_size)

            start_code_count = 0
            i = 0
            while i < len(scan_data) - 3:
                if scan_data[i] == 0 and scan_data[i+1] == 0 \
                        and scan_data[i+2] == 1 \
                        and scan_data[i+3] in _MPEG_START_CODES:
                    start_code_count += 1
                    i += 4
                else:
                    i += 1

            if start_code_count < 2:
                return 'corrupt', (
                    'Too few valid MPEG start codes — '
                    'file data appears corrupt')

            # Check for MPEG program end code (00 00 01 B9) at end
            f.seek(max(0, file_size - 64))
            tail = f.read(64)
            has_end_code = b'\x00\x00\x01\xb9' in tail

            if not has_end_code:
                return 'partial', (
                    'Missing MPEG program end code — '
                    'file is likely truncated')

            return 'ok', None

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'


# ─── Video dispatcher ────────────────────────────────────────────────────────

def check_video(filepath: str):
    ext = Path(filepath).suffix.lower()
    if ext in MP4_EXTS:
        return check_mp4(filepath)
    elif ext in AVI_EXTS:
        return check_avi(filepath)
    elif ext in MPEG_EXTS:
        return check_mpeg(filepath)
    return 'error', 'Unknown video format'


# ─── Dispatcher ───────────────────────────────────────────────────────────────

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


# ─── Directory scanner (generator) ────────────────────────────────────────────

WORKER_THREADS = 4

def scan_directory_gen(root_dir: str):
    root = Path(root_dir).expanduser().resolve()

    if not root.exists():
        yield {'type': 'error', 'message': f'Path not found: {root_dir}'}
        return
    if not root.is_dir():
        yield {'type': 'error', 'message': f'Not a directory: {root_dir}'}
        return

    # Count total files first
    yield {'type': 'status', 'message': 'Counting image files…'}
    all_files = []
    for dp, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for f in sorted(files):
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                all_files.append((dp, f))

    total = len(all_files)
    yield {'type': 'total', 'total': total}

    scanned = 0
    issues  = 0
    start   = time.time()

    def _check_worker(dp, fname):
        """Run check_image in a worker thread."""
        filepath = os.path.join(dp, fname)
        file_size = 0
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            pass
        status, reason = check_image(filepath)
        return dp, fname, filepath, file_size, status, reason

    # Process files in batches using a thread pool
    batch_size = WORKER_THREADS * 4
    for batch_start in range(0, total, batch_size):
        if scan_state['cancelled']:
            yield {'type': 'cancelled', 'scanned': scanned, 'issues': issues}
            return

        batch = all_files[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
            futures = {
                executor.submit(_check_worker, dp, fname): (dp, fname)
                for dp, fname in batch
            }

            for future in as_completed(futures):
                if scan_state['cancelled']:
                    executor.shutdown(wait=False, cancel_futures=True)
                    yield {'type': 'cancelled', 'scanned': scanned, 'issues': issues}
                    return

                dp, fname, filepath, file_size, status, reason = future.result()
                scanned += 1

                yield {
                    'type':    'scanning',
                    'file':    fname,
                    'dir':     dp,
                    'scanned': scanned,
                    'total':   total,
                    'issues':  issues,
                }

                if status != 'ok':
                    issues += 1
                    # Extract corruption percentage from reason if present
                    corrupt_pct = None
                    if reason:
                        pct_m = re.search(r'~([\d.]+)% of file corrupted', reason)
                        if pct_m:
                            corrupt_pct = float(pct_m.group(1))
                    event = {
                        'type':      'issue',
                        'filepath':  filepath,
                        'filename':  fname,
                        'dir':       dp,
                        'ext':       Path(fname).suffix.lower(),
                        'file_size': file_size,
                        'status':    status,
                        'reason':    reason,
                        'scanned':   scanned,
                        'issues':    issues,
                    }
                    if corrupt_pct is not None:
                        event['corrupt_pct'] = corrupt_pct
                    yield event

    elapsed = time.time() - start
    yield {
        'type':    'complete',
        'scanned': scanned,
        'issues':  issues,
        'elapsed': round(elapsed, 1),
    }


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

        # GPS — read sub-IFD (tag 0x8825 = 34853)
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

exif_state = {'running': False, 'cancelled': False, 'results': []}

# Thumbnail cache — OrderedDict used as simple LRU (max 1000 entries)
from collections import OrderedDict
_thumbnail_cache: OrderedDict = OrderedDict()
_THUMBNAIL_CACHE_MAX = 1000
_THUMBNAIL_SIZE = 300  # max px on either axis


def _generate_thumbnail(filepath: str) -> bytes | None:
    """Return JPEG thumbnail bytes, or None on failure."""
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    ext = Path(filepath).suffix.lower()
    try:
        img = None

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
                        else:
                            img = Image.fromarray(thumb.data)
                    except Exception:
                        rgb = raw.postprocess(
                            use_camera_wb=True, half_size=True, output_bps=8)
                        img = Image.fromarray(rgb)
            except Exception:
                pass

        if img is None:
            img = Image.open(filepath)

        img.thumbnail((_THUMBNAIL_SIZE, _THUMBNAIL_SIZE), Image.LANCZOS)
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


def exif_scan_gen(root_dir: str):
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
        return dp, fname, filepath, file_size, exif

    batch_size = WORKER_THREADS * 4
    for batch_start in range(0, total, batch_size):
        if exif_state['cancelled']:
            yield {'type': 'cancelled', 'scanned': scanned}
            return

        batch = all_files[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
            futures = {
                executor.submit(_exif_worker, dp, fname): (dp, fname)
                for dp, fname in batch
            }

            for future in as_completed(futures):
                if exif_state['cancelled']:
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
                exif_state['results'].append(event)
                yield event

    elapsed = time.time() - start
    yield {'type': 'complete', 'scanned': scanned, 'elapsed': round(elapsed, 1)}


# ─── HTTP handler ─────────────────────────────────────────────────────────────

class ScannerHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, data, mimetype, filename):
        self.send_response(200)
        self.send_header('Content-Type', mimetype)
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('X-Filename', filename)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _query_params(self):
        return parse_qs(urlparse(self.path).query)

    def _route_path(self):
        return urlparse(self.path).path

    # ── GET routes ──

    def do_GET(self):
        path = self._route_path()
        try:
            if path == '/api/scan':
                self._handle_scan()
            elif path == '/api/export':
                self._handle_export()
            elif path == '/api/browse':
                self._handle_browse()
            elif path == '/api/libs':
                self._handle_libs()
            elif path == '/api/mount-status':
                self._handle_mount_status()
            elif path == '/api/exif-scan':
                self._handle_exif_scan()
            elif path == '/api/thumbnail':
                self._handle_thumbnail()
            else:
                super().do_GET()
        except (ConnectionResetError, BrokenPipeError):
            pass

    # ── POST routes ──

    def do_POST(self):
        path = self._route_path()
        try:
            if path == '/api/cancel':
                self._handle_cancel()
            elif path == '/api/exif-cancel':
                self._handle_exif_cancel()
            elif path == '/api/reveal':
                self._handle_reveal()
            elif path == '/api/extract-preview':
                self._handle_extract_preview()
            elif path == '/api/repair-jpeg':
                self._handle_repair_jpeg()
            elif path == '/api/salvage-image':
                self._handle_salvage_image()
            else:
                self.send_error(404)
        except (ConnectionResetError, BrokenPipeError):
            pass

    # ── Handler methods ──

    def _handle_scan(self):
        params = self._query_params()
        root_dir = params.get('dir', [''])[0].strip()
        if not root_dir:
            return self._send_json({'error': 'No directory specified'}, 400)

        scan_state['cancelled'] = False
        scan_state['running']   = True
        scan_state['results']   = []

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        try:
            for event in scan_directory_gen(root_dir):
                if event.get('type') == 'issue':
                    scan_state['results'].append(event)
                line = f"data: {json.dumps(event)}\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            scan_state['running'] = False

    def _handle_cancel(self):
        scan_state['cancelled'] = True
        self._send_json({'ok': True})

    def _handle_exif_cancel(self):
        exif_state['cancelled'] = True
        self._send_json({'ok': True})

    def _handle_thumbnail(self):
        params = self._query_params()
        filepath = params.get('path', [''])[0].strip()

        if not filepath or not os.path.exists(filepath):
            self.send_error(404)
            return

        if filepath in _thumbnail_cache:
            _thumbnail_cache.move_to_end(filepath)
            data = _thumbnail_cache[filepath]
        else:
            data = _generate_thumbnail(filepath)
            if data is None:
                self.send_error(404)
                return
            _thumbnail_cache[filepath] = data
            _thumbnail_cache.move_to_end(filepath)
            if len(_thumbnail_cache) > _THUMBNAIL_CACHE_MAX:
                _thumbnail_cache.popitem(last=False)

        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        self.wfile.write(data)

    def _handle_exif_scan(self):
        params = self._query_params()
        root_dir = params.get('dir', [''])[0].strip()
        if not root_dir:
            return self._send_json({'error': 'No directory specified'}, 400)

        exif_state['cancelled'] = False
        exif_state['running']   = True
        exif_state['results']   = []

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        try:
            for event in exif_scan_gen(root_dir):
                line = f"data: {json.dumps(event, default=str)}\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            exif_state['running'] = False

    def _handle_export(self):
        results = scan_state.get('results', [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Status', 'Filename', 'Extension', 'Directory',
                         'Full Path', 'File Size (bytes)', 'Corruption %', 'Issue'])
        for r in results:
            writer.writerow([
                r.get('status',''),
                r.get('filename',''),
                r.get('ext',''),
                r.get('dir',''),
                r.get('filepath',''),
                r.get('file_size',''),
                r.get('corrupt_pct',''),
                r.get('reason',''),
            ])

        output.seek(0)
        # UTF-8 BOM so Excel interprets unicode characters (em dashes, etc.) correctly
        csv_str = '\ufeff' + output.getvalue()
        body = csv_str.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition',
                         'attachment; filename=photo_scan_results.csv')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_browse(self):
        params = self._query_params()
        raw = params.get('path', [''])[0].strip()
        target = Path(raw).expanduser().resolve() if raw else Path.home()

        if not target.exists() or not target.is_dir():
            target = Path.home()

        try:
            dirs = sorted([
                d.name for d in target.iterdir()
                if d.is_dir() and not d.name.startswith('.')
            ], key=str.lower)
        except PermissionError:
            dirs = []

        parent = str(target.parent) if target != target.parent else None
        self._send_json({
            'current': str(target),
            'parent': parent,
            'dirs': dirs,
        })

    def _handle_reveal(self):
        data = self._read_json_body()
        target = data.get('path', '')
        if not target or not os.path.exists(target):
            return self._send_json({'error': 'Path not found'}, 404)

        try:
            if sys.platform == 'darwin':
                if os.path.isfile(target):
                    subprocess.Popen(['open', '-R', target])
                else:
                    subprocess.Popen(['open', target])
            elif sys.platform == 'win32':
                if os.path.isfile(target):
                    subprocess.Popen(['explorer', '/select,', target])
                else:
                    subprocess.Popen(['explorer', target])
            else:
                parent = os.path.dirname(target) if os.path.isfile(target) else target
                subprocess.Popen(['xdg-open', parent])
            self._send_json({'ok': True})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_extract_preview(self):
        data = self._read_json_body()
        filepath = data.get('filepath', '')

        if not filepath or not os.path.exists(filepath):
            return self._send_json({'error': 'File not found'}, 404)

        ext = Path(filepath).suffix.lower()
        if ext not in RAW_EXTS:
            return self._send_json({'error': 'Not a RAW file'}, 400)

        preview = _find_best_embedded_preview(filepath)
        if not preview:
            return self._send_json({'error': 'No embedded preview found'}, 404)

        pw, ph, p_off, p_len = preview

        try:
            with open(filepath, 'rb') as f:
                f.seek(p_off)
                jpeg_bytes = f.read(p_len)
        except Exception as e:
            return self._send_json({'error': f'Read error: {e}'}, 500)

        stem = Path(filepath).stem
        filename = f'{stem}_preview.jpg'
        self._send_file(jpeg_bytes, 'image/jpeg', filename)

    def _handle_repair_jpeg(self):
        data = self._read_json_body()
        filepath = data.get('filepath', '')

        if not filepath or not os.path.exists(filepath):
            return self._send_json({'error': 'File not found'}, 404)

        ext = Path(filepath).suffix.lower()
        if ext not in JPEG_EXTS:
            return self._send_json({'error': 'Not a JPEG file'}, 400)

        # Decode the truncated image — Pillow can recover all pixel data
        # even when the compressed stream is incomplete
        try:
            from PIL import Image, ImageFile
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            img = Image.open(filepath)
            img.load()
        except Exception as e:
            return self._send_json({
                'error': f'Cannot decode image for repair: {e}'
            }, 422)

        # Preserve EXIF and ICC profile
        exif_data = img.info.get('exif', b'')
        icc_profile = img.info.get('icc_profile', None)

        # Re-encode as a structurally clean JPEG
        save_kwargs = {'quality': 100, 'optimize': True}
        if exif_data:
            save_kwargs['exif'] = exif_data
        if icc_profile:
            save_kwargs['icc_profile'] = icc_profile

        buf = io.BytesIO()
        img.save(buf, 'JPEG', **save_kwargs)

        # Verify the result decodes cleanly in strict mode
        buf.seek(0)
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            verify = Image.open(buf)
            verify.load()
        except Exception as e:
            return self._send_json({
                'error': f'Repair produced an invalid file: {e}'
            }, 422)

        buf.seek(0)
        repaired_bytes = buf.read()

        stem = Path(filepath).stem
        suffix = Path(filepath).suffix
        filename = f'{stem}_repaired{suffix}'
        self._send_file(repaired_bytes, 'image/jpeg', filename)

    def _handle_salvage_image(self):
        data = self._read_json_body()
        filepath = data.get('filepath', '')

        if not filepath or not os.path.exists(filepath):
            return self._send_json({'error': 'File not found'}, 404)

        ext = Path(filepath).suffix.lower()
        if ext not in JPEG_EXTS:
            return self._send_json({'error': 'Not a JPEG file'}, 400)

        try:
            image_bytes, filename = salvage_jpeg(filepath)
        except ValueError as e:
            return self._send_json({'error': str(e)}, 422)
        except Exception as e:
            return self._send_json({'error': f'Salvage failed: {e}'}, 500)

        self._send_file(image_bytes, 'image/jpeg', filename)

    def _handle_libs(self):
        status = {}
        try:
            from PIL import Image
            status['pillow'] = True
        except ImportError:
            status['pillow'] = False

        try:
            import rawpy
            status['rawpy'] = True
        except ImportError:
            status['rawpy'] = False

        try:
            import pillow_heif
            status['pillow_heif'] = True
        except ImportError:
            status['pillow_heif'] = False

        self._send_json(status)

    def _handle_mount_status(self):
        params = self._query_params()
        path = params.get('path', [''])[0].strip()
        if not path:
            return self._send_json({'error': 'No path specified'}, 400)

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        last_exists = None
        try:
            while True:
                # os.path.exists() can return True for empty mount-point dirs
                # that macOS leaves behind after ejecting a volume. Verify the
                # path is a non-empty accessible directory to avoid false positives.
                try:
                    exists = os.path.isdir(path) and next(os.scandir(path), None) is not None
                except OSError:
                    exists = False
                if exists != last_exists:
                    last_exists = exists
                    event = json.dumps({'exists': exists, 'path': path})
                    self.wfile.write(f"data: {event}\n\n".encode())
                    self.wfile.flush()
                time.sleep(3)
        except (ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, format, *args):
        pass  # Suppress default access log noise


# ─── JPEG salvage (donor-table grafting + MCU remap) ─────────────────────────

def _extract_donor_tables(data: bytes):
    """Extract DQT/DHT/SOF0/SOS segments from a JPEG, skipping APP segments."""
    pos = 2  # skip SOI
    pre_sos = []
    sos_segment = None
    sof_info = None  # (width, height, mcu_w, mcu_h)
    while pos < len(data) - 1:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xD9:
            break
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if pos + 3 >= len(data):
            break
        seg_len = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        segment = data[pos:pos + 2 + seg_len]
        if 0xE0 <= marker <= 0xEF:
            pos += 2 + seg_len
            continue
        if marker == 0xC0:  # SOF0
            h = struct.unpack('>H', segment[5:7])[0]
            w = struct.unpack('>H', segment[7:9])[0]
            ncomp = segment[9]
            max_h = max_v = 1
            for c in range(ncomp):
                ci = 10 + c * 3
                sampling = segment[ci + 1]
                max_h = max(max_h, sampling >> 4)
                max_v = max(max_v, sampling & 0xF)
            sof_info = (w, h, max_h * 8, max_v * 8)
            pre_sos.append(segment)
        elif marker == 0xDA:  # SOS
            sos_segment = segment
            break
        else:
            pre_sos.append(segment)
        pos += 2 + seg_len
    return pre_sos, sos_segment, sof_info


def _find_donor(directory: str, damaged_path: str):
    """Find a valid JPEG in the same directory to use as table donor."""
    damaged_name = os.path.basename(damaged_path)
    candidates = []
    try:
        for fname in os.listdir(directory):
            if fname == damaged_name:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in JPEG_EXTS:
                candidates.append(os.path.join(directory, fname))
    except OSError:
        return None, None, None

    for cpath in sorted(candidates):
        try:
            with open(cpath, 'rb') as f:
                header = f.read(2)
                if header != b'\xff\xd8':
                    continue
                f.seek(0)
                donor_data = f.read()
            pre_sos, sos_seg, sof_info = _extract_donor_tables(donor_data)
            if pre_sos and sos_seg and sof_info:
                return pre_sos, sos_seg, sof_info
        except (OSError, Exception):
            continue
    return None, None, None


def salvage_jpeg(filepath: str):
    """Salvage a JPEG with missing SOI (leading zeros + surviving compressed data).

    Returns (image_bytes, filename) on success, raises ValueError on failure.
    """
    from PIL import Image, ImageFile

    file_size = os.path.getsize(filepath)
    if file_size < 2048:
        raise ValueError('File too small to salvage')

    with open(filepath, 'rb') as f:
        damaged = f.read()

    # Find where leading zeros end
    zero_end = 0
    for i in range(len(damaged)):
        if damaged[i] != 0:
            zero_end = i
            break
    else:
        raise ValueError('File is entirely zeros')

    compressed_data = damaged[zero_end:]
    if len(compressed_data) < 1024:
        raise ValueError('Not enough surviving data to salvage')

    # --- Check if the file contains its own tables (only header/SOI lost) ---
    # Scan for a main-image SOF0 (FF C0) followed eventually by SOS (FF DA).
    # If found, we just need to prepend SOI + the tables already in the file.
    own_tables_offset = -1
    remaining = damaged[zero_end:]
    for i in range(len(remaining) - 10):
        # Look for DHT or DQT marker that precedes a full-size SOF0
        if remaining[i] == 0xFF and remaining[i + 1] in (0xC4, 0xDB):
            # Scan ahead for SOF0 with large dimensions
            j = i
            found_sof = False
            while j < min(i + 2000, len(remaining) - 10):
                if remaining[j] == 0xFF and remaining[j + 1] == 0xC0:
                    seg_len = struct.unpack('>H', remaining[j + 2:j + 4])[0]
                    if seg_len >= 11:
                        h = struct.unpack('>H', remaining[j + 5:j + 7])[0]
                        w = struct.unpack('>H', remaining[j + 7:j + 9])[0]
                        if w > 500 and h > 500:
                            own_tables_offset = zero_end + i
                            found_sof = True
                    break
                j += 1
            if found_sof:
                break

    if own_tables_offset > 0:
        # File has its own tables — just prepend SOI and decode
        reconstructed = b'\xFF\xD8' + damaged[own_tables_offset:]
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            img = Image.open(io.BytesIO(reconstructed))
            img.load()
        except Exception as e:
            raise ValueError(f'Failed to decode with embedded tables: {e}')
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False

        out_buf = io.BytesIO()
        img.save(out_buf, 'JPEG', quality=100, subsampling='4:2:0')
        out_buf.seek(0)
        stem = Path(filepath).stem
        suffix = Path(filepath).suffix
        return out_buf.read(), f'{stem}_salvaged{suffix}'

    # --- Fallback: donor-table grafting for files with only compressed data ---

    # Count RST markers in the surviving data
    rst_count = 0
    first_rst_num = -1
    first_rst_byte = -1
    for i in range(len(compressed_data) - 1):
        if compressed_data[i] == 0xFF and 0xD0 <= compressed_data[i + 1] <= 0xD7:
            if first_rst_num < 0:
                first_rst_num = compressed_data[i + 1] - 0xD0
                first_rst_byte = i
            rst_count += 1

    has_rsts = rst_count >= 10

    # Find a donor JPEG in the same directory
    directory = os.path.dirname(filepath)
    pre_sos, sos_seg, sof_info = _find_donor(directory, filepath)
    if pre_sos is None:
        raise ValueError('No valid donor JPEG found in the same directory')

    img_w, img_h, mcu_w, mcu_h = sof_info
    mcu_cols = img_w // mcu_w
    mcu_rows = img_h // mcu_h
    total_mcus = mcu_rows * mcu_cols

    if total_mcus == 0:
        raise ValueError('Invalid image dimensions from donor')

    # Build grafted JPEG: SOI + tables [+ DRI if RSTs present] + SOS + data + EOI
    DRI = 4
    buf = bytearray(b'\xFF\xD8')
    for seg in pre_sos:
        buf.extend(seg)
    if has_rsts:
        buf.extend(b'\xFF\xDD\x00\x04')
        buf.extend(struct.pack('>H', DRI))
    buf.extend(sos_seg)
    buf.extend(compressed_data)
    buf.extend(b'\xFF\xD9')

    # Decode
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        img = Image.open(io.BytesIO(bytes(buf)))
        img.load()
    except Exception as e:
        raise ValueError(f'Failed to decode grafted image: {e}')
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False

    decoded = img.copy()
    if decoded.size != (img_w, img_h):
        raise ValueError(
            f'Decoded size {decoded.size} does not match donor {img_w}x{img_h}')

    if not has_rsts:
        # --- No-RST path: simple graft + decode, no MCU remap possible ---
        # The decoded image is the best we can get. Content is at the top,
        # gray at the bottom. Save directly.
        output = decoded
    else:
        # --- RST path: precise MCU-level remap ---
        # Step 1: detect gray MCU rows at bottom → P_row
        try:
            pixels = list(decoded.get_flattened_data())
        except AttributeError:
            pixels = list(decoded.getdata())
        row_len = img_w
        first_gray_mcu_row = mcu_rows
        for mr in range(mcu_rows - 1, -1, -1):
            start = mr * mcu_h * row_len
            row = pixels[start:start + row_len]
            if len(set(row)) > 2:
                first_gray_mcu_row = mr + 1
                break
        P_row = mcu_rows - first_gray_mcu_row

        # Step 2: RST-marker alignment for exact P including column offset
        # Constraint: rst_count*DRI <= total_mcus-P <= rst_count*DRI + 2*DRI
        P = P_row * mcu_cols
        rst_mcus = rst_count * DRI
        P_min = max(0, total_mcus - rst_mcus - 2 * DRI)
        P_max = total_mcus - rst_mcus
        candidates = []
        for P_col_try in range(mcu_cols):
            P_try = P_row * mcu_cols + P_col_try
            if P_try < P_min or P_try > P_max:
                continue
            for g in range(DRI):
                total = P_try + g
                if total % DRI == 0:
                    n = total // DRI
                    if n % 8 == first_rst_num:
                        candidates.append(P_try)
                        break
        if candidates:
            center = (P_min + P_max) // 2
            P = min(candidates, key=lambda p: abs(p - center))

        if P < 0 or P >= total_mcus:
            P = max(0, P_row * mcu_cols)

        # Step 3: MCU-level remap
        output = Image.new('RGB', (img_w, img_h), (128, 128, 128))
        remap_count = min(total_mcus - P, total_mcus)

        for d_seq in range(remap_count):
            d_row = d_seq // mcu_cols
            d_col = d_seq % mcu_cols
            if d_row >= mcu_rows:
                break

            orig_seq = (P + d_seq) % total_mcus
            o_row = orig_seq // mcu_cols
            o_col = orig_seq % mcu_cols

            sx, sy = d_col * mcu_w, d_row * mcu_h
            dx, dy = o_col * mcu_w, o_row * mcu_h

            block = decoded.crop((sx, sy, sx + mcu_w, sy + mcu_h))
            output.paste(block, (dx, dy))

        # Gray out garbled MCUs (before first RST — bad DC predictor)
        garbled_count = 6
        for d_seq in range(garbled_count):
            orig_seq = (P + d_seq) % total_mcus
            o_row = orig_seq // mcu_cols
            o_col = orig_seq % mcu_cols
            dx, dy = o_col * mcu_w, o_row * mcu_h
            gray_block = Image.new('RGB', (mcu_w, mcu_h), (128, 128, 128))
            output.paste(gray_block, (dx, dy))

    # Encode result
    out_buf = io.BytesIO()
    output.save(out_buf, 'JPEG', quality=100, subsampling='4:2:0')
    out_buf.seek(0)

    stem = Path(filepath).stem
    suffix = Path(filepath).suffix
    filename = f'{stem}_salvaged{suffix}'
    return out_buf.read(), filename


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5900
    print()
    print('╔══════════════════════════════════════════════╗')
    print('║       Photo Integrity Scanner                ║')
    print(f'║  Open http://localhost:{port} in your browser  ║')
    print('╚══════════════════════════════════════════════╝')
    print()
    threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('127.0.0.1', port), ScannerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
        server.server_close()
