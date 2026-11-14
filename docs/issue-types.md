# Issue Types

Every scanned file is classified into one status. In Scan Directory, anything that isn't `OK` is reported as an issue, grouped by folder and included in the CSV export. Exif Info and Blur Check run the same check and mark damaged files with a red **Damaged** tag.

| Status | Meaning | Typical next step |
|--------|---------|-------------------|
| **OK** | File decodes completely and cleanly. Not shown as an issue. | n/a |
| **Partial** | File is truncated: the header is intact but image data is incomplete. | [Repair JPEG](recovery.md#repair-jpeg) for JPEGs; [Export Preview](recovery.md#export-preview) for RAW |
| **Corrupt** | Invalid headers, missing SOI marker, or destroyed structure. | [Salvage Image](recovery.md#salvage-image) for JPEGs; [Export Preview](recovery.md#export-preview) for RAW |
| **EXIF Only** | File contains metadata but no recoverable image content. | Usually unrecoverable; metadata may still be useful |
| **Empty** | File is 0 bytes. | Unrecoverable |
| **Unsupported** | Format needs an optional library that isn't installed, or a variant the library can't read. This means "couldn't check", not damaged. | Install rawpy / pillow-heif (see [Supported formats](supported-formats.md)) |
| **Error** | Permission denied or unexpected I/O error. | Check file permissions / drive health |

## How the status is decided

The status comes from the format-specific checker (`check_jpeg`, `check_raw`, etc. in `backend/integrity/`). In general:

1. **Size gates first**: 0 bytes → `Empty`; too small to hold a valid header → `Corrupt`.
2. **Structure next**: signature/marker/atom checks. A missing container structure is `Corrupt`; a structure that declares more data than the file holds is `Partial`.
3. **Full decode last**: the definitive test. A clean decode is `OK`; a decode that fails with a truncation error is `Partial`; any other decode failure is `Corrupt`.

For RAW files, the scanner additionally parses LibRaw's reported corruption offset. Damage confined to the last 5% of the file, when a full-resolution embedded preview survives, is reported as `Partial` with a note that the file is still usable, rather than as outright corruption.

For damaged RAW files, Scan Directory also checks whether the embedded preview can be located and decodes fully, and only offers **Export Preview** when it can (it can't when the RAW header that points to the preview is gone, e.g. a recovered file whose start was zeroed).

## Corruption percentage

When LibRaw reports where the data goes bad, the scanner computes what fraction of the file is affected and attaches it to the issue (shown in the UI and the CSV's *Corruption %* column). This helps you triage: a file that's 0.2% corrupt at the tail is very different from one that's 60% gone.
