"""ExifTool (https://exiftool.org) for Exif Info metadata: finding it, running
it, and downloading the app's own copy.

ExifTool reads the metadata of practically every camera's files, including
each maker's private maker notes (lens names, for example), and its author
adds new cameras every few weeks, so Exif Info delegates to it rather than
parsing formats itself.

The app keeps its own copy in the user's cache folder (EXIFTOOL_DIR, outside
the project), run with the system's Perl, so every Mac uses the same version
with no Homebrew or PATH setup. At launch, ensure_exiftool() downloads the
latest release in the background when that copy is missing or older than
EXIFTOOL_MIN_VERSION (app.conf). An exiftool installed some other way (e.g.
Homebrew) is used only until the app's copy is in place. Without any,
backend/exif.py falls back to a basic built-in reader.

One ExifTool process is kept open for all files (PyExifTool's stay-open
mode), so Perl starts once per server run, not once per file.
"""

import atexit
import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time

from backend.config import APP_NAME, _APP_CONFIG


def _cache_dir():
    """The user's cache folder for this app (outside the project, so moving or
    re-cloning the project doesn't mean downloading again)."""
    if os.uname().sysname == 'Darwin':
        base = os.path.expanduser('~/Library/Caches')
    else:
        base = os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache')
    return os.path.join(base, APP_NAME)


EXIFTOOL_DIR = os.path.join(_cache_dir(), 'exiftool')
EXIFTOOL_MIN_VERSION = _APP_CONFIG.get('EXIFTOOL_MIN_VERSION', '')
EXIFTOOL_SCRIPT = os.path.join(EXIFTOOL_DIR, 'exiftool')
EXIFTOOL_VERSION_URL = 'https://exiftool.org/ver.txt'
EXIFTOOL_CHECKSUMS_URL = 'https://exiftool.org/checksums.txt'
# exiftool.org hosts the releases on SourceForge; the checksum comes from exiftool.org
EXIFTOOL_ARCHIVE_URL = 'https://sourceforge.net/projects/exiftool/files/Image-ExifTool-{version}.tar.gz/download'
EXIFTOOL_LATEST_CHECK_SECS = 24 * 3600

# Tags Exif Info shows. A '#' suffix asks for the plain number instead of
# ExifTool's text (e.g. 0.005 rather than "1/200"); LensID is ExifTool's best
# lens name, decoded from maker notes when the file has no LensModel text.
EXIFTOOL_TAGS = [
    'Make', 'Model', 'LensID', 'LensModel',
    # Capture time, best first. CreationDate (Apple's QuickTime Keys) is the local
    # time where an iPhone video was filmed, with its time zone; CreateDate is
    # rewritten when Photos exports a slow-motion clip, and is UTC on iPhones
    'DateTimeOriginal', 'CreationDate', 'CreateDate', 'ModifyDate',
    'ISO', 'FNumber#', 'ExposureTime#', 'FocalLength#', 'Flash#',
    'Composite:GPSLatitude#', 'Composite:GPSLongitude#',   # signed (the EXIF tags aren't)
    'ImageWidth', 'ImageHeight', 'Rotation#',               # used for videos only
    'XMPToolkit', 'CreatorTool', 'Software',                # which editor wrote the file
]
# -fast: don't scan to the end of large files for trailers. QuickTime times are
# read as stored (no QuickTimeUTC): most cameras write their clock's local time
# there, as in their photos (a Canon G15 clip would shift by this Mac's time zone
# otherwise), and iPhone videos are dated by CreationDate instead.
EXIFTOOL_ARGS = ['-fast']

# Finder-launched apps don't get the shell's PATH, so also look where
# Homebrew and the official macOS installer put exiftool
_EXTRA_PATHS = ['/opt/homebrew/bin', '/usr/local/bin']

_helper = None            # exiftool.ExifToolHelper
_helper_path = None
_helper_lock = threading.Lock()   # one stay-open process: one request at a time
_download = {'state': 'idle', 'error': None, 'detail': None}
_latest = {'version': None, 'checked': 0.0, 'checking': False}
_version_cache = {}       # (path, mtime) -> version string


def find_exiftool():
    """(path, source): source is 'app' for the app's own copy, 'system' for an
    exiftool installed some other way (used only until the app's copy is in
    place), or (None, None)."""
    if os.path.isfile(EXIFTOOL_SCRIPT) and shutil.which('perl'):
        return EXIFTOOL_SCRIPT, 'app'
    path = shutil.which('exiftool') or shutil.which(
        'exiftool', path=os.pathsep.join(_EXTRA_PATHS))
    if path:
        return path, 'system'
    return None, None


def _wrapper_installed():
    try:
        import exiftool  # noqa: F401
        return True
    except ImportError:
        return False


def _get_helper():
    """The running ExifToolHelper for the current exiftool, or None. Caller holds _helper_lock."""
    global _helper, _helper_path
    path, _ = find_exiftool()
    if path is None:
        return None
    if _helper is not None and _helper_path == path and _helper.running:
        return _helper
    _stop_helper()
    import exiftool
    helper = exiftool.ExifToolHelper(executable=path, common_args=EXIFTOOL_ARGS, check_execute=False)
    helper.run()
    _helper, _helper_path = helper, path
    return helper


def _stop_helper():
    global _helper, _helper_path
    if _helper is not None:
        try:
            _helper.terminate()
        except Exception:
            pass
    _helper, _helper_path = None, None


atexit.register(_stop_helper)


def read_metadata(filepath: str):
    """ExifTool's tags for one file (a dict, empty when it found nothing), or
    None when ExifTool isn't available, so the caller can use its own reader."""
    with _helper_lock:
        try:
            helper = _get_helper()
            if helper is None:
                return None
            if _download['state'] == 'done':   # "installed, run Exif Info again" has been acted on
                _download['state'] = 'idle'
            found = helper.get_tags([filepath], EXIFTOOL_TAGS)
            return found[0] if found else {}
        except ImportError:
            return None
        except Exception:
            _stop_helper()   # restart on the next file
            return None


def _parse_version(text):
    m = re.fullmatch(r'\s*(\d+)\.(\d+)\s*', text or '')
    return (int(m.group(1)), int(m.group(2))) if m else None


def _installed_version(path):
    if not path:
        return None
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _version_cache:
        try:
            out = subprocess.run([path, '-ver'], capture_output=True, text=True, timeout=20).stdout
            _version_cache[key] = out.strip() if _parse_version(out) else None
        except Exception:
            _version_cache[key] = None
    return _version_cache[key]


def _curl(url, out_path=None, timeout=60):
    """Fetch url with curl (system trust store: works behind TLS-inspecting
    proxies). Returns the text, or writes to out_path. Raises _DownloadError."""
    cmd = ['curl', '-fsSL', '--retry', '2', '--connect-timeout', '20', '--max-time', str(timeout)]
    cmd += ['-o', out_path, url] if out_path else [url]
    proc = subprocess.run(cmd, capture_output=True, text=not out_path)
    if proc.returncode != 0:
        stderr = proc.stderr if isinstance(proc.stderr, str) else proc.stderr.decode('utf-8', 'replace')
        host = re.sub(r'^https?://([^/]+).*$', r'\1', url)
        raise _DownloadError(f"Couldn't download from {host}. Check your internet connection, "
                             'or whether a firewall or proxy blocks it.',
                             stderr.strip() or f'curl exited with {proc.returncode}')
    return None if out_path else proc.stdout


class _DownloadError(Exception):
    """message: plain explanation for the user; detail: the technical cause."""

    def __init__(self, message, detail):
        super().__init__(message)
        self.message, self.detail = message, detail


def _check_latest():
    try:
        version = _curl(EXIFTOOL_VERSION_URL, timeout=20).strip()
        if _parse_version(version):
            _latest['version'] = version
    except Exception:
        pass
    finally:
        _latest['checked'] = time.time()
        _latest['checking'] = False


def _latest_version():
    """The newest release announced on exiftool.org, checked in the background
    at most once a day; None until the first check finishes."""
    if not _latest['checking'] and time.time() - _latest['checked'] > EXIFTOOL_LATEST_CHECK_SECS:
        _latest['checking'] = True
        threading.Thread(target=_check_latest, daemon=True).start()
    return _latest['version']


def exiftool_status() -> dict:
    path, source = find_exiftool()
    version = _installed_version(path)
    latest = _latest_version() if path else None   # nothing to update otherwise
    newer = bool(version and latest and _parse_version(latest) > _parse_version(version))
    if source == 'app' and _download['state'] == 'error':
        _download.update(state='idle', error=None, detail=None)   # the app's copy arrived since
    return {
        'available': bool(path) and _wrapper_installed(),
        'source': source,                  # 'system' | 'app' | None
        'version': version,
        'latest': latest,
        'update_available': newer and source == 'app',   # a Homebrew copy is updated by Homebrew
        'can_download': bool(shutil.which('perl')) and bool(shutil.which('curl')),
        'wrapper_installed': _wrapper_installed(),
        'download': dict(_download),
    }


def _download_exiftool():
    """Download the latest Image-ExifTool release, verify its SHA-256 against
    exiftool.org's published checksums, and install it in EXIFTOOL_DIR."""
    parent = os.path.dirname(EXIFTOOL_DIR)
    archive = os.path.join(parent, '.exiftool-download.tar.gz')
    staging = os.path.join(parent, '.exiftool-new')
    old = os.path.join(parent, '.exiftool-old')
    started = time.time()
    try:
        os.makedirs(parent, exist_ok=True)
        version = _curl(EXIFTOOL_VERSION_URL, timeout=20).strip()
        if not _parse_version(version):
            raise _DownloadError("exiftool.org didn't report a version number.", f'ver.txt: {version[:80]!r}')
        minimum = _parse_version(EXIFTOOL_MIN_VERSION)
        if minimum and _parse_version(version) < minimum:
            raise _DownloadError(f'app.conf asks for ExifTool {EXIFTOOL_MIN_VERSION} or newer, but the latest '
                                 f'release on exiftool.org is {version}. Check EXIFTOOL_MIN_VERSION.',
                                 f'EXIFTOOL_MIN_VERSION={EXIFTOOL_MIN_VERSION}, ver.txt={version}')
        name = f'Image-ExifTool-{version}.tar.gz'
        m = re.search(r'SHA2-256\(' + re.escape(name) + r'\)=\s*([0-9a-f]{64})',
                      _curl(EXIFTOOL_CHECKSUMS_URL, timeout=20))
        if not m:
            raise _DownloadError("exiftool.org doesn't list a checksum for the latest release yet. Try again later.",
                                 f'{name} not in checksums.txt')
        _curl(EXIFTOOL_ARCHIVE_URL.format(version=version), out_path=archive, timeout=300)

        _download['state'] = 'verifying'
        digest = hashlib.sha256()
        with open(archive, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                digest.update(chunk)
        if digest.hexdigest() != m.group(1):
            raise _DownloadError("The downloaded ExifTool doesn't match the checksum exiftool.org "
                                 'publishes, so it was discarded.',
                                 f'SHA-256 {digest.hexdigest()}, expected {m.group(1)}')

        shutil.rmtree(staging, ignore_errors=True)
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(staging, filter='data')   # 'data': no absolute paths, links, or ../
            except TypeError:   # Python without extraction filters: check the paths ourselves
                for member in tar.getmembers():
                    parts = member.name.split('/')
                    if member.issym() or member.islnk() or os.path.isabs(member.name) or '..' in parts:
                        raise _DownloadError("The ExifTool download contained unexpected paths, so it was discarded.",
                                             f'unsafe member: {member.name}')
                tar.extractall(staging)
        unpacked = os.path.join(staging, f'Image-ExifTool-{version}')
        if not os.path.isfile(os.path.join(unpacked, 'exiftool')):
            raise _DownloadError("The ExifTool download didn't contain the exiftool program.", f'missing {unpacked}/exiftool')
        os.chmod(os.path.join(unpacked, 'exiftool'), 0o755)

        with _helper_lock:            # swap in the new copy between files
            _stop_helper()
            shutil.rmtree(old, ignore_errors=True)
            if os.path.exists(EXIFTOOL_DIR):
                os.replace(EXIFTOOL_DIR, old)
            os.replace(unpacked, EXIFTOOL_DIR)
        shutil.rmtree(old, ignore_errors=True)
        _latest.update(version=version, checked=time.time())
        _download.update(state='done', error=None, detail=None)
        print(f'ExifTool {version} installed ({time.time() - started:.1f} s).')
    except _DownloadError as e:
        _download.update(state='error', error=e.message, detail=e.detail)
    except OSError as e:
        _download.update(state='error', detail=str(e),
                         error=f"ExifTool couldn't be saved. Check that this folder is writable: {parent}")
    except Exception as e:
        _download.update(state='error', error='The ExifTool download failed unexpectedly.', detail=str(e))
    finally:
        if _download['state'] == 'error':
            print(f'ExifTool download failed: {_download["error"]} ({_download["detail"]})')
        try:
            os.remove(archive)
        except OSError:
            pass
        shutil.rmtree(staging, ignore_errors=True)


EXIFTOOL_RETRY_DELAYS = (10, 30)   # seconds before each retry of the launch-time download


def _download_with_retries(delays):
    """Download, retrying after each delay in delays while it keeps failing
    (e.g. a network that isn't up yet right after login)."""
    for attempt, delay in enumerate((*delays, None), start=1):
        _download_exiftool()
        if _download['state'] != 'error' or delay is None:
            return
        print(f'  Retrying the ExifTool download in {delay} s (attempt {attempt + 1} of {len(delays) + 1})...')
        _download.update(state='downloading')   # keep the panel showing "Downloading" meanwhile
        time.sleep(delay)


def start_exiftool_download(retry=False):
    """Download (or update to) the latest ExifTool in the background. retry:
    try again a couple of times if it fails (used at launch; a click on
    Download/Update/Try again makes one attempt)."""
    if _download['state'] in ('downloading', 'verifying'):
        return
    _download.update(state='downloading', error=None, detail=None)
    threading.Thread(target=_download_with_retries, args=(EXIFTOOL_RETRY_DELAYS if retry else (),),
                     daemon=True).start()


def _app_copy_current():
    """True when the app's own copy exists and meets EXIFTOOL_MIN_VERSION."""
    if not (os.path.isfile(EXIFTOOL_SCRIPT) and shutil.which('perl')):
        return False
    version = _parse_version(_installed_version(EXIFTOOL_SCRIPT))
    minimum = _parse_version(EXIFTOOL_MIN_VERSION)
    return version is not None and (minimum is None or version >= minimum)


def ensure_exiftool():
    """At launch: download the latest ExifTool in the background when the app's
    copy is missing or older than EXIFTOOL_MIN_VERSION. Exif Info uses any other
    exiftool, or the built-in reader, until it's in place."""
    if _app_copy_current():
        print(f'ExifTool {_installed_version(EXIFTOOL_SCRIPT)} ready.')
        return
    have = _installed_version(EXIFTOOL_SCRIPT) if os.path.isfile(EXIFTOOL_SCRIPT) else None
    if not (shutil.which('perl') and shutil.which('curl')):
        print('ExifTool unavailable: downloading it needs Perl and curl. Exif Info will use its basic reader.')
        return
    why = f'{have} is older than {EXIFTOOL_MIN_VERSION}' if have else 'not installed yet'
    print(f'ExifTool {why}: downloading the latest release in the background...')
    start_exiftool_download(retry=True)
