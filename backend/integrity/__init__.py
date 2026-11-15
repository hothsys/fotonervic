"""Integrity checks: one module per format family, and the dispatcher every
scan (Scan Directory, Exif Info, Blur Check) uses."""

import os
import threading
import time
from pathlib import Path

from backend.config import WORKER_THREADS
from backend.formats import HEIC_EXTS, JPEG_EXTS, PNG_EXTS, RAW_EXTS, VIDEO_EXTS
from backend.integrity.generic import check_generic_pillow
from backend.integrity.heic import check_heic
from backend.integrity.jpeg import check_jpeg
from backend.integrity.png import check_png
from backend.integrity.raw import check_raw
from backend.integrity.video import check_video

# ─── Dispatcher ───────────────────────────────────────────────────────────────

# ─── RAW checks in worker processes ───────────────────────────────────────────
# A RAW check decodes the sensor data with LibRaw (0.1-2 s per file; ~2 s for
# an iPhone ProRAW DNG) and captures LibRaw's messages by redirecting the
# process's stderr, which only one thread can do at a time. So in threads, RAW
# checks ran one by one; in worker processes, each with its own stderr, they
# run in parallel. LibRaw is C, so a crash on a badly damaged file now only
# kills a worker (replaced on the next file), not the server.
RAW_CHECK_PROCESSES = WORKER_THREADS
_POOL_START_TIMEOUT = 60   # seconds for the worker processes to answer a first ping

_raw_pool = None
_raw_pool_usable = True   # False once worker processes have failed to start
_raw_pool_lock = threading.Lock()


def _pool_ping():
    return os.getpid()


def _exit_with_parent(parent_pid):
    """Worker process start-up: exit as soon as the server that started it is
    gone, however it ended (stop, crash, kill -9), instead of lingering."""
    def watch():
        while os.getppid() == parent_pid:
            time.sleep(2)
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()


def _spawn_pool(workers):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    # spawn: fresh processes (macOS's default; fork is unsafe with threads)
    return ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
                               initializer=_exit_with_parent, initargs=(os.getpid(),))


def _get_raw_pool():
    """The worker process pool, started and checked on first use; None if
    worker processes don't work here (RAW checks then run in this process)."""
    global _raw_pool, _raw_pool_usable
    with _raw_pool_lock:
        if _raw_pool is None and _raw_pool_usable:
            pool = _spawn_pool(RAW_CHECK_PROCESSES)
            try:
                pool.submit(_pool_ping).result(timeout=_POOL_START_TIMEOUT)
                _raw_pool = pool
            except Exception as e:
                pool.shutdown(wait=False, cancel_futures=True)
                _raw_pool_usable = False
                print(f'RAW integrity checks will run one at a time: worker processes failed to start ({e!r}).')
        return _raw_pool


def _discard_raw_pool(pool):
    """Drop a broken pool (unless another thread already replaced it)."""
    global _raw_pool
    with _raw_pool_lock:
        if _raw_pool is pool:
            _raw_pool = None
    pool.shutdown(wait=False, cancel_futures=True)


def _check_raw_isolated(filepath: str):
    from concurrent.futures.process import BrokenProcessPool
    pool = _get_raw_pool()
    if pool is None:
        return check_raw(filepath)
    try:
        return pool.submit(check_raw, filepath).result()
    except BrokenProcessPool:
        # A worker died, which fails every file in progress, not just the one
        # that crashed it. Retry this file on its own: only a crash there
        # means this file crashes the decoder.
        _discard_raw_pool(pool)
        solo = _spawn_pool(1)
        try:
            return solo.submit(check_raw, filepath).result()
        except BrokenProcessPool:
            return 'corrupt', ('The RAW decoder crashed reading this file, which usually means '
                               'its image data is badly damaged')
        finally:
            solo.shutdown(wait=False)


def check_integrity(filepath: str) -> dict:
    """The file integrity check (what Scan Directory reports), as a dict so
    scans can merge it into their results. integrity is 'ok', 'partial',
    'corrupt', 'exif_only', 'empty', 'error', or 'unsupported' (couldn't be
    checked, e.g. HEIC without pillow-heif); integrity_reason explains it.
    It fully decodes the file (including RAW sensor data), so it's the slow
    part of any scan that uses it."""
    status, reason = check_image(filepath)
    return {'integrity': status, 'integrity_reason': reason}


def check_image(filepath: str):
    ext = Path(filepath).suffix.lower()
    if ext in VIDEO_EXTS:
        return check_video(filepath)
    elif ext in JPEG_EXTS:
        return check_jpeg(filepath)
    elif ext in PNG_EXTS:
        return check_png(filepath)
    elif ext in HEIC_EXTS:
        return check_heic(filepath)
    elif ext in RAW_EXTS:
        return _check_raw_isolated(filepath)
    else:
        return check_generic_pillow(filepath)
