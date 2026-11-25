# Blur Check

Click **Blur Check** to score every photo in a directory for blur. Results appear as a thumbnail grid grouped by folder, blurriest first, each with a blur score from **0 (sharp)** to **100 (very blurry)**.

- **Blur threshold slider:** photos scoring at or above it count as blurry; by default only those are shown. Moving it re-filters instantly (no rescan), and the setting is remembered. **Default** resets it to 50.
- **Show all photos** lists every photo, with the blurry ones outlined in red.
- **Score colours:** green below 15, yellow from 15 to 49, red at 50 or above (fixed bands, whatever the slider is set to).
- **ⓘ on each score:** click it to see what the score means at your current threshold and what it was based on: the AI quality rating, the sharpness measure, how much of the frame has detail, and anything that raised the score (very little fine detail) or changed how it was measured (a RAW scored from its JPEG companion). A damaged file's pop-out says the score covers only the readable part.
- **Low detail:** photos that are mostly smooth sky, silhouette, haze, or plain surfaces (a moon, a sunrise over a ridge, fog) have too little detail to judge focus and can score high even when perfectly sharp. When under 20% of the frame has detail, the photo gets a grey **Low detail** tag whose ⓘ explains why and what the score was based on, its score turns grey (for reference only), and it never counts as blurry: it's listed under **Show all photos**, sorted last, and counted separately in the summary. Check these by eye in the preview at 100%.
- **Export CSV** saves every photo's score, its components (including Low Detail and Detail %), and whether it's blurry at the current threshold.
- **Preview:** click a thumbnail to check a photo full screen and zoom in to 100% (see [Lightbox preview](lightbox.md)); the caption shows its blur score.

## AI-assisted scoring

Blur Check combines two measurements:

1. **A sharpness measure** (always available): the variance of the Laplacian, scored by the photo's sharpest region so a sharp subject on a soft, out-of-focus background (bokeh) still counts as sharp, checked in every direction to catch camera shake, and contrast-normalized so dark photos aren't penalized. It's good at blur specifically, but its scale depends on the scene: a crisp portrait has less edge detail than crisp carved stone, so one threshold doesn't fit every folder.
2. **An AI quality model** (optional, recommended): **CLIP-IQA+**, a trained image-quality model that judges photos the way people do across cameras and scenes. On its own it also marks dark photos down, which is why it's combined with the sharpness measure rather than used alone.

A third check catches photos that look ordinary to both: ones smeared by camera shake, soft low-resolution exports, or heavy phone noise reduction can keep plenty of edge contrast while losing nearly all fine detail. When a photo's sharpest areas have almost no fine detail (measured in the frequency domain), it's flagged, unless the AI model rates the photo above average (some phones' own processing leaves sharp photos with little fine detail too).

Before scoring, dark photos are brightened (shadows lifted most, like raising exposure in an editor), because underexposure is fixable in post-processing and shouldn't count as blur. This happens on an in-memory copy; files are never modified.

The two scores are standardized against a reference library and blended, with the AI model weighted 60% and the sharpness measure 40% (the AI model judges bokeh portraits and smeared zooms better; the sharpness measure catches real softness the AI model can miss, and isn't fooled by dark photos). The default threshold of 50 sits on the boundary between photos the owner judged sharp and photos they judged blurry (41 photos from 11 cameras, 2001 to 2025). On an 851-photo curated iPhone/Nikon D810 library, 17 photos (2%) are flagged at the default.

**Installing the model:** the first Blur Check without it shows **Basic scoring** with a **Download model** button (146 MB, one time). The app downloads it with `curl`, verifies its SHA-256 checksum, and stores it in `models/`. It needs `onnxruntime`, which the app installs automatically on startup (optional: if that install fails, Blur Check keeps using basic scoring).

**Speed:** about 0.25 s per photo with the AI model (an 851-photo folder takes under 4 minutes), versus about 15 seconds for the whole folder with basic scoring.

**License:** the model file is **not** covered by this project's MIT license. It combines OpenAI's CLIP image encoder (MIT) with learned prompts from pyiqa (PolyForm Noncommercial), so it's for **non-commercial use only**. See [`models/MODEL_LICENSE.md`](../models/MODEL_LICENSE.md).

### Publishing the model (maintainers)

The 146 MB model is too big for git, so it's distributed as a GitHub release file:

1. Build it (or use the copy in `models/`): see the instructions at the top of [`tools/export_quality_model.py`](../tools/export_quality_model.py). It needs PyTorch in a throwaway virtual environment, checks that the exported model reproduces pyiqa exactly, and prints the file's SHA-256, which must match `QUALITY_MODEL_SHA256` in `backend/blur/quality_model.py`.
2. Create a GitHub release tagged `quality-model-v1` and attach `models/clipiqa_plus_rn50.onnx` and `models/MODEL_LICENSE.md`.
3. `QUALITY_MODEL_URL` in `app.conf` already points at that release file.

**Limitations:** neither measurement knows what you *meant* to focus on, so a photo with the background in focus and the subject soft can count as sharp. Intentional softness (long-exposure water, mist, haze) can score as blurry. The calibration rests on a small set of photos the owner judged (41 from 11 cameras) plus one large library, so if the default doesn't match your eye, the slider is the fix. RAW files are scored from their embedded full-size preview when there is one. When the preview is too small (e.g. iPhone DNGs), a same-name JPEG/HEIC saved alongside it (RAW+JPEG shooting) is scored instead; without one, the sensor data is decoded and lightly sharpened to approximate the camera's processing. The card's tooltip says which was used.
