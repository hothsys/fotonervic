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
        if state["cancel"] is not None:
            state["cancel"].set()
        cancel = threading.Event()
        state["cancel"] = cancel
        state["results"] = []
        state["running"] = True
    return cancel


def _finish_job(state, cancel):
    with _job_lock:
        if state["cancel"] is cancel:
            state["running"] = False


def _cancel_job(state):
    with _job_lock:
        if state["cancel"] is not None:
            state["cancel"].set()


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


def log_scan(name, result_type, tally=None):
    """Decorator for a scan generator (root_dir, cancel): logs its start, a
    DEBUG line per file, and a summary at the end (files, damaged files by
    status, the optional tally(event) -> label counts, and duration), from the
    events the scan already yields."""
    import functools
    import logging
    import time
    from collections import Counter

    def wrap(scan_gen):
        log = logging.getLogger(scan_gen.__module__)

        @functools.wraps(scan_gen)
        def run(root_dir, cancel):
            started = time.time()
            damaged, tallied = Counter(), Counter()
            log.info(f"{name} started: {root_dir}")
            try:
                for event in scan_gen(root_dir, cancel):
                    kind = event.get("type")
                    if kind == "total":
                        log.info(f"{name}: {event['total']:,} files to check")
                    elif kind == result_type:
                        status = event.get("status") or event.get("integrity") or "ok"
                        if status not in ("ok", "unsupported"):
                            damaged[status] += 1
                        label = tally(event) if tally else None
                        if label:
                            tallied[label] += 1
                        log.debug(
                            f"{name}: {event.get('filepath')}: {status}"
                            + (f", {label}" if label else "")
                        )
                    elif kind == "complete":
                        parts = [
                            f"{event.get('scanned', 0):,} files in {time.time() - started:.1f} s"
                        ]
                        parts.append(
                            "damaged: " + ", ".join(f"{n} {s}" for s, n in damaged.most_common())
                            if damaged
                            else "no damaged files"
                        )
                        parts += [f"{n:,} {label}" for label, n in tallied.most_common()]
                        log.info(f"{name} finished: " + "; ".join(parts))
                    elif kind == "cancelled":
                        log.info(f"{name} cancelled after {event.get('scanned', 0):,} files")
                    elif kind == "error":
                        log.warning(f"{name}: {event.get('message') or event.get('reason')}")
                    yield event
            except GeneratorExit:  # the browser went away mid-scan
                log.info(f"{name} stopped: the page closed the connection")
                raise
            except Exception:
                log.exception(f"{name} failed")
                raise

        return run

    return wrap
