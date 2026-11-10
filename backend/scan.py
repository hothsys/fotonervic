"""Scan Directory (integrity scan of a folder tree) and the pre-scan media count."""

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.config import WORKER_THREADS
from backend.formats import RAW_EXTS, SUPPORTED_EXTENSIONS, VIDEO_EXTS
from backend.integrity import check_integrity
from backend.tiff import _has_usable_preview

scan_state = {
    'running': False,
    'cancel': None,
    'results': [],
}


# ─── Directory scanner (generator) ────────────────────────────────────────────


def scan_directory_gen(root_dir: str, cancel: threading.Event):
    root = Path(root_dir).expanduser().resolve()

    if not root.exists():
        yield {'type': 'error', 'message': f'Path not found: {root_dir}'}
        return
    if not root.is_dir():
        yield {'type': 'error', 'message': f'Not a directory: {root_dir}'}
        return

    # Count total files first
    yield {'type': 'status', 'message': 'Counting image files…'}
    all_files = []
    for dp, dirs, files in os.walk(root, followlinks=False):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': 0, 'issues': 0}
            return
        dirs.sort()
        for f in sorted(files):
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                all_files.append((dp, f))

    total = len(all_files)
    yield {'type': 'total', 'total': total}

    scanned = 0
    issues  = 0
    start   = time.time()

    def _check_worker(dp, fname):
        """Run check_image in a worker thread."""
        filepath = os.path.join(dp, fname)
        file_size = 0
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            pass
        result = check_integrity(filepath)
        status, reason = result['integrity'], result['integrity_reason']
        # For damaged RAW files, whether Export Preview has anything to export
        has_preview = None
        if status != 'ok' and Path(fname).suffix.lower() in RAW_EXTS:
            has_preview = _has_usable_preview(filepath)
        return dp, fname, filepath, file_size, status, reason, has_preview

    # Process files in batches using a thread pool
    batch_size = WORKER_THREADS * 4
    for batch_start in range(0, total, batch_size):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': scanned, 'issues': issues}
            return

        batch = all_files[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
            futures = {
                executor.submit(_check_worker, dp, fname): (dp, fname)
                for dp, fname in batch
            }

            for future in as_completed(futures):
                if cancel.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    yield {'type': 'cancelled', 'scanned': scanned, 'issues': issues}
                    return

                dp, fname, filepath, file_size, status, reason, has_preview = future.result()
                scanned += 1

                yield {
                    'type':    'scanning',
                    'file':    fname,
                    'dir':     dp,
                    'scanned': scanned,
                    'total':   total,
                    'issues':  issues,
                }

                if status != 'ok':
                    issues += 1
                    # Extract corruption percentage from reason if present
                    corrupt_pct = None
                    if reason:
                        pct_m = re.search(r'~([\d.]+)% of file corrupted', reason)
                        if pct_m:
                            corrupt_pct = float(pct_m.group(1))
                    event = {
                        'type':      'issue',
                        'filepath':  filepath,
                        'filename':  fname,
                        'dir':       dp,
                        'ext':       Path(fname).suffix.lower(),
                        'file_size': file_size,
                        'status':    status,
                        'reason':    reason,
                        'scanned':   scanned,
                        'issues':    issues,
                    }
                    if corrupt_pct is not None:
                        event['corrupt_pct'] = corrupt_pct
                    if has_preview is not None:
                        event['has_preview'] = has_preview
                    yield event

    elapsed = time.time() - start
    yield {
        'type':    'complete',
        'scanned': scanned,
        'issues':  issues,
        'elapsed': round(elapsed, 1),
    }


# ─── Pre-scan file count ──────────────────────────────────────────────────────
# Counts what a scan would process when a directory is chosen or typed. Only
# lists files and checks extensions (no file is opened), so it's fast on local
# disks; on slow network volumes it streams running totals. A new count cancels
# the previous one (typing changes the path every few keystrokes).

count_state = {'running': False, 'cancel': None, 'results': []}
COUNT_PROGRESS_INTERVAL = 0.25   # seconds between running-total events


def count_media_gen(root_dir: str, cancel: threading.Event):
    root = Path(root_dir).expanduser()
    if not root.exists():
        yield {'type': 'error', 'reason': 'not_found'}
        return
    if not root.is_dir():
        yield {'type': 'error', 'reason': 'not_dir'}
        return

    photos = videos = folders = 0
    start = last = time.time()
    for dp, dirs, files in os.walk(root, followlinks=False):
        if cancel.is_set():
            return
        folders += 1
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in VIDEO_EXTS:
                videos += 1
            elif ext in SUPPORTED_EXTENSIONS:
                photos += 1
        now = time.time()
        if now - last >= COUNT_PROGRESS_INTERVAL:
            last = now
            yield {'type': 'progress', 'photos': photos, 'videos': videos, 'folders': folders}
    yield {'type': 'complete', 'photos': photos, 'videos': videos, 'folders': folders,
           'elapsed': round(time.time() - start, 2)}
