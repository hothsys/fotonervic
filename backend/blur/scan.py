"""The Blur Check scan of a folder tree."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.blur.score import measure_blur
from backend.config import WORKER_THREADS
from backend.formats import SUPPORTED_EXTENSIONS, VIDEO_EXTS
from backend.integrity import check_integrity

BLUR_IMAGE_EXTS = SUPPORTED_EXTENSIONS - VIDEO_EXTS


blur_state = {'running': False, 'cancel': None, 'results': []}


def blur_scan_gen(root_dir: str, cancel: threading.Event):
    root = Path(root_dir).expanduser().resolve()

    if not root.exists():
        yield {'type': 'error', 'message': f'Path not found: {root_dir}'}
        return
    if not root.is_dir():
        yield {'type': 'error', 'message': f'Not a directory: {root_dir}'}
        return

    yield {'type': 'status', 'message': 'Counting photos…'}
    all_files = []
    for dp, dirs, files in os.walk(root, followlinks=False):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': 0}
            return
        dirs.sort()
        for f in sorted(files):
            if Path(f).suffix.lower() in BLUR_IMAGE_EXTS:
                all_files.append((dp, f))

    total = len(all_files)
    yield {'type': 'total', 'total': total}

    scanned = 0
    start   = time.time()

    def _blur_worker(dp, fname):
        filepath = os.path.join(dp, fname)
        file_size = 0
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            pass
        # Integrity check too: a damaged file can still score as sharp, e.g. a
        # RAW whose embedded preview survived while its sensor data didn't
        blur = measure_blur(filepath)
        blur.update(check_integrity(filepath))
        return dp, fname, filepath, file_size, blur

    batch_size = WORKER_THREADS * 4
    for batch_start in range(0, total, batch_size):
        if cancel.is_set():
            yield {'type': 'cancelled', 'scanned': scanned}
            return

        batch = all_files[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
            futures = {
                executor.submit(_blur_worker, dp, fname): (dp, fname)
                for dp, fname in batch
            }

            for future in as_completed(futures):
                if cancel.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    yield {'type': 'cancelled', 'scanned': scanned}
                    return

                dp, fname, filepath, file_size, blur = future.result()
                scanned += 1

                yield {
                    'type':    'scanning',
                    'file':    fname,
                    'dir':     dp,
                    'scanned': scanned,
                    'total':   total,
                }
                yield {
                    'type':      'blur_result',
                    'filepath':  filepath,
                    'filename':  fname,
                    'dir':       dp,
                    'ext':       Path(fname).suffix.lower(),
                    'file_size': file_size,
                    **blur,
                }

    elapsed = time.time() - start
    yield {'type': 'complete', 'scanned': scanned, 'elapsed': round(elapsed, 1)}
