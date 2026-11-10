
# ─── Blur detection ───────────────────────────────────────────────────────────
#
# Two measurements, combined when the AI model is installed:
#
# 1. Hand-built sharpness (always available): variance of the Laplacian,
#    adapted so a sharp subject on a soft background (bokeh) isn't mistaken
#    for a blurry photo:
#      * tiled: scored by the photo's sharpest region, not its average
#      * directional: second differences along 4 directions, keeping the
#        weakest per tile (camera shake smears one direction only)
#      * contrast-stretched (gain capped), so dark photos aren't penalized
#      * featureless tiles (sky, fog, walls) are ignored
#    Good at blur specifically, but its scale depends on the scene: a crisp
#    low-texture photo (a portrait) produces less edge energy than a crisp
#    high-texture one (carved stone), so one threshold doesn't fit every folder.
#
# 2. AI quality (optional): CLIP-IQA+, a CLIP ResNet-50 model trained on human
#    quality ratings (models/clipiqa_plus_rn50.onnx, built by
#    tools/export_quality_model.py). It judges photos the way people do across
#    cameras and scenes, but on its own it also marks dark photos down.
#
# Blending the two (each standardized against a reference library; weights in
# calibration.py) kept the
# hand-built measure's blur specificity and gained the model's consistency:
# on the user's labelled test photos plus an 851-photo library, one threshold
# separated sharp from blurry in both, with no bokeh photo flagged.
