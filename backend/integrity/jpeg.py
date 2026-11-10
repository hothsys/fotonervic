"""JPEG integrity check."""

import os

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
                return 'corrupt', 'Missing JPEG SOI marker; not a valid JPEG file'

            # Scan for APP1/EXIF segment
            header_chunk = f.read(min(2048, file_size - 2))
            has_exif = b'Exif\x00\x00' in header_chunk
            has_jfif = b'JFIF\x00' in header_chunk

            # Check for SOS (Start of Scan) marker; its presence means image data exists
            f.seek(2)
            full_header = f.read(min(65536, file_size))
            has_sos = b'\xff\xda' in full_header

        # Specific case: has EXIF but no image scan data at all
        if has_exif and not has_sos:
            return 'exif_only', \
                'File contains EXIF/metadata but no image scan data, so ' \
                'image content was not recovered'

        if not has_sos:
            return 'partial', \
                'No image scan data (SOS marker) found; image may be a bare header'

        # Full Pillow decode is the definitive test.
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
