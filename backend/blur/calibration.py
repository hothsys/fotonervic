"""Every tunable number in Blur Check. Calibration changes (from the owner's
verdicts) should only need to touch this file."""

BLUR_WORK_SIZE = 1024     # long side of the working copy; makes scores comparable across resolutions
BLUR_GRID      = 16       # tiles along the long side
BLUR_TOP_FRAC  = 0.02     # sharpness = mean of the sharpest 2% of tiles (at least 2): "the subject"
BLUR_MAX_GAIN  = 4.0      # cap on the contrast stretch
BLUR_TEX_STD   = 6.0      # tiles flatter than this (grey-level std) carry no focus information
BLUR_MIN_SIZE  = 512      # smaller images are too small to judge focus (e.g. the 160x120
                          # thumbnail Pillow opens for a NEF when rawpy isn't installed)


# Exposure normalization before scoring. Blur Check is for culling before
# (non-destructive) RAW editing: underexposure is fixable in Lightroom, missed
# focus and motion blur aren't, so a dark photo shouldn't score as blurry. Both
# measures otherwise penalize darkness (weak edges; the AI model learned that
# people rate dark photos lower). Applied to the in-memory copy only.
EXPOSURE_TARGET    = 0.40   # brighten until median luminance reaches 40% (never darken)
EXPOSURE_MIN_GAMMA = 0.35   # strongest lift allowed, so near-black frames don't become pure noise


QUALITY_INPUT_SIZE   = 768   # long side fed to the model: as accurate as 1024 px, ~2x faster


# Calibration, from a reference library (851 photos) and the user's labelled
# test photos. Each measurement is standardized (z-score) against the library,
# and the blur score maps the combined z to 0..100 so the boundary between the
# labelled sharp and blurry photos lands on BLUR_DEFAULT_THRESHOLD.
CAL_SHARP_MEAN, CAL_SHARP_STD = 2.6397, 0.3899      # hand-built log10(1 + sharpness), after exposure normalization
CAL_QUALITY_MEAN, CAL_QUALITY_STD = 0.6674, 0.0803  # AI quality (probability of "good"), after exposure normalization
# Sharp/blurry boundary in combined z, from the owner's verdicts (41 photos:
# labelled test set + Iceland photos they judged). AI: midway between the
# least-sharp photo they call sharp and the sharpest-looking one they call
# blurry (two hard misses, cr_071 and Sign2, excluded: both measures rate them
# ordinary; iceland_bhumi_iphone_0965 too, inseparable at any weighting).
# Basic: the measures overlap, so the error-minimizing cut.
CAL_CUT_AI, CAL_CUT_BASIC = -2.0120, -1.6262
# Share of the AI quality measure in the combined z (the rest is sharpness).
# 0.6 rather than 0.5: in bokeh portraits (IMG_6920) the sharpness measure
# finds no crisp edges, and in smeared zooms (0965) surviving building edges
# fool it, while the AI model judges both right. Higher shares stop catching
# known-soft photos (1427, day3_0030) and push dark photos up.
CAL_WEIGHT_AI = 0.6
CAL_SCALE = 25.0                              # blur points per unit of z (at the threshold)
CAL_CURVE = 25.0                              # softness of the S-curve that maps onto 0..100
BLUR_DEFAULT_THRESHOLD = 50


# A RAW whose embedded preview is too small to judge (iPhone DNGs: 328x246)
# is scored from something better, in order of preference:
#  1. a same-name JPEG/HEIC companion (RAW+JPEG shooting): the camera's own
#     rendering of the same shot. On 24 Iceland DNG/JPG pairs, scoring the
#     plain sensor decode instead flagged 7 DNGs while none of their JPGs were
#     flagged (average gap 19 points), because a plain decode lacks the
#     camera's sharpening and contrast.
#  2. the sensor data with an unsharp mask approximating that processing
#     (radius 1.8, 120%, chosen on half the pairs; average gap 5 points on the
#     other half, no DNG flagged)
COMPANION_EXTS = ('.jpg', '.jpeg', '.heic', '.heif')
SENSOR_UNSHARP = (1.8, 120, 2)   # radius, percent, threshold


# ── Fine-detail check (catches smeared/soft photos both measures rate ordinary) ──
# Some blurry photos (camera shake smears, soft low-res exports, heavy
# phone noise reduction) still have plenty of edge contrast, so the sharpness
# measure and the AI model both rate them average. What they lack is fine
# detail: in the frequency domain, little power at fine scales relative to
# coarse ones. Measured on the photo's sharpest 128 px patches (so bokeh
# backgrounds don't count against it), across 12 orientations. On the owner's
# verdicts, the three blurry photos lowest on this measure (cr_071, Sign2,
# iceland_bhumi_iphone_0584) all fall below FINE_DETAIL_CUTOFF, and no photo
# they call not blurry does; it can't separate every case (e.g.
# iceland_bhumi_iphone_0965, blurry, sits among not-blurry photos), so it's a
# floor on the score, not a replacement.
# Sharp iPhone 13 Pro photos (IMG_9711, IMG_9458 in the owner's Lightroom
# Mobile folder) can measure just as low, from the phone's own processing, but
# the AI model rates them above average, while every blurry photo the floor
# catches rates below average. So the floor only applies when the AI model
# doesn't vouch for the photo (or isn't installed).
FINE_DETAIL_PATCH = 128
FINE_DETAIL_DIRECTIONS = 12
FINE_DETAIL_TOP_FRAC = 0.10      # use the sharpest 10% of patches (at least 3)
FINE_DETAIL_CUTOFF = -1.53       # below this, the photo is flagged regardless of the blur score
FINE_DETAIL_SCALE = 0.125        # how fast the floor rises below the cutoff
FINE_DETAIL_MAX_QUALITY_Z = 0.0  # floor skipped when the AI quality z is above this
