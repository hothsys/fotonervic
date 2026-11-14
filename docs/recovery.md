# Recovery Techniques

Foto Nerve Shatter offers three one-click recovery actions on Scan Directory results, each targeting a different kind of damage. All of them are non-destructive: they read the damaged original and hand you a **new** downloadable file (`*_repaired`, `*_salvaged`, `*_preview`). The original is never modified.

## Repair JPEG

For **truncated** JPEGs where the header is intact but the file was cut short.

The repair decodes all surviving pixel data using Pillow's truncation-tolerant mode, preserves the original EXIF metadata and ICC color profile, and re-encodes as a structurally clean JPEG. The result is verified with a strict (non-tolerant) decode before it's returned, so it opens in any viewer without errors.

Endpoint: `POST /api/repair-jpeg` → returns `{stem}_repaired.jpg`.

## Salvage Image

For **corrupt** JPEGs where the beginning of the file has been zeroed out (missing SOI marker). Three strategies are tried in order:

1. **Embedded tables**: if the file's own DQT/DHT/SOF0 tables survived, just prepend the SOI marker. This produces a perfect reconstruction with no data loss.

2. **Donor grafting + MCU remap**: finds a working JPEG in the same directory, extracts its quantization and Huffman tables, grafts them onto the surviving compressed data, then remaps MCU blocks to their correct grid positions using RST marker alignment. Recovers roughly 80-95% of the image depending on how much data was zeroed.

3. **Simple graft**: for files without restart markers, grafts donor tables and decodes what's available. Content appears at the top; unrecoverable regions are gray.

Endpoint: `POST /api/salvage-image` → returns `{stem}_salvaged.jpg`.

> **Note:** strategies 2 and 3 need at least one healthy JPEG in the same folder to borrow tables from, ideally from the same camera. If the file's own tables are gone and no donor is found, salvage fails with "No valid donor JPEG found in the same directory".

## Export Preview

For **RAW files** that can't be fully decoded, extracts the embedded JPEG preview that most cameras store inside the RAW container. This is typically a full-resolution JPEG the camera generated at capture time, so even when the sensor data is unrecoverable you often still get a usable full-size image.

The app walks the RAW file's TIFF structure, every IFD and SubIFD (NEF stores previews in SubIFDs; ARW stores them in the main IFD chain), and extracts the **largest** preview it finds. The button only appears when a preview can be located and decodes fully; RAW formats that aren't TIFF-based, or files whose header was destroyed, don't get one.

Endpoint: `POST /api/extract-preview` → returns `{stem}_preview.jpg`.

## Which action for which status

| Status | Format | Action |
|--------|--------|--------|
| Partial | JPEG | Repair JPEG |
| Corrupt (missing SOI marker) | JPEG | Salvage Image |
| Partial / Corrupt | RAW | Export Preview |

See [Issue types](issue-types.md) for how each status is determined.
