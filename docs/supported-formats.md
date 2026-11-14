# Supported Formats

A file is included in a scan only if its extension (case-insensitive) is in the `SUPPORTED_EXTENSIONS` set in `backend/formats.py`. Each family routes to a dedicated checker in `backend/integrity/` via `check_image()`.

| Category | Extensions | Checker |
|----------|-----------|---------|
| JPEG | `.jpg` `.jpeg` `.jpe` `.jfif` | `check_jpeg` (`jpeg.py`): SOI/SOS marker analysis + full Pillow decode |
| PNG | `.png` | `check_png` (`png.py`): signature + IHDR/IEND chunks + decode |
| HEIC/HEIF | `.heic` `.heif` | `check_heic` (`heic.py`): HEIF box structure walk + decode via pillow-heif |
| TIFF | `.tif` `.tiff` | `check_generic_pillow` (`generic.py`) |
| RAW | `.nef` `.nrw` `.arw` `.srf` `.sr2` `.cr2` `.cr3` `.dng` `.raf` `.rw2` `.orf` `.pef` `.srw` | `check_raw` (`raw.py`): TIFF structure parse (NEF/ARW) + rawpy decode |
| Other | `.webp` `.bmp` `.gif` | `check_generic_pillow` (`generic.py`) |
| Video | `.mp4` `.m4v` `.mov` `.avi` `.mpg` `.mpeg` | `check_mp4` / `check_avi` / `check_mpeg` (`video.py`): container walk |

Blur Check scores every supported format except videos.

## How each family is validated

- **JPEG**: checks for the SOI marker (`FF D8`), looks for a Start-of-Scan marker to confirm image data exists, then does a strict Pillow decode (truncation-tolerant mode is deliberately off, so cut-short files surface as `Partial`).
- **PNG**: verifies the 8-byte signature, that the first chunk is `IHDR`, and that `IEND` is present in the tail, then decodes.
- **HEIC/HEIF**: walks the container's boxes without decoding to check that the structure is there and no image tile's data runs past the end of the file (truncated files are `Partial`, with the share of tiles affected), then decodes with pillow-heif.
- **RAW (NEF/ARW)**: parses the TIFF container (IFD chain + SubIFDs) to tell whether image-data tags exist and point inside the file, then attempts a full rawpy decode and inspects LibRaw's reported corruption offset. Other RAW formats go straight to the rawpy decode.
- **Video**: walks the container structure (ISOBMFF atoms for MP4/MOV, RIFF chunks for AVI, start codes for MPEG) and flags missing essential atoms/chunks or truncation, without decoding frames.

## Optional libraries

- **rawpy** enables full RAW decoding. Without it, RAW files fall back to a structural check plus a Pillow attempt.
- **pillow-heif** enables HEIC/HEIF (iPhone photos). Without it, the structure walk still catches truncated HEIC files, but ones that look intact are reported as `Unsupported` because they can't be decoded.

Both are installed automatically on first run when possible (and listed in `requirements.txt` for manual installs). The header shows whether they're available, from `/api/libs`.

## Adding a format

Add the extension to `SUPPORTED_EXTENSIONS` and the appropriate family set (e.g. `JPEG_EXTS`, `RAW_EXTS`, `VIDEO_EXTS`) in `backend/formats.py`, then route it in `check_image()` (`backend/integrity/__init__.py`) to a checker. Add it to `RAW_EXTS` in `js/core.js` too if it's a RAW format, so the Export Preview button appears.
