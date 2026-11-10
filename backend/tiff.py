"""TIFF structure parsing for TIFF-based RAWs (NEF, ARW) and embedded
preview extraction, shared by the RAW integrity check, thumbnails, and
Export Preview."""

import io
import os
import struct

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
                # Had offset tags but couldn't read the counts, so the result is ambiguous
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

def _has_usable_preview(filepath: str) -> bool:
    """True if Export Preview would produce a complete JPEG: an embedded
    preview can be located and decodes fully. False when the RAW header that
    points to it is gone (e.g. a recovered file whose start was zeroed)."""
    preview = _find_best_embedded_preview(filepath)
    if not preview:
        return False
    _, _, offset, length = preview
    try:
        from PIL import Image
        with open(filepath, 'rb') as f:
            f.seek(offset)
            data = f.read(length)
        Image.open(io.BytesIO(data)).load()
        return True
    except Exception:
        return False


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
                if dtype == 3:  # SHORT: 2 bytes
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
