<p align="center">
  <img src="logo.svg" width="220">
</p>

<h1 align="center">Foto Nerve Shatter</h1>

<p align="center">
  <i>I hope you never have to use this. But if you do, I hope it helps.</i>
  
  This web app recursively scans directories for corrupt, truncated, or damaged image and video files. For images, it attempts recovery where possible. Also extracts EXIF metadata
with thumbnail previews across an entire directory.
  
  Built for data recovery scenarios where hundreds or thousands of photos have been rescued from a failing drive but many are partially damaged. The scanner identifies every problem file, categorizes the damage, and offers one-click repair or salvage for supported image formats.
</p>

## Features

- **Recursive scanning** with real-time progress via Server-Sent Events
- **Folder-grouped results** with filtering by issue type
- **Repair JPEG**: re-encodes truncated JPEGs while preserving EXIF metadata and ICC profiles
- **Salvage Image**: recovers JPEGs with destroyed headers (missing SOI) using donor-table grafting and MCU-level remapping
- **Export Preview**: extracts embedded JPEG previews from RAW files that can't be fully decoded
- **EXIF Info**: scans every image and video for metadata (camera, date, settings, GPS coordinates, dimensions) and displays it as a lazy-loaded thumbnail card grid grouped by folder
- **Blur Check**: scores every photo for blur (0 = sharp, 100 = very blurry) without mistaking bokeh for blur, using a sharpness measure plus an optional AI quality model, with a threshold slider to decide what counts as blurry
- **Volume mount detection**: detects when a drive is mounted/unmounted in real time and shows a status indicator
- **Previous scans**: last 10 scans persisted to IndexedDB; restore any previous scan from a dropdown without rescanning
- **CSV export** of scan results, EXIF data, and blur scores
- **Directory browser** with breadcrumb navigation
- **Reveal in Finder/Explorer**: jump to any file from the UI
- **Lightbox preview**: click a photo's thumbnail in Exif Info or Blur Check to view it full screen (RAW and HEIC included), step through photos with the arrow keys, and click to zoom to 100% to check focus

## Supported Formats

| Category | Extensions |
|----------|-----------|
| JPEG | `.jpg` `.jpeg` `.jpe` `.jfif` |
| PNG | `.png` |
| HEIC/HEIF | `.heic` `.heif` |
| TIFF | `.tif` `.tiff` |
| RAW | `.nef` `.nrw` `.arw` `.srf` `.sr2` `.cr2` `.cr3` `.dng` `.raf` `.rw2` `.orf` `.pef` `.srw` |
| Other | `.webp` `.bmp` `.gif` |
| Video | `.mp4` `.m4v` `.mov` `.avi` `.mpg` `.mpeg` |

How each format is checked: [Supported formats](docs/supported-formats.md).

## Starting and Stopping

Foto Nerve Shatter runs as a local web server at [http://localhost:5900](http://localhost:5900) and opens your browser when it starts. There's nothing to install by hand: on first launch it creates its own Python environment (`.venv/` in the project folder, so your system Python is untouched), installs [`requirements.txt`](requirements.txt) into it with [uv](https://docs.astral.sh/uv/) (a fast installer, set up automatically), and downloads ExifTool for Exif Info at the same time. That's about 40 MB, so the first launch takes 5 to 30 seconds depending on your connection. Later launches start in about a second; when `requirements.txt` changes (e.g. a Dependabot update), the reinstall takes under a second.

### macOS

Double-click **`FotoNerveShatter.app`** in the project folder. Foto Nerve Shatter starts in the background (no Terminal window) and your browser opens.

- **First launch:** if macOS asks whether Foto Nerve Shatter can access your Downloads folder or a removable volume, click **Allow**. Foto Nerve Shatter needs this to scan your photos.
- **On another Mac:** if macOS says *"Apple could not verify FotoNerveShatter is free of malware"*, or the app says it *can't find its project folder* (or `sh: ./app.conf: No such file or directory`), that's Gatekeeper: the launchers are signed locally, not notarized by Apple, so macOS blocks copies that arrive by download, AirDrop, or zip. Either:
  - **Rebuild the launchers on that Mac (recommended).** In Terminal, from the project folder, run `launcher/build-app.sh` once. Launchers built on the Mac itself aren't blocked.
  - **Or clear the quarantine flag** without rebuilding: in Terminal, from the project folder, run `xattr -dr com.apple.quarantine .`

  System Settings' **Open Anyway** isn't enough on its own: it gets past the warning, but macOS then runs the app from a temporary copy where it can't find `app.conf` and `server.sh`.
- **To stop it or reopen the browser:** double-click FotoNerveShatter.app again. A dialog says Foto Nerve Shatter is already running and offers **Open in Browser** or **Stop Foto Nerve Shatter**. If you keep another copy of the project and launch the app from there, it detects the running instance on the configured port and shows the same dialog.
- **Dock shortcut:** drag FotoNerveShatter.app onto the Dock. Keep the app itself in the project folder, because it uses `server.sh` next to it.

Prefer a Terminal window? Double-click **FotoNerveShatter.command** instead; it starts Foto Nerve Shatter from a Terminal window, and pressing Return there stops it. You can also use the `server.sh` commands below (`./server.sh logs` follows the server log; see [Logging](docs/logging.md)).

### Linux

From the project folder:

```bash
./server.sh start         # start in the background and open the browser
./server.sh stop          # stop it
./server.sh status        # check whether it's running
./server.sh logs          # follow the app's log (~/Library/Logs/FotoNerveShatter/app.log)
./server.sh restart
```

Add a port number to `start` or `restart` (e.g. `./server.sh start 8080`) to use a different port. Alternatively, edit `app.conf` (`PORT=5900`) so FotoNerveShatter.app and `server.sh` share the same setting.

### Windows

From the project folder in Command Prompt or PowerShell:

```bash
python app.py             # start (use "py app.py" if "python" isn't found)
python app.py 8080        # start on a different port
```

Leave the window open while you use Foto Nerve Shatter, and press **Ctrl+C** in it to stop. (Under WSL, use the Linux instructions.)

## Requirements

- Python 3.12+ (macOS includes Perl and curl, which ExifTool's download uses)

Everything else is installed automatically into `.venv/` from [`requirements.txt`](requirements.txt), which Dependabot keeps current:

- **Pillow**, **numpy**: required
- **uv**: the installer `app.py` uses for the rest (installed with pip first; if it can't be, pip is used instead)
- **rawpy** (full RAW support), **pillow-heif** (HEIC/HEIF), **onnxruntime** (Blur Check's AI quality model), **PyExifTool** (runs ExifTool for Exif Info): optional, marked `# optional` in `requirements.txt`. Each is installed on its own, so if one fails (e.g. no build for a new Python version yet) only that feature is turned off.

No external web framework is needed; it uses Python's built-in `http.server`. To start over with a clean environment, delete `.venv/` and launch again.

## Issue Types

| Status | Meaning |
|--------|---------|
| **Partial** | File is truncated, so image data is incomplete. Repair may help. |
| **Corrupt** | Invalid headers, missing SOI marker, or destroyed structure. Salvage may help for JPEGs. |
| **EXIF Only** | File contains metadata but no recoverable image content. |
| **Empty** | File is 0 bytes. |
| **Unsupported** | Format requires an optional library that isn't installed. |
| **Error** | Permission denied or unexpected I/O error. |

How each status is decided, and the corruption percentage: [Issue types](docs/issue-types.md).

## Recovery Techniques

### Repair JPEG

For **truncated** JPEGs where the header is intact but the file was cut short. The repair decodes all surviving pixel data using Pillow's truncation-tolerant mode, preserves the original EXIF metadata and ICC color profile, and re-encodes as a structurally clean JPEG. The result opens in any viewer without errors.

### Salvage Image

For **corrupt** JPEGs where the beginning of the file has been zeroed out (missing SOI marker). Three strategies are tried in order:

1. **Embedded tables**: if the file's own DQT/DHT/SOF0 tables survived, just prepend the SOI marker. This produces a perfect reconstruction with no data loss.

2. **Donor grafting + MCU remap**: finds a working JPEG from the same directory, extracts its quantization and Huffman tables, grafts them onto the surviving compressed data, then remaps MCU blocks to their correct grid positions using RST marker alignment. Recovers 80-95% of the image depending on how much data was zeroed.

3. **Simple graft**: for files without restart markers, grafts donor tables and decodes what's available. Content appears at the top; unrecoverable data is gray.

### Export Preview

For **RAW files** that can't be fully decoded, extracts the embedded JPEG preview that most cameras store inside the RAW container. This is typically a full-resolution JPEG that the camera generated at capture time.

More detail, including which action fits which status: [Recovery techniques](docs/recovery.md).

## EXIF Info

Click **Exif Info** to scan every image and video in a directory for metadata. Results appear as a card grid grouped by folder. Each card shows:

- Thumbnail (lazy-loaded as you scroll, so it handles 10k+ files efficiently)
- Camera make and model, and the lens
- Capture time (when the photo was taken)
- Exposure settings (aperture, shutter speed, ISO, focal length)
- Image dimensions and file size
- GPS coordinates (clickable link to Google Maps, when available)
- A note when camera details are missing, instead of an empty card: removed on export by an editor (e.g. Lightroom's *Include: Copyright Only*), or simply not in the file (e.g. photos saved from messaging apps, screenshots)

Supports JPEG, PNG, HEIC, TIFF, WebP, and every supported RAW format (NEF, ARW, CR2, CR3, DNG, RAF, RW2, ORF, PEF, SRW, and more). Videos show a placeholder icon. Click a photo's thumbnail to preview it in the lightbox (see [Lightbox preview](#lightbox-preview)); click a filename, or a video's thumbnail, to reveal the file in Finder / Explorer.

Each file also gets the same integrity check as Scan Directory: damaged files get a red **Damaged** tag (hover for the exact problem), are counted in the summary, and the CSV export includes Integrity columns. The check decompresses every file, including RAW sensor data, so it's the slowest part of Exif Info on RAW-heavy folders; RAW files are checked four at a time in separate processes (e.g. 20 iPhone 17 Pro ProRAW DNGs: about 8 seconds; 40 Nikon D810 NEFs: about 5).

**ExifTool:** metadata is read by [ExifTool](https://exiftool.org), which knows practically every camera's files, including lens names hidden in maker notes, and is updated for new cameras every few weeks. The app keeps its own copy (about 8 MB, checksum-verified, in `~/Library/Caches/FotoNerveShatter/exiftool`, outside the project): it's downloaded at launch whenever it's missing or older than `EXIFTOOL_MIN_VERSION` in `app.conf`, and the panel above the results offers an **Update** when exiftool.org has a newer release. No Homebrew or PATH setup is needed; an `exiftool` you installed yourself is used only until the app's copy is in place. With ExifTool, videos also show their camera, capture time, and GPS. Until it's available, a basic built-in reader shows the common fields for JPEG, HEIC, and some RAW files.

How metadata and thumbnails are read: [EXIF Info](docs/exif.md).

## Blur Check

Click **Blur Check** to score every photo in a directory for blur. Results appear as a thumbnail grid grouped by folder, blurriest first, each with a blur score from **0 (sharp)** to **100 (very blurry)**.

- **Blur threshold slider:** photos scoring at or above it count as blurry; by default only those are shown. Moving it re-filters instantly (no rescan), and the setting is remembered. **Default** resets it to 50.
- **Show all photos** lists every photo, with the blurry ones outlined in red.
- **Score colours:** green below 15, yellow from 15 to 49, red at 50 or above (fixed bands, whatever the slider is set to).
- **ⓘ on each score:** click it to see what the score means at your current threshold and what it was based on: the AI quality rating, the sharpness measure, how much of the frame has detail, and anything that raised the score (very little fine detail) or changed how it was measured (a RAW scored from its JPEG companion). A damaged file's pop-out says the score covers only the readable part.
- **Low detail:** photos that are mostly smooth sky, silhouette, haze, or plain surfaces (a moon, a sunrise over a ridge, fog) have too little detail to judge focus and can score high even when perfectly sharp. When under 20% of the frame has detail, the photo gets a grey **Low detail** tag whose ⓘ explains why and what the score was based on, its score turns grey (for reference only), and it never counts as blurry: it's listed under **Show all photos**, sorted last, and counted separately in the summary. Check these by eye in the preview at 100%.
- **Export CSV** saves every photo's score, its components (including Low Detail and Detail %), and whether it's blurry at the current threshold.
- **Preview:** click a thumbnail to check a photo full screen and zoom in to 100% (see [Lightbox preview](#lightbox-preview)); the caption shows its blur score.

### AI-assisted scoring

Blur Check combines two measurements:

1. **A sharpness measure** (always available): the variance of the Laplacian, scored by the photo's sharpest region so a sharp subject on a soft, out-of-focus background (bokeh) still counts as sharp, checked in every direction to catch camera shake, and contrast-normalized so dark photos aren't penalized. It's good at blur specifically, but its scale depends on the scene: a crisp portrait has less edge detail than crisp carved stone, so one threshold doesn't fit every folder.
2. **An AI quality model** (optional, recommended): **CLIP-IQA+**, a trained image-quality model that judges photos the way people do across cameras and scenes. On its own it also marks dark photos down, which is why it's combined with the sharpness measure rather than used alone.

A third check catches photos that look ordinary to both: ones smeared by camera shake, soft low-resolution exports, or heavy phone noise reduction can keep plenty of edge contrast while losing nearly all fine detail. When a photo's sharpest areas have almost no fine detail (measured in the frequency domain), it's flagged, unless the AI model rates the photo above average (some phones' own processing leaves sharp photos with little fine detail too).

Before scoring, dark photos are brightened (shadows lifted most, like raising exposure in an editor), because underexposure is fixable in post-processing and shouldn't count as blur. This happens on an in-memory copy; files are never modified.

The two scores are standardized against a reference library and blended, with the AI model weighted 60% and the sharpness measure 40% (the AI model judges bokeh portraits and smeared zooms better; the sharpness measure catches real softness the AI model can miss, and isn't fooled by dark photos). The default threshold of 50 sits on the boundary between photos the owner judged sharp and photos they judged blurry (41 photos from 11 cameras, 2001 to 2025). On an 851-photo curated iPhone/Nikon D810 library, 17 photos (2%) are flagged at the default.

**Installing the model:** the first Blur Check without it shows **Basic scoring** with a **Download model** button (146 MB, one time). The app downloads it with `curl`, verifies its SHA-256 checksum, and stores it in `models/`. It needs `onnxruntime`, which the app installs automatically on startup (optional: if that install fails, Blur Check keeps using basic scoring).

**Speed:** about 0.25 s per photo with the AI model (an 851-photo folder takes under 4 minutes), versus about 15 seconds for the whole folder with basic scoring.

**License:** the model file is **not** covered by this project's MIT license. It combines OpenAI's CLIP image encoder (MIT) with learned prompts from pyiqa (PolyForm Noncommercial), so it's for **non-commercial use only**. See [`models/MODEL_LICENSE.md`](models/MODEL_LICENSE.md).

#### Publishing the model (maintainers)

The 146 MB model is too big for git, so it's distributed as a GitHub release file:

1. Build it (or use the copy in `models/`): see the instructions at the top of [`tools/export_quality_model.py`](tools/export_quality_model.py). It needs PyTorch in a throwaway virtual environment, checks that the exported model reproduces pyiqa exactly, and prints the file's SHA-256, which must match `QUALITY_MODEL_SHA256` in `backend/blur/quality_model.py`.
2. Create a GitHub release tagged `quality-model-v1` and attach `models/clipiqa_plus_rn50.onnx` and `models/MODEL_LICENSE.md`.
3. `QUALITY_MODEL_URL` in `app.conf` already points at that release file.

**Limitations:** neither measurement knows what you *meant* to focus on, so a photo with the background in focus and the subject soft can count as sharp. Intentional softness (long-exposure water, mist, haze) can score as blurry. The calibration rests on a small set of photos the owner judged (41 from 11 cameras) plus one large library, so if the default doesn't match your eye, the slider is the fix. RAW files are scored from their embedded full-size preview when there is one. When the preview is too small (e.g. iPhone DNGs), a same-name JPEG/HEIC saved alongside it (RAW+JPEG shooting) is scored instead; without one, the sensor data is decoded and lightly sharpened to approximate the camera's processing. The card's tooltip says which was used.

## Lightbox Preview

Click a photo's thumbnail in Exif Info or Blur Check to view it full screen. Browsers can't display RAW files (or HEIC/TIFF in Chrome), so the server renders an upright JPEG of each photo: for RAW files, from the camera's embedded preview (full resolution on most cameras), a same-name JPEG/HEIC saved alongside it, or the sensor data, in that order.

- **Arrow keys** (or the ‹ › buttons) step through the photos visible in that section, in their current order; **Escape** or a click on the dark background closes.
- **Click** the photo to zoom to 100%, the way you'd check focus before culling; the full-resolution version loads only then. Scroll or drag to pan; click again or press **Escape** to zoom back out. Photos already shown at their actual size (e.g. small images) can't be zoomed, so they show no zoom cursor and the caption says *100%*.
- The caption shows the filename, blur score (in Blur Check), a **Damaged** tag if the file failed its integrity check, and, at 100%, the full-resolution size. The folder button reveals the photo in Finder / Explorer.
- Videos aren't previewed; their thumbnail reveals the file instead.

Previews are cached in memory (up to 256 MB) and in the browser for a day; **Clear Cache** under the settings cog empties both.

## How It Works

The backend is a Python HTTP server (built on `http.server`, no framework) with a thread pool (4 workers) for parallel file checking. `app.py` is only the entry point: it installs missing dependencies and starts the server. The application lives in `backend/`:

| Module | What it does |
|---|---|
| `server.py` | HTTP handler: serves the frontend and the `/api/` endpoints |
| `integrity/` | Integrity checks, one module per format family (`jpeg`, `png`, `heic`, `raw`, `video`, `generic`), and `check_integrity()`, which every scan uses |
| `scan.py` | Scan Directory and the pre-scan media count |
| `exif.py`, `thumbnails.py` | EXIF extraction and the Exif Info scan; card thumbnails |
| `blur/` | Blur Check: `calibration.py` (every tunable number), `loading.py`, `sharpness.py`, `quality_model.py`, `score.py`, `scan.py` |
| `tiff.py` | TIFF structure parsing and embedded RAW preview extraction |
| `preview.py` | Lightbox previews: upright JPEGs at screen size or full resolution |
| `repair.py` | JPEG salvage |
| `config.py`, `formats.py`, `jobs.py` | Paths and `app.conf`, supported extensions, scan cancellation |

The frontend is `index.html`, `css/styles.css`, and plain scripts in `js/`, one per feature (`scan.js`, `exif.js`, `blur.js`, `lightbox.js`, `browse.js`, `history.js`, `recovery.js`, `mount.js`), with shared helpers in `core.js` and startup in `main.js`. No build step, no node_modules, no framework dependencies.

Scan results stream to the browser in real time via SSE. Each file is validated by a format-specific checker that examines container structure (headers, markers, atoms) and attempts a full Pillow decode. Previous scans are persisted to IndexedDB (last 10) and listed in the Previous scans dropdown; picking one loads it.

Module responsibilities, every API endpoint, and the concurrency model: [Architecture](docs/architecture.md).

## Documentation

| Doc | Covers |
|---|---|
| [Architecture](docs/architecture.md) | Code layout (backend modules, frontend scripts), startup, API endpoints, request flow, concurrency, privacy |
| [Supported formats](docs/supported-formats.md) | Which extensions are scanned, how each format family is validated, optional libraries, adding a format |
| [Issue types](docs/issue-types.md) | What each status means, how it's decided, RAW tail damage, corruption percentage |
| [Recovery techniques](docs/recovery.md) | Repair JPEG, Salvage Image, and Export Preview in detail |
| [EXIF Info](docs/exif.md) | What the cards show, the integrity check, how metadata, thumbnails, and lightbox previews are read, CSV export |
| [Logging](docs/logging.md) | Where the server's output goes and how to read it |

## License

MIT. ExifTool isn't bundled; when the app downloads it, it's under ExifTool's own license (the same terms as Perl). The AI quality model is non-commercial only (see [AI-assisted scoring](#ai-assisted-scoring)).
