"""Hand-built sharpness measure and the fine-detail measure."""

import math

from backend.blur.calibration import (
    BLUR_GRID,
    BLUR_MAX_GAIN,
    BLUR_TEX_STD,
    BLUR_TOP_FRAC,
    FINE_DETAIL_DIRECTIONS,
    FINE_DETAIL_PATCH,
    FINE_DETAIL_TOP_FRAC,
)

def _hand_built_sharpness(gray):
    """Sharpness of the photo's sharpest region, or None when it has too little
    texture to judge. gray: 'L' image."""
    import numpy as np
    a = np.asarray(gray, dtype=np.float32)
    lo, hi = np.percentile(a, (1, 99))
    a = (a - lo) * min(BLUR_MAX_GAIN, 255.0 / max(hi - lo, 1.0))

    c = a[1:-1, 1:-1]
    second_diffs = (
        a[1:-1, :-2] + a[1:-1, 2:] - 2 * c,           # horizontal
        a[:-2, 1:-1] + a[2:, 1:-1] - 2 * c,           # vertical
        (a[:-2, :-2] + a[2:, 2:] - 2 * c) / 2,        # diagonals (pixels sqrt2 apart)
        (a[:-2, 2:] + a[2:, :-2] - 2 * c) / 2,
    )
    h, w = c.shape
    if h > w:
        rows, cols = BLUR_GRID, max(1, round(BLUR_GRID * w / h))
    else:
        rows, cols = max(1, round(BLUR_GRID * h / w)), BLUR_GRID
    th, tw = h // rows, w // cols

    def per_tile(x):
        return x[:rows * th, :cols * tw].reshape(rows, th, cols, tw)

    tile_sharp = np.stack([per_tile(d).var(axis=(1, 3)) for d in second_diffs]).min(axis=0)
    tile_std = per_tile(c).std(axis=(1, 3))
    textured = tile_sharp[tile_std >= BLUR_TEX_STD]
    k = max(2, math.ceil(BLUR_TOP_FRAC * tile_sharp.size))
    if textured.size < k:
        return None
    return float(np.sort(textured)[-k:].mean())


_FINE_DETAIL_MASKS = None


def _fine_detail_masks():
    global _FINE_DETAIL_MASKS
    if _FINE_DETAIL_MASKS is None:
        import numpy as np
        n = FINE_DETAIL_PATCH
        f = np.fft.fftshift(np.fft.fftfreq(n))
        fy, fx = np.meshgrid(f, f, indexing='ij')
        radius = np.hypot(fx, fy)
        angle = (np.degrees(np.arctan2(fy, fx)) + 180) % 180
        half_width = 180 / FINE_DETAIL_DIRECTIONS / 2
        wedges = [np.abs(((angle - k * 180 / FINE_DETAIL_DIRECTIONS) + 90) % 180 - 90) < half_width
                  for k in range(FINE_DETAIL_DIRECTIONS)]
        fine = (radius >= 0.25) & (radius <= 0.45)      # cycles/pixel
        coarse = (radius >= 0.06) & (radius <= 0.15)
        window = np.outer(np.hanning(n), np.hanning(n))
        _FINE_DETAIL_MASKS = ([w & fine for w in wedges], [w & coarse for w in wedges], window)
    return _FINE_DETAIL_MASKS


def _fine_detail(gray):
    """Mean log10(fine/coarse spectral power) over the sharpest patches and
    all orientations; lower = less fine detail. None if too little texture."""
    import numpy as np
    fine_masks, coarse_masks, window = _fine_detail_masks()
    a = np.asarray(gray, dtype=np.float32)
    lo, hi = np.percentile(a, (1, 99))
    a = (a - lo) * min(BLUR_MAX_GAIN, 255.0 / max(hi - lo, 1.0))
    n, step = FINE_DETAIL_PATCH, FINE_DETAIL_PATCH // 2
    ratios = []
    for y in range(0, a.shape[0] - n + 1, step):
        for x in range(0, a.shape[1] - n + 1, step):
            tile = a[y:y + n, x:x + n]
            if tile.std() < BLUR_TEX_STD:
                continue
            power = np.abs(np.fft.fftshift(np.fft.fft2((tile - tile.mean()) * window))) ** 2
            ratios.append([math.log10(power[fm].mean() / max(power[cm].mean(), 1e-12))
                           for fm, cm in zip(fine_masks, coarse_masks)])
    if len(ratios) < 3:
        return None
    ratios = np.array(ratios)
    k = max(3, int(round(FINE_DETAIL_TOP_FRAC * len(ratios))))
    top = ratios[np.argsort(ratios.max(axis=1))[-k:]]   # patches sharpest in their best direction
    return float(top.mean())
