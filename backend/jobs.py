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
