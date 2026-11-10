"""Optional AI quality model (CLIP-IQA+ via onnxruntime): loading, status,
and in-app download."""

import hashlib
import os
import re
import subprocess
import threading

from backend.blur.calibration import QUALITY_INPUT_SIZE
from backend.config import APP_DIR, WORKER_THREADS, _APP_CONFIG

QUALITY_MODEL_PATH  = os.path.join(APP_DIR, 'models', 'clipiqa_plus_rn50.onnx')
QUALITY_MODEL_URL   = _APP_CONFIG.get('QUALITY_MODEL_URL', '')
QUALITY_MODEL_SHA256 = '96693a1f8d1d1c00c64e8be95420f6772238e73dea0df009951ab6aaf1f9dc9d'
QUALITY_MODEL_BYTES  = 152809361


# ── AI quality model (optional) ──

_quality_session = None
_quality_lock = threading.Lock()
_quality_download = {'state': 'idle', 'error': None, 'detail': None}


def _quality_model():
    """Shared onnxruntime session, or None if onnxruntime or the model file is
    missing. Sessions are thread-safe, so the scan's worker threads share one."""
    global _quality_session
    if _quality_session is not None:
        return _quality_session
    with _quality_lock:
        if _quality_session is None and os.path.exists(QUALITY_MODEL_PATH):
            try:
                import onnxruntime as ort
            except ImportError:
                return None
            opts = ort.SessionOptions()
            # The scan already runs WORKER_THREADS photos in parallel
            opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // WORKER_THREADS)
            opts.inter_op_num_threads = 1
            _quality_session = ort.InferenceSession(
                QUALITY_MODEL_PATH, opts, providers=['CPUExecutionProvider'])
    return _quality_session


def quality_model_status() -> dict:
    try:
        import onnxruntime  # noqa: F401
        runtime = True
    except ImportError:
        runtime = False
    present = os.path.exists(QUALITY_MODEL_PATH)
    if present and _quality_download['state'] == 'error':
        # Installed by hand after a failed download: the old error no longer applies
        _quality_download.update(state='idle', error=None, detail=None)
    return {
        'available': runtime and present,
        'runtime_installed': runtime,
        'model_present': present,
        'model_bytes': QUALITY_MODEL_BYTES,
        'download_url': QUALITY_MODEL_URL,
        'download': {**_quality_download, 'received': _download_received()},
    }


def _download_received():
    try:
        return os.path.getsize(QUALITY_MODEL_PATH + '.part')
    except OSError:
        return QUALITY_MODEL_BYTES if _quality_download['state'] in ('verifying', 'done') else 0


class _DownloadError(Exception):
    """message: plain explanation for the user; detail: the technical cause."""

    def __init__(self, message, detail):
        super().__init__(message)
        self.message, self.detail = message, detail


_SAVE_FAILED = ("The model couldn't be saved. Check that the disk has 150 MB free and that "
                f'this folder is writable: {os.path.dirname(QUALITY_MODEL_PATH)}')


def _curl_failure_message(code, http_status):
    """Explain a failed curl download (exit code, final HTTP status) in plain terms."""
    if http_status[:1] in ('4', '5'):     # the server (or a proxy) answered with an error
        if http_status == '404':
            return ("The model wasn't found at the download address (HTTP 404). The "
                    'quality-model-v1 release may have been removed or renamed, or '
                    'QUALITY_MODEL_URL in app.conf may be wrong.')
        if http_status in ('401', '403'):
            return (f'GitHub refused the download (HTTP {http_status}). The repository or '
                    'release may be private.')
        return f'GitHub returned an error (HTTP {http_status}). Try again later.'
    if code == 6:
        return "Couldn't reach GitHub (the address didn't resolve). Check your internet connection."
    if code in (7, 28):
        return ("Couldn't connect to GitHub, or the connection timed out. Check your internet "
                'connection, or whether a firewall or proxy blocks GitHub.')
    if code == 5:
        return "Couldn't reach the network proxy. Check your proxy settings."
    if code in (35, 51, 58, 59, 60, 77, 83, 90, 91):
        return ("A secure connection to GitHub couldn't be established. A network proxy or "
                'firewall may be intercepting it.')
    if code in (18, 52, 55, 56, 92):
        return 'The connection dropped during the download. Try again.'
    if code == 23:
        return _SAVE_FAILED
    return 'The download failed. Try again.'


def _download_quality_model():
    """Fetch the model from QUALITY_MODEL_URL with curl (which uses the system
    trust store, so it works behind TLS-inspecting proxies), verify its
    SHA-256, then move it into place."""
    global _quality_session
    part = QUALITY_MODEL_PATH + '.part'
    try:
        os.makedirs(os.path.dirname(QUALITY_MODEL_PATH), exist_ok=True)
        proc = subprocess.run(
            ['curl', '-fsSL', '--retry', '3', '--connect-timeout', '20',
             # give up on a stalled transfer (under 1 KB/s for a minute)
             '--speed-limit', '1024', '--speed-time', '60',
             '-w', '%{http_code}', '-o', part, QUALITY_MODEL_URL],
            capture_output=True, text=True)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            # The HTTP status, when the server answered: from -w, or from curl's
            # message (behind some proxies an HTTP error arrives as another exit code)
            status = proc.stdout.strip()
            m = re.search(r'returned error: (\d{3})', stderr)
            if m:
                status = m.group(1)
            raise _DownloadError(_curl_failure_message(proc.returncode, status),
                                 stderr or f'curl exited with {proc.returncode}')
        _quality_download['state'] = 'verifying'
        digest = hashlib.sha256()
        with open(part, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                digest.update(chunk)
        if digest.hexdigest() != QUALITY_MODEL_SHA256:
            raise _DownloadError(
                "The downloaded file isn't the expected model (its checksum doesn't match). "
                'The release may hold a different or damaged file.',
                f'SHA-256 {digest.hexdigest()}, expected {QUALITY_MODEL_SHA256}')
        os.replace(part, QUALITY_MODEL_PATH)
        with _quality_lock:
            _quality_session = None
        _quality_download.update(state='done', error=None, detail=None)
    except Exception as e:
        if isinstance(e, _DownloadError):
            _quality_download.update(state='error', error=e.message, detail=e.detail)
        elif isinstance(e, OSError):     # creating models/, reading or moving the file
            _quality_download.update(state='error', error=_SAVE_FAILED, detail=str(e))
        else:
            _quality_download.update(state='error', error='The download failed unexpectedly.', detail=str(e))
        try:
            os.remove(part)
        except OSError:
            pass


def start_quality_model_download():
    if _quality_download['state'] in ('downloading', 'verifying'):
        return
    if not QUALITY_MODEL_URL:
        _quality_download.update(state='error', error='No QUALITY_MODEL_URL set in app.conf.', detail=None)
        return
    _quality_download.update(state='downloading', error=None, detail=None)
    threading.Thread(target=_download_quality_model, daemon=True).start()


def _quality_score(rgb):
    """AI quality, 0..1 (probability the photo is 'good'), or None."""
    sess = _quality_model()
    if sess is None:
        return None
    import numpy as np
    img = rgb.copy()
    img.thumbnail((QUALITY_INPUT_SIZE, QUALITY_INPUT_SIZE))
    x = (np.asarray(img, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    return float(sess.run(None, {'image': x})[0][0, 0])
