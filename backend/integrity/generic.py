"""Integrity check for other Pillow-readable formats (TIFF, WebP, BMP, GIF)."""

import os

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
