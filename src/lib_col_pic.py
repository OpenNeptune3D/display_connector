# Copyright (c) 2023 Molodos
# The ElegooNeptuneThumbnails plugin is released under the terms of the AGPLv3 or higher.

from threading import Lock
import numpy as np
from PIL import ImageColor

thumbnail_lock = Lock()

_PALETTE_DTYPE = np.dtype([
    ('colo16', np.uint16),
    ('A0', np.uint8),
    ('A1', np.uint8),
    ('A2', np.uint8),
    ('qty', np.uint32),
])

# Pre-computed LUT for base64-like encoding: 6-bit value → ASCII byte
# Avoids per-byte arithmetic and branch in hot loop
_ENCODE_LUT = np.array([
    (126 if (i + 48) == 92 else i + 48) for i in range(64)
], dtype=np.uint8)


def parse_thumbnail(img, width: int, height: int, default_background: str) -> str:
    with thumbnail_lock:
        img.thumbnail((width, height))
        img = img.convert("RGBA")
        pixels = np.array(img, dtype=np.uint8)
        img_h, img_w = pixels.shape[:2]

        bg_hex = default_background if default_background.startswith("#") else "#" + default_background
        r_bkg, g_bkg, b_bkg = ImageColor.getcolor(bg_hex, "RGB")

        # Alpha compositing - single pass, minimal intermediates
        alpha = pixels[:, :, 3].astype(np.float32) * (1.0 / 255.0)
        inv_alpha = 1.0 - alpha

        r = (pixels[:, :, 0] * alpha + r_bkg * inv_alpha).astype(np.uint8)
        g = (pixels[:, :, 1] * alpha + g_bkg * inv_alpha).astype(np.uint8)
        b = (pixels[:, :, 2] * alpha + b_bkg * inv_alpha).astype(np.uint8)

        # RGB565 - direct computation, no intermediate array
        color16 = (
            ((r.astype(np.uint16) >> 3) << 11) |
            ((g.astype(np.uint16) >> 2) << 5) |
            (b.astype(np.uint16) >> 3)
        ).ravel()  # ravel() avoids copy if already contiguous

        # Tighter buffer estimate: header(32) + palette(2048) + rle(~n/2) + base64 expansion(4/3)
        # Worst case RLE is 2 bytes per pixel, but typical is much less
        buffer_size = max(8192, int(img_h * img_w * 3))
        output_data = bytearray(buffer_size)

        encoded_len = _colpic_encode_str(color16, img_w, img_h, output_data, len(output_data), 1024)

        if encoded_len <= 0:
            return ""
        return output_data[:encoded_len].decode("ascii")


def _colpic_encode_str(
    fromcolor16: np.ndarray,
    picw: int,
    pich: int,
    outputdata: bytearray,
    outputmaxsize: int,
    colorsmax: int,
) -> int:
    qty = _colpic_encode(fromcolor16, picw, pich, outputdata, outputmaxsize, colorsmax)
    if qty == 0:
        return 0

    padding = (3 - qty % 3) % 3
    if qty + padding > outputmaxsize:
        return 0
    for i in range(padding):
        outputdata[qty + i] = 0
    qty += padding

    final_len = (qty * 4) // 3
    if final_len >= outputmaxsize:
        return 0

    # Vectorized base64-like encoding using LUT
    raw = np.frombuffer(outputdata, dtype=np.uint8, count=qty)

    # Reshape to groups of 3 bytes
    raw_padded = raw.reshape(-1, 3)

    # Extract 6-bit chunks: 3 bytes → 4 values
    c0 = raw_padded[:, 0] >> 2
    c1 = ((raw_padded[:, 0] & 0x03) << 4) | (raw_padded[:, 1] >> 4)
    c2 = ((raw_padded[:, 1] & 0x0F) << 2) | (raw_padded[:, 2] >> 6)
    c3 = raw_padded[:, 2] & 0x3F

    # Apply LUT and interleave
    encoded = np.column_stack([
        _ENCODE_LUT[c0],
        _ENCODE_LUT[c1],
        _ENCODE_LUT[c2],
        _ENCODE_LUT[c3],
    ]).ravel()

    outputdata[:final_len] = encoded.tobytes()
    outputdata[final_len] = 0
    return final_len


def _colpic_encode(
    fromcolor16: np.ndarray,
    picw: int,
    pich: int,
    outputdata: bytearray,
    outputmaxsize: int,
    colorsmax: int,
) -> int:
    HEADER_SIZE = 32

    # Unconditional defensive copy: palette reduction mutates `pixels`.
    pixels = np.array(fromcolor16, dtype=np.uint16, copy=True)

    colorsmax = min(colorsmax, 1024)

    unique_colors, counts = np.unique(pixels, return_counts=True)

    palette = np.zeros(len(unique_colors), dtype=_PALETTE_DTYPE)
    palette['colo16'] = unique_colors
    palette['qty'] = counts
    palette['A0'] = (unique_colors >> 11) & 0x1F
    palette['A1'] = (unique_colors >> 5) & 0x3F
    palette['A2'] = unique_colors & 0x1F

    sort_order = np.argsort(palette['qty'])[::-1]
    palette = palette[sort_order]

    # Optimized palette reduction: batch distance calc + LUT remap
    if len(palette) > colorsmax:
        keep = palette[:colorsmax]
        discard = palette[colorsmax:]

        # Vectorized distance: (num_discard, num_keep) matrix
        # Use int16 to avoid overflow on subtraction
        d_a0 = np.abs(
            discard['A0'].astype(np.int16)[:, np.newaxis] -
            keep['A0'].astype(np.int16)
        )
        d_a1 = np.abs(
            discard['A1'].astype(np.int16)[:, np.newaxis] -
            keep['A1'].astype(np.int16)
        )
        d_a2 = np.abs(
            discard['A2'].astype(np.int16)[:, np.newaxis] -
            keep['A2'].astype(np.int16)
        )
        distances = d_a0 + d_a1 + d_a2

        nearest_indices = np.argmin(distances, axis=1)

        # Build 65536-entry LUT for O(1) pixel remapping
        remap_lut = np.arange(65536, dtype=np.uint16)
        remap_lut[discard['colo16']] = keep['colo16'][nearest_indices]

        # Single-pass remap - cache-friendly sequential access
        pixels = remap_lut[pixels]
        palette = keep

    color_to_idx = {int(c): i for i, c in enumerate(palette['colo16'])}
    list_data_size = len(palette) * 2

    if HEADER_SIZE + list_data_size + 2 > outputmaxsize:
        return 0

    outputdata[:outputmaxsize] = b"\x00" * outputmaxsize

    outputdata[0] = 3
    outputdata[4:8] = int(picw).to_bytes(4, 'little')
    outputdata[8:12] = int(pich).to_bytes(4, 'little')
    outputdata[12:16] = (98419516).to_bytes(4, 'little')
    outputdata[16:20] = list_data_size.to_bytes(4, 'little')

    palette_bytes = palette['colo16'].astype('<u2').tobytes()
    outputdata[HEADER_SIZE:HEADER_SIZE + list_data_size] = palette_bytes

    rle_offset = HEADER_SIZE + list_data_size
    rle_maxsize = outputmaxsize - rle_offset

    encoded_len = _rle_encode_fast(pixels, color_to_idx, outputdata, rle_offset, rle_maxsize)
    if encoded_len < 0:
        return 0

    outputdata[20:24] = encoded_len.to_bytes(4, 'little')

    return HEADER_SIZE + list_data_size + encoded_len


def _rle_encode_fast(
    pixels: np.ndarray,
    color_to_idx: dict,
    output: bytearray,
    output_offset: int,
    max_size: int,
) -> int:
    """
    RLE encode with NumPy-accelerated run detection.
    Falls back to pure Python for the encoding step but minimizes iterations.
    """
    n = len(pixels)
    if n == 0:
        return 0

    # Find run boundaries using NumPy - O(n) but vectorized
    # diff_mask[i] is True where a new run starts
    diff_mask = np.empty(n, dtype=np.bool_)
    diff_mask[0] = True
    np.not_equal(pixels[1:], pixels[:-1], out=diff_mask[1:])

    run_starts = np.flatnonzero(diff_mask)
    run_ends = np.concatenate([run_starts[1:], [n]])
    run_lengths = run_ends - run_starts
    run_colors = pixels[run_starts]

    # Batch lookup palette indices
    palette_indices = np.array([color_to_idx.get(int(c), 0) for c in run_colors], dtype=np.uint16)
    tids = (palette_indices & 0x1F).astype(np.uint8)
    sids = ((palette_indices >> 5) & 0x1F).astype(np.uint8)

    # Encode runs - still need Python loop but iterating over runs, not pixels
    dst = 0
    last_sid = 0

    for i in range(len(run_lengths)):
        length = int(run_lengths[i])
        tid = tids[i]
        sid = sids[i]

        # Handle runs > 255 by splitting
        while length > 0:
            chunk = min(255, length)

            # Segment switch
            if sid != last_sid:
                if dst >= max_size:
                    return -1
                output[output_offset + dst] = (7 << 5) | sid
                dst += 1
                last_sid = sid

            # Encode run
            if chunk <= 6:
                if dst >= max_size:
                    return -1
                output[output_offset + dst] = (chunk << 5) | tid
                dst += 1
            else:
                if dst + 1 >= max_size:
                    return -1
                output[output_offset + dst] = tid
                output[output_offset + dst + 1] = chunk
                dst += 2

            length -= chunk

    return dst
