"""JPEG salvage: donor-table grafting and MCU remap."""

import io
import os
import struct
from pathlib import Path

from backend.formats import JPEG_EXTS

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
        # File has its own tables: just prepend SOI and decode
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

        # Gray out garbled MCUs (before first RST, bad DC predictor)
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
