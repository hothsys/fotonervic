# <img src="logo.svg" width="50" height="65" valign="bottom" />&nbsp;&nbsp;Foto Nerve Shatter
*I hope you never have to use this. But if you do, I hope it helps.*

This web app recursively scans directories for corrupt, truncated, or damaged image and video files. For images, it attempts recovery where possible. Also extracts EXIF metadata with thumbnail previews across an entire directory.

Built for data recovery scenarios where hundreds or thousands of photos have been rescued from a failing drive but many are partially damaged. The scanner identifies every problem file, categorizes the damage, and offers one-click repair or salvage for supported image formats.

## Features

- **Recursive scanning** with real-time progress via Server-Sent Events
- **Folder-grouped results** with filtering by issue type
- **Repair JPEG**: re-encodes truncated JPEGs while preserving EXIF metadata and ICC profiles
- **Salvage Image**: recovers JPEGs with destroyed headers (missing SOI) using donor-table grafting and MCU-level remapping
- **Export Preview**: extracts embedded JPEG previews from RAW files that can't be fully decoded
- **EXIF Info**: scans every image and video for metadata (camera, date, settings, GPS coordinates, dimensions) and displays it as a lazy-loaded thumbnail card grid grouped by folder
- **Volume mount detection**: detects when a drive is mounted/unmounted in real time and shows a status indicator
- **Previous scans**: last 10 scans persisted to IndexedDB; restore any previous scan from a dropdown without rescanning
- **CSV export** of scan results and EXIF data
- **Directory browser** with breadcrumb navigation
- **Reveal in Finder/Explorer**: jump to any file from the UI

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

## Starting and Stopping

Foto Nerve Shatter runs as a local web server at [http://localhost:5900](http://localhost:5900) and opens your browser when it starts. Missing dependencies are installed automatically on first run, so the first launch can take a minute.

### macOS

Double-click **`FotoNerveShatter.app`** in the project folder. Foto Nerve Shatter starts in the background (no Terminal window) and your browser opens.

- **First launch:** if macOS asks whether Foto Nerve Shatter can access your Downloads folder or a removable volume, click **Allow**. Foto Nerve Shatter needs this to scan your photos.
- **On another Mac:** if macOS says *"Apple could not verify FotoNerveShatter is free of malware"*, or the app says it *can't find its project folder* (or `sh: ./app.conf: No such file or directory`), that's Gatekeeper: the launchers are signed locally, not notarized by Apple, so macOS blocks copies that arrive by download, AirDrop, or zip. Either:
  - **Rebuild the launchers on that Mac (recommended).** In Terminal, from the project folder, run `launcher/build-app.sh` once. Launchers built on the Mac itself aren't blocked.
  - **Or clear the quarantine flag** without rebuilding: in Terminal, from the project folder, run `xattr -dr com.apple.quarantine .`

  System Settings' **Open Anyway** isn't enough on its own: it gets past the warning, but macOS then runs the app from a temporary copy where it can't find `app.conf` and `server.sh`.
- **To stop it or reopen the browser:** double-click FotoNerveShatter.app again. A dialog says Foto Nerve Shatter is already running and offers **Open in Browser** or **Stop Foto Nerve Shatter**.
- **Dock shortcut:** drag FotoNerveShatter.app onto the Dock. Keep the app itself in the project folder, because it uses `server.sh` next to it.

Prefer a visible log? Double-click **FotoNerveShatter.command** instead; it runs Foto Nerve Shatter in a Terminal window, and pressing Return there stops it. You can also use the `server.sh` commands below.

### Linux

From the project folder:

```bash
./server.sh start         # start in the background and open the browser
./server.sh stop          # stop it
./server.sh status        # check whether it's running
./server.sh logs          # follow the server log
./server.sh restart
```

Add a port number to `start` or `restart` (e.g. `./server.sh start 8080`) to use a different port.

### Windows

From the project folder in Command Prompt or PowerShell:

```bash
python app.py             # start (use "py app.py" if "python" isn't found)
python app.py 8080        # start on a different port
```

Leave the window open while you use Foto Nerve Shatter, and press **Ctrl+C** in it to stop. (Under WSL, use the Linux instructions.)

## Requirements

- Python 3.8+
- Pillow >= 10.0.0

No external web framework is needed; it uses Python's built-in `http.server`.

Optional (installed automatically if available):

- **rawpy >= 0.18.0**: full RAW format support (NEF, ARW, CR2, CR3, DNG, RAF, RW2, ORF, PEF, SRW)
- **pillow-heif >= 0.13.0**: HEIC/HEIF support (iPhone photos)

Or install everything manually:

```bash
pip install -r requirements.txt
```

## Issue Types

| Status | Meaning |
|--------|---------|
| **Partial** | File is truncated, so image data is incomplete. Repair may help. |
| **Corrupt** | Invalid headers, missing SOI marker, or destroyed structure. Salvage may help for JPEGs. |
| **EXIF Only** | File contains metadata but no recoverable image content. |
| **Empty** | File is 0 bytes. |
| **Unsupported** | Format requires an optional library that isn't installed. |
| **Error** | Permission denied or unexpected I/O error. |

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

## EXIF Info

Click **Exif Info** to scan every image and video in a directory for metadata. Results appear as a card grid grouped by folder. Each card shows:

- Thumbnail (lazy-loaded as you scroll, so it handles 10k+ files efficiently)
- Camera make and model
- Capture time
- Exposure settings (aperture, shutter speed, ISO, focal length)
- Image dimensions and file size
- GPS coordinates (clickable link to Google Maps, when available)

Supports JPEG, PNG, HEIC, TIFF, WebP, and RAW formats. Videos show a placeholder icon.

## How It Works

The backend is `app.py`, a Python HTTP server (built on `http.server`, no framework) with a thread pool (4 workers) for parallel file checking. The frontend is split across `index.html`, `css/styles.css`, and `js/app.js`. No build step, no node_modules, no framework dependencies.

Scan results stream to the browser in real time via SSE. Each file is validated by a format-specific checker that examines container structure (headers, markers, atoms) and attempts a full Pillow decode. Previous scans are persisted to IndexedDB (last 10) and restored automatically on page load.

## License

MIT
