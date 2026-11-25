# EXIF Info

Click **Exif Info** to scan every image and video in a directory for metadata. Results stream in over SSE and appear as a card grid grouped by folder.

## What each card shows

- **Thumbnail**: lazy-loaded, fetched only as the card scrolls into view, so the grid stays responsive across 10,000+ files.
- **Camera**: make and model (the make is dropped when the model already names the brand, e.g. *Canon EOS R5*).
- **Lens**: the lens name, when the file records one (see below).
- **Capture time**: when the photo was taken (`DateTimeOriginal`), falling back to `DateTimeDigitized`, then `DateTime` (last modified).
- **Exposure settings**: aperture (f-number), shutter speed (1/250s below 0.3 seconds, else seconds such as 0.3s or 2.5s), ISO, focal length.
- **Dimensions and file size**.
- **GPS coordinates**: when present, shown as a clickable link to Google Maps.
- **Export note**: when a photo has no camera metadata at all but was written by an editor, the card says so instead of showing nothing, e.g. *Camera metadata removed on export (Lightroom or Photoshop)*: Lightroom's Export dialog can strip metadata (Metadata › Include: Copyright Only), leaving only Adobe's XMP signature. The editor's name is shown when the file still records it (`CreatorTool` / `Software`, e.g. *Adobe Photoshop Lightroom Classic*). Re-export with *All Metadata*, or scan the originals. Photos with no camera make or model and no editor signature say *No camera details in this file* (in grey): typical of photos saved from messaging or social apps, which remove camera details when sharing, and of screenshots and scans. Each note has an ⓘ bubble: click it (or press Enter on it) for a pop-out explaining the possible reasons, plus, for small copies, a remark that the size points to a shared or downloaded copy. RAW files and videos get no note. The CSV has a *Metadata Note* column.
- **Damaged tag**: a red **Damaged** tag when the integrity check finds a problem (see below); hover for the exact problem.

Clicking a photo's thumbnail opens it in the lightbox (full screen, arrow keys to step through, click to zoom to 100%; see [Lightbox Preview](lightbox.md)). Clicking a filename, or a video's thumbnail, reveals the file in Finder / Explorer.

## Supported inputs

JPEG, PNG, HEIC, TIFF, WebP, and RAW formats are read for metadata. Videos are listed with a play icon and their extension instead of a thumbnail; ExifTool also gives them their camera, capture time, GPS, and dimensions.

## Integrity check

Every file also gets the same integrity check as Scan Directory. Damaged files are tagged on their card and counted in the summary and folder headers, and the CSV export includes Integrity columns. `Unsupported` means the file couldn't be checked, not that it's damaged; see [Issue types](issue-types.md).

The check decompresses every file, including RAW sensor data, so it's the slowest part of Exif Info on RAW-heavy folders; RAW files are checked four at a time in separate processes (e.g. 20 iPhone 17 Pro ProRAW DNGs: about 8 seconds; 40 Nikon D810 NEFs: about 5).

## How it works

- **Metadata is read by [ExifTool](https://exiftool.org).** ExifTool reads practically every camera's files, including each maker's private maker notes (which is where many cameras keep the lens name), and its author adds new cameras every few weeks, so new formats and models need no changes here. The app uses its **own copy**, kept in the user's cache folder (`~/Library/Caches/FotoNerveShatter/exiftool`, outside the project) and run with the system's Perl:
  - **At launch**, if that copy is missing or older than `EXIFTOOL_MIN_VERSION` (`app.conf`), the latest release is downloaded in the background: the version from exiftool.org, the archive from exiftool.org's SourceForge downloads, checked against the SHA-256 exiftool.org publishes. Raise `EXIFTOOL_MIN_VERSION` to require a newer ExifTool on every Mac.
  - **Updates**: while ExifTool is installed, the app checks exiftool.org's version once a day, and the status box above the results offers **Update** when there's a newer release.
  - **Another exiftool** (e.g. from Homebrew) is used only until the app's copy is in place, e.g. while it downloads on first launch.
  - The **status box** appears only when something needs attention: a download in progress or failed, an update, or ExifTool unavailable.

  One ExifTool process stays open for the whole scan (via the PyExifTool package), so it costs about 9 ms per file. ExifTool also reads **video** metadata (camera, capture time, GPS, and dimensions, swapped for clips filmed in portrait), which the built-in reader can't. Tested on 32 clips from iPhone 4 to 17 Pro, Canon, Fujifilm, Panasonic, and Nikon cameras, including recovered files. Lens names come from ExifTool's `LensID` (decoded from maker notes, e.g. *AF-S Zoom-Nikkor 24-70mm f/2.8G ED*), falling back to `LensModel`.
- **Built-in reader (basic fallback)**: used until ExifTool is available, or for a file ExifTool can't read. It reads Pillow's EXIF (IFD0, the Exif sub-IFD, and the GPS sub-IFD) for JPEG, HEIC, TIFF, PNG, and the RAW files Pillow can open (e.g. NEF, DNG); other RAW files and videos show only their dimensions. It isn't extended for new cameras; that's ExifTool's job. The `metadata_source` field of each result says which reader was used.
- Values are normalized either way: `f/2.8`, `1/250s` (seconds from 0.3 s up, e.g. `0.3s`, `2.5s`), `35mm`, signed decimal GPS degrees; capture time is the first of `DateTimeOriginal` (photos, and Canon's movie EXIF), `CreationDate` (iPhone videos: the local time where the clip was filmed; the QuickTime `CreateDate` is UTC on iPhones and is rewritten when Photos exports a slow-motion or trimmed clip), `CreateDate`, and `ModifyDate`. QuickTime `CreateDate` is shown as stored, ExifTool's default: most cameras write their clock's local time there, but a few devices write UTC, so a video with no other date (e.g. a re-encoded clip with its metadata stripped) can be off by the time-zone difference.
- **Dimensions** always come from the file itself, as displayed: rotated for portrait photos, and for RAW files LibRaw's decoded image size (which excludes the masked sensor border).
- Thumbnails are generated on demand at up to 300 px, rotated upright, re-encoded as quality-72 JPEG, and cached in an in-memory LRU (up to 1000 entries) so re-scrolling is instant. For RAW files the camera's embedded thumbnail is used when possible, avoiding a full decode. Blur Check cards use the same thumbnails. **Clear Cache** (under the settings cog) empties this cache.
- Lightbox previews are rendered by `backend/preview.py`: an upright JPEG at 2560 px (the screen-size version) and, when the photo is zoomed in, at full resolution. RAW files use the camera's embedded preview when it's at least 1024 px, else a same-name JPEG/HEIC, else the sensor data. Previews are cached in memory up to 256 MB.
- Metadata, thumbnails, and previews are read in tolerant mode (unlike the integrity check), so even damaged files still yield a thumbnail and whatever metadata survived.

## Export

Exif Info results can be exported to CSV from the UI (built in the browser by `js/exif.js`), the same way Scan Directory results are.

Endpoints: `GET /api/exif-scan?dir=` (SSE stream), `GET /api/thumbnail?path=` (per-card image), `GET /api/preview?path=[&full=1]` (lightbox), `POST /api/exif-cancel` (stop), `GET /api/exiftool` (ExifTool status) and `POST /api/exiftool/download` (download or update it).

## Using Exif Info

Click **Exif Info** to scan every image and video in a directory for metadata. Results appear as a card grid grouped by folder. Each card shows:

- Thumbnail (lazy-loaded as you scroll, so it handles 10k+ files efficiently)
- Camera make and model, and the lens
- Capture time (when the photo was taken)
- Exposure settings (aperture, shutter speed, ISO, focal length)
- Image dimensions and file size
- GPS coordinates (clickable link to Google Maps, when available)
- A note when camera details are missing, instead of an empty card: removed on export by an editor (e.g. Lightroom's *Include: Copyright Only*), or simply not in the file (e.g. photos saved from messaging apps, screenshots)

Supports JPEG, PNG, HEIC, TIFF, WebP, and every supported RAW format (NEF, ARW, CR2, CR3, DNG, RAF, RW2, ORF, PEF, SRW, and more). Videos show a placeholder icon. Click a photo's thumbnail to preview it in the lightbox (see [Lightbox preview](lightbox.md)); click a filename, or a video's thumbnail, to reveal the file in Finder / Explorer.

Each file also gets the same integrity check as Scan Directory: damaged files get a red **Damaged** tag (hover for the exact problem), are counted in the summary, and the CSV export includes Integrity columns. The check decompresses every file, including RAW sensor data, so it's the slowest part of Exif Info on RAW-heavy folders; RAW files are checked four at a time in separate processes (e.g. 20 iPhone 17 Pro ProRAW DNGs: about 8 seconds; 40 Nikon D810 NEFs: about 5).

**ExifTool:** metadata is read by [ExifTool](https://exiftool.org), which knows practically every camera's files, including lens names hidden in maker notes, and is updated for new cameras every few weeks. The app keeps its own copy (about 8 MB, checksum-verified, in `~/Library/Caches/FotoNerveShatter/exiftool`, outside the project): it's downloaded at launch whenever it's missing or older than `EXIFTOOL_MIN_VERSION` in `app.conf`, and the panel above the results offers an **Update** when exiftool.org has a newer release. No Homebrew or PATH setup is needed; an `exiftool` you installed yourself is used only until the app's copy is in place. With ExifTool, videos also show their camera, capture time, and GPS. Until it's available, a basic built-in reader shows the common fields for JPEG, HEIC, and some RAW files.
