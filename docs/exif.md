# EXIF Info

Click **Exif Info** to scan every image and video in a directory for metadata. Results stream in over SSE and appear as a card grid grouped by folder.

## What each card shows

- **Thumbnail**: lazy-loaded, fetched only as the card scrolls into view, so the grid stays responsive across 10,000+ files.
- **Camera**: make and model.
- **Capture time**: from `DateTimeOriginal`, falling back to `DateTime`.
- **Exposure settings**: aperture (f-number), shutter speed, ISO, focal length.
- **Dimensions and file size**.
- **GPS coordinates**: when present, shown as a clickable link to Google Maps.
- **Damaged tag**: a red **Damaged** tag when the integrity check finds a problem (see below); hover for the exact problem.

Clicking a photo's thumbnail opens it in the lightbox (full screen, arrow keys to step through, click to zoom to 100%; see [Lightbox Preview](../README.md#lightbox-preview)). Clicking a filename, or a video's thumbnail, reveals the file in Finder / Explorer.

## Supported inputs

JPEG, PNG, HEIC, TIFF, WebP, and RAW formats are read for metadata. Videos are listed with a play icon and their extension instead of a thumbnail (no EXIF is extracted from video containers).

## Integrity check

Every file also gets the same integrity check as Scan Directory. Damaged files are tagged on their card and counted in the summary and folder headers, and the CSV export includes Integrity columns. `Unsupported` means the file couldn't be checked, not that it's damaged; see [Issue types](issue-types.md).

The check fully decodes every file, including RAW sensor data, so Exif Info is slower on RAW-heavy folders (125 NEFs: about 60 seconds instead of 15).

## How it works

- Metadata is read with Pillow's `getexif()` and GPS sub-IFD, normalized into clean values (rationals converted to `f/2.8`, `1/250s`, `35mm`; GPS DMS converted to signed decimal degrees).
- For **RAW** files, dimensions come from rawpy when available, and embedded-JPEG EXIF is read via Pillow.
- Thumbnails are generated on demand at up to 300 px, rotated upright, re-encoded as quality-72 JPEG, and cached in an in-memory LRU (up to 1000 entries) so re-scrolling is instant. For RAW files the camera's embedded thumbnail is used when possible, avoiding a full decode. Blur Check cards use the same thumbnails. **Clear Cache** (under the settings cog) empties this cache.
- Lightbox previews are rendered by `backend/preview.py`: an upright JPEG at 2560 px (the screen-size version) and, when the photo is zoomed in, at full resolution. RAW files use the camera's embedded preview when it's at least 1024 px, else a same-name JPEG/HEIC, else the sensor data. Previews are cached in memory up to 256 MB.
- Metadata, thumbnails, and previews are read in tolerant mode (unlike the integrity check), so even damaged files still yield a thumbnail and whatever metadata survived.

## Export

Exif Info results can be exported to CSV from the UI (built in the browser by `js/exif.js`), the same way Scan Directory results are.

Endpoints: `GET /api/exif-scan?dir=` (SSE stream), `GET /api/thumbnail?path=` (per-card image), `GET /api/preview?path=[&full=1]` (lightbox), `POST /api/exif-cancel` (stop).
