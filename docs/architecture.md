# Architecture

Foto Nerve Shatter is a local web app: a Python backend built on the standard library's `http.server` (no framework, no build step) that serves both the API and a static vanilla-JS frontend.

## Stack

- **Backend**: Python 3.10+, `http.server.ThreadingHTTPServer`, bound to `127.0.0.1` (port 5900 by default; `PORT` in `app.conf` or a command-line argument changes it).
- **Frontend**: plain HTML / CSS / JS, Josefin Sans + IBM Plex Mono fonts, dark theme.
- **Imaging**: Pillow (JPEG/PNG/TIFF/WebP/BMP/GIF decode), rawpy/LibRaw (RAW), pillow-heif (HEIC/HEIF). Without rawpy or pillow-heif the app still runs; those formats get a structural check only or are reported as `Unsupported`.
- **Blur Check**: numpy for the sharpness measures; onnxruntime (optional) for the AI quality model.

## Files

| Path | Responsibility |
|---|---|
| `app.py` | Entry point only: installs missing dependencies, then starts the server |
| `backend/` | The application (see below) |
| `index.html` | Layout: header, directory browser, scan controls, results, card grids |
| `css/styles.css` | All styles (dark theme, CSS variables) |
| `js/*.js` | Client logic, split by feature (see below) |
| `app.conf` | App name, title, port, and the AI model's download URL; read by `server.sh`, the launchers, and `backend/config.py` |
| `server.sh`, `launcher/` | Start/stop script and the macOS launchers that call it |
| `models/` | The AI quality model (downloaded in-app; not in git) and its license |
| `tools/export_quality_model.py` | One-off build script for the AI model; the app never runs it |

### Backend (`backend/`)

Modules import each other absolutely (`from backend.x import ...`).

| Module | Responsibility |
|---|---|
| `server.py` | `ScannerHandler` (a `SimpleHTTPRequestHandler`): static files from the project folder, everything under `/api/` handled explicitly. The JPEG repair path lives here (`_handle_repair_jpeg`) |
| `integrity/` | One checker per format family (`jpeg.py`, `png.py`, `heic.py`, `raw.py`, `video.py`, `generic.py`), dispatched by extension in `check_image()`; `check_integrity()` wraps it for the scans that report integrity alongside other results |
| `scan.py` | Scan Directory (`scan_directory_gen`) and the pre-scan media count (`count_media_gen`) |
| `exif.py` | EXIF extraction, orientation, and the Exif Info scan (`exif_scan_gen`) |
| `thumbnails.py` | Card thumbnails with an in-memory LRU cache |
| `blur/` | Blur Check: `calibration.py` (every tunable number), `loading.py`, `sharpness.py`, `quality_model.py`, `score.py` (`measure_blur`), `scan.py` (`blur_scan_gen`) |
| `tiff.py` | TIFF structure parsing for NEF/ARW and embedded preview extraction |
| `repair.py` | JPEG salvage (`salvage_jpeg`) |
| `config.py` | `APP_DIR` (the project root), `app.conf` settings, `WORKER_THREADS` |
| `formats.py` | Supported extensions, grouped by checker |
| `jobs.py` | Per-scan cancellation bookkeeping |

### Frontend (`js/`)

Plain global scripts (no build step, no ES modules), loaded in order by `index.html` with `core.js` first and `main.js` last. Top-level `let`/`const` declarations are shared across them. Buttons use inline `onclick` handlers in `index.html`; dynamically rendered rows and cards use click delegation in `main.js`.

| File | Responsibility |
|---|---|
| `core.js` | Shared constants and helpers (`escHtml`, `formatSize`, `statusLabel`, the integrity tag helpers), the library check, the busy lock that disables controls during a scan, thumbnail URLs, the settings menu |
| `browse.js` | Directory browser modal and the pre-scan media count |
| `history.js` | Saved Scan Directory results (IndexedDB) and the Previous scans dropdown |
| `recovery.js` | Export Preview, Repair JPG, and Salvage Image actions |
| `scan.js` | Scan Directory (SSE), results rendering, filtering, folder toggle, CSV export |
| `exif.js` | Exif Info (SSE), lazy-loaded thumbnail card grid, CSV export |
| `blur.js` | Blur Check (SSE), cards, threshold slider, AI model status and download, CSV export |
| `mount.js` | Volume mount/unmount watcher |
| `main.js` | Click delegation for result rows and cards, and startup (loads last) |

## Startup

`app.py` checks for Pillow, rawpy, pillow-heif, and numpy and installs any that are missing with pip before importing the backend; then it tries onnxruntime, which is optional (if that install fails, Blur Check uses basic scoring). The minimum versions it installs are listed in `_ensure_dependencies()`; `requirements.txt` is for installing everything manually.

## Scans

Scan Directory, Exif Info, and Blur Check are generators that walk a directory, check files with a `ThreadPoolExecutor` (`WORKER_THREADS`, 4, in batches of 16), and yield events that the server streams to the browser as Server-Sent Events. Exif Info and Blur Check run the same integrity check as Scan Directory on every file and merge its result into theirs.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/scan?dir=` | SSE: Scan Directory progress and issues |
| GET | `/api/exif-scan?dir=` | SSE: Exif Info metadata per file |
| GET | `/api/blur-scan?dir=` | SSE: Blur Check scores per photo |
| GET | `/api/count?dir=` | SSE: how many photos and videos a scan of the directory would process |
| GET | `/api/integrity?path=` | Integrity check of one file |
| GET | `/api/thumbnail?path=` | JPEG thumbnail, generated on demand and cached (LRU, 1000 entries) |
| GET | `/api/export` | CSV of the last Scan Directory's issues |
| GET | `/api/browse?path=` | Directory listing for the folder browser |
| GET | `/api/libs` | Which imaging libraries (Pillow, rawpy, pillow-heif) are available |
| GET | `/api/mount-status?path=` | SSE: mount/unmount events for the directory's volume |
| GET | `/api/quality-model` | AI model status: runtime installed, model present, download progress |
| POST | `/api/quality-model/download` | Start downloading the AI model |
| POST | `/api/cancel` | Cancel the running Scan Directory |
| POST | `/api/exif-cancel` | Cancel the running Exif Info scan |
| POST | `/api/blur-cancel` | Cancel the running Blur Check |
| POST | `/api/reveal` | Reveal a file or folder in Finder/Explorer |
| POST | `/api/extract-preview` | Extract the embedded JPEG preview from a RAW file |
| POST | `/api/repair-jpeg` | Re-encode a truncated JPEG cleanly |
| POST | `/api/salvage-image` | Reconstruct a JPEG with a destroyed header |
| POST | `/api/clear-cache` | Empty the thumbnail cache and the browser's HTTP cache for the app |

## Request flow

```
Browser ──/api/count─────────► shows how many files a scan will process
        ──/api/mount-status──► shows drive connected / ejected
        ──/api/scan──────────► streams issues as each file is checked
        ──/api/exif-scan─────► streams metadata cards
        ──/api/blur-scan─────► streams blur scores
        ──/api/thumbnail─────► lazy, only for cards scrolled into view
        ──/api/repair-jpeg───► returns a downloadable repaired file
```

CSV exports are built in the browser from the results already on the page.

## Concurrency model

`ThreadingHTTPServer` handles each connection on its own thread; scans fan out further with a `ThreadPoolExecutor`. Each scan type has one state object, and starting a scan cancels the previous one of the same type; the frontend's busy lock also disables the other scan buttons while one runs. RAW integrity checks briefly redirect process-wide stderr (to capture LibRaw's corruption offset) under a lock, so they're serialized. The AI model limits its own thread count so four parallel photos don't oversubscribe the CPU.

## Privacy

100% local. The server binds to `127.0.0.1` only: no account, no telemetry. The only network requests are the web fonts and, if you click **Download model** in Blur Check, the one-time model download from GitHub.
