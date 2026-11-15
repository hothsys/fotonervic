"""Per-scan job bookkeeping: each scan type has a state dict, and starting
a scan cancels the previous one of that type."""

import threading

# Each scan gets its own cancel Event so that cancelling (or starting a new
# scan) only affects that scan; a shared boolean would be reset by the next
# scan before the old one noticed it.


_job_lock = threading.Lock()

def _start_job(state):
    """Cancel any job still running for this state and register a new one."""
    with _job_lock:
        if state['cancel'] is not None:
            state['cancel'].set()
        cancel = threading.Event()
        state['cancel']  = cancel
        state['results'] = []
        state['running'] = True
    return cancel

def _finish_job(state, cancel):
    with _job_lock:
        if state['cancel'] is cancel:
            state['running'] = False

def _cancel_job(state):
    with _job_lock:
        if state['cancel'] is not None:
            state['cancel'].set()


def run_in_threads(fn, items, cancel, workers=None):
    """Yield fn(*item) for each item as it finishes, using a pool of worker
    threads that's kept busy: up to two items per thread are in flight, and a
    new one starts as soon as any finishes (no waiting for a whole batch's
    slowest file). Stops starting new items once cancel is set; leaving the
    loop early cancels whatever hasn't started."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from backend.config import WORKER_THREADS
    workers = workers or WORKER_THREADS
    executor = ThreadPoolExecutor(max_workers=workers)
    pending = set()
    remaining = iter(items)

    def top_up():
        while len(pending) < workers * 2 and not cancel.is_set():
            item = next(remaining, None)
            if item is None:
                return
            pending.add(executor.submit(fn, *item))

    try:
        top_up()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pending.discard(future)
                yield future.result()
            top_up()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
