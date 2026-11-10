"""Video integrity checks (MP4/MOV/M4V, AVI, MPEG) and their dispatcher."""

import os
import struct
from pathlib import Path

from backend.formats import AVI_EXTS, MP4_EXTS, MPEG_EXTS

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
                            'Truncated atom header; file cut off mid-atom'
                    size = struct.unpack('>Q', ext)[0]

                # size 0 means atom extends to EOF (valid for last atom)
                if size == 0:
                    size = file_size - offset

                if size < 8:
                    # First atom invalid: not an MP4/MOV file
                    if atoms_checked == 0:
                        return 'corrupt', \
                            'No valid MP4/MOV container structure found'
                    break

                # Validate first atom looks like a real ISOBMFF atom
                if atoms_checked == 0:
                    if atom_type not in _KNOWN_ATOMS:
                        return 'corrupt', \
                            'No valid MP4/MOV container structure found'

                # Unknown atom after essential atoms found: trailing garbage,
                # stop walking (cameras occasionally write junk after moov)
                if atom_type not in _KNOWN_ATOMS and has_moov:
                    break

                if atom_type == b'ftyp':
                    has_ftyp = True
                elif atom_type == b'moov':
                    has_moov = True
                elif atom_type == b'mdat':
                    has_mdat = True

                # Check if atom extends past EOF. Only flag essential atoms;
                # garbage trailers with implausible sizes are silently ignored
                if offset + size > file_size:
                    if atom_type not in _KNOWN_ATOMS:
                        break  # trailing junk, not a truncation
                    atom_name = atom_type.decode('ascii', errors='replace')
                    return 'partial', (
                        f'File is truncated: {atom_name!r} atom declares '
                        f'{size:,} bytes but only '
                        f'{file_size - offset:,} remain in file')

                offset += size
                atoms_checked += 1

        if atoms_checked == 0:
            return 'corrupt', 'No valid MP4/MOV container structure found'

        if not has_moov:
            return 'corrupt', (
                'No moov atom (metadata/index), so the file is unplayable. '
                'The moov atom may have been at the end of the file '
                'and lost to truncation')

        if has_moov and not has_mdat:
            return 'partial', (
                'Has moov (metadata) but no mdat (media data); '
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
                return 'corrupt', 'Missing RIFF header; not a valid AVI file'

            riff_type = header[8:12]
            if riff_type not in (b'AVI ', b'AVIX'):
                return 'corrupt', (
                    f'RIFF type is {riff_type!r}, not AVI, so '
                    f'this is not a valid AVI file')

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
                    'Missing AVI header list (hdrl); '
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
                    f'File is truncated: {file_size:,} of '
                    f'{declared_size:,} declared bytes '
                    f'(~{pct}% of data missing)')

            if not has_movi:
                return 'partial', (
                    'Has AVI header but no video data chunk (movi); '
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
                # Could be an MPEG elementary stream; check for any
                # valid start code
                if header[:3] == b'\x00\x00\x01' \
                        and header[3] in _MPEG_START_CODES:
                    pass  # valid MPEG start code, continue
                else:
                    return 'corrupt', (
                        'No MPEG start code found; '
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
                    'Too few valid MPEG start codes; '
                    'file data appears corrupt')

            # Check for MPEG program end code (00 00 01 B9) at end
            f.seek(max(0, file_size - 64))
            tail = f.read(64)
            has_end_code = b'\x00\x00\x01\xb9' in tail

            if not has_end_code:
                return 'partial', (
                    'Missing MPEG program end code, so '
                    'the file is likely truncated')

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
