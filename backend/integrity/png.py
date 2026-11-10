"""PNG integrity check."""

import os

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
                'Missing PNG IEND chunk, so the file is truncated (image data incomplete)'

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
