# Lightbox preview

Click a photo's thumbnail in Exif Info or Blur Check to view it full screen. Browsers can't display RAW files (or HEIC/TIFF in Chrome), so the server renders an upright JPEG of each photo: for RAW files, from the camera's embedded preview (full resolution on most cameras), a same-name JPEG/HEIC saved alongside it, or the sensor data, in that order.

- **Arrow keys** (or the ‹ › buttons) step through the photos visible in that section, in their current order; **Escape** or a click on the dark background closes.
- **Click** the photo to zoom to 100%, the way you'd check focus before culling; the full-resolution version loads only then. Scroll or drag to pan; click again or press **Escape** to zoom back out. Photos already shown at their actual size (e.g. small images) can't be zoomed, so they show no zoom cursor and the caption says *100%*.
- The caption shows the filename, blur score (in Blur Check), a **Damaged** tag if the file failed its integrity check, and, at 100%, the full-resolution size. The folder button reveals the photo in Finder / Explorer.
- Videos aren't previewed; their thumbnail reveals the file instead.

Previews are cached in memory (up to 256 MB) and in the browser for a day; **Clear Cache** under the settings cog empties both.
