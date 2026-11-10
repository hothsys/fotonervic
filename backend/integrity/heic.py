"""HEIC / HEIF integrity check."""

import os
import struct

# ─── HEIC / HEIF checker ──────────────────────────────────────────────────────

# Coded image item types in a HEIF container (iPhones store a grid of 'hvc1' tiles)
_HEIF_CODED_ITEMS = {b'hvc1', b'av01', b'avc1', b'jpeg', b'j2k1', b'unci'}


def _iter_boxes(buf, start, end):
    """Yield (type, payload_start, payload_end) for ISOBMFF boxes in buf[start:end]."""
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack('>I4s', buf[pos:pos + 8])
        hlen = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack('>Q', buf[pos + 8:pos + 16])[0]
            hlen = 16
        elif size == 0:
            size = end - pos
        if size < hlen:
            return
        yield typ, pos + hlen, min(pos + size, end)
        pos += size


def _parse_heif_structure(filepath: str):
    """Walk a HEIF/HEIC container without decoding it.

    Returns None if the file doesn't start with an 'ftyp' box, else a dict:
      truncated_box  name of a top-level box that runs past end of file, or None
      items          {item_id: item_type} from 'iinf'
      extents        [(item_id, end_offset)] for item data stored in the file
      has_transform  True if an 'irot'/'imir' property is present; libheif
                     applies those itself when decoding
    """
    file_size = os.path.getsize(filepath)
    meta = None
    truncated_box = None
    with open(filepath, 'rb') as f:
        offset = 0
        while offset + 8 <= file_size:
            f.seek(offset)
            size, typ = struct.unpack('>I4s', f.read(8))
            hlen = 8
            if size == 1:
                size = struct.unpack('>Q', f.read(8))[0]
                hlen = 16
            elif size == 0:
                size = file_size - offset
            if offset == 0 and typ != b'ftyp':
                return None
            if size < hlen:
                truncated_box = typ.decode('latin-1')
                break
            if typ == b'meta' and meta is None:
                f.seek(offset + hlen)
                meta = f.read(min(size, file_size - offset) - hlen)
            if offset + size > file_size:
                truncated_box = typ.decode('latin-1')
                break
            offset += size

    result = {'truncated_box': truncated_box, 'items': {}, 'extents': [],
              'has_transform': False}
    if not meta or len(meta) < 4:
        return result

    def uint(buf, pos, nbytes):
        return int.from_bytes(buf[pos:pos + nbytes], 'big') if nbytes else 0

    try:
        # 'meta' is a FullBox: 4 bytes of version/flags before its children
        for typ, start, end in _iter_boxes(meta, 4, len(meta)):
            if typ == b'iprp':
                for t2, s2, e2 in _iter_boxes(meta, start, end):
                    if t2 == b'ipco':
                        for t3, _, _ in _iter_boxes(meta, s2, e2):
                            if t3 in (b'irot', b'imir'):
                                result['has_transform'] = True
            elif typ == b'iinf':
                version = meta[start]
                first = start + (6 if version == 0 else 8)
                for t2, s2, e2 in _iter_boxes(meta, first, end):
                    if t2 != b'infe' or meta[s2] < 2:
                        continue
                    id_len = 2 if meta[s2] == 2 else 4
                    item_id = uint(meta, s2 + 4, id_len)
                    result['items'][item_id] = meta[s2 + 4 + id_len + 2:s2 + 4 + id_len + 6]
            elif typ == b'iloc':
                version = meta[start]
                pos = start + 4
                offset_size, length_size = meta[pos] >> 4, meta[pos] & 0x0F
                base_offset_size = meta[pos + 1] >> 4
                index_size = meta[pos + 1] & 0x0F if version in (1, 2) else 0
                pos += 2
                id_len = 4 if version == 2 else 2
                item_count = uint(meta, pos, id_len)
                pos += id_len
                for _ in range(item_count):
                    item_id = uint(meta, pos, id_len)
                    pos += id_len
                    method = 0
                    if version in (1, 2):
                        method = uint(meta, pos, 2) & 0x0F
                        pos += 2
                    pos += 2  # data_reference_index
                    base = uint(meta, pos, base_offset_size)
                    pos += base_offset_size
                    extent_count = uint(meta, pos, 2)
                    pos += 2
                    for _ in range(extent_count):
                        pos += index_size
                        ext_off = uint(meta, pos, offset_size)
                        pos += offset_size
                        ext_len = uint(meta, pos, length_size)
                        pos += length_size
                        if method == 0:  # stored in the file (1 = inside meta, 2 = another item)
                            result['extents'].append((item_id, base + ext_off + ext_len))
    except (IndexError, struct.error):
        pass  # header itself damaged; report whatever was parsed
    return result


def check_heic(filepath: str):
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return 'empty', 'File is empty (0 bytes)'

        # Structural check first. libheif decodes a grid image even when some
        # tiles are missing (it fills them with solid color), so a successful
        # decode alone doesn't prove the file is complete.
        heif = _parse_heif_structure(filepath)
        if heif is None:
            return 'corrupt', 'No valid HEIF/HEIC container structure (missing ftyp box)'

        cut_items = {item for item, end in heif['extents'] if end > file_size}
        expected_end = max([end for _, end in heif['extents']] + [file_size])
        pct = round((expected_end - file_size) / expected_end * 100, 3)
        if cut_items:
            coded = {i for i, t in heif['items'].items() if t in _HEIF_CODED_ITEMS}
            cut_tiles = cut_items & coded
            what = (f'{len(cut_tiles)} of {len(coded)} image tiles are incomplete or missing'
                    if coded else f'{len(cut_items)} data items run past the end of the file')
            return 'partial', f'HEIC file is truncated: {what} (~{pct}% of file corrupted)'
        if heif['truncated_box']:
            return 'partial', (f"HEIC file is truncated: '{heif['truncated_box']}' box "
                               f"runs past the end of the file")

        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass  # plain PIL may still have HEIF support

        try:
            from PIL import Image
            img = Image.open(filepath)
            img.load()
            return 'ok', None
        except Exception as e:
            err_lower = str(e).lower()
            if 'cannot identify' in err_lower:
                return 'unsupported', \
                    'HEIC/HEIF support unavailable. Install pillow-heif ' \
                    '(pip install pillow-heif). Container structure looks intact.'
            if 'truncated' in err_lower:
                return 'partial', f'Truncated HEIC file: {str(e)}'
            return 'corrupt', f'HEIC decode error: {str(e)}'

    except PermissionError:
        return 'error', 'Permission denied reading file'
    except Exception as e:
        return 'error', f'Unexpected error: {str(e)}'
