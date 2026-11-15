#!/usr/bin/env python3
"""
Recursively scans directories for corrupt or partial image files.
Detects: truncated files, missing image data, corrupt headers,
and files with EXIF metadata but no recoverable image content.

Entry point: sets up the app's own Python environment, then starts the
server. The application itself lives in backend/.

Zero configuration: on first launch this creates a virtual environment in
.venv/ (so nothing is installed into the system's or Homebrew's Python), installs
requirements.txt into it, and restarts itself inside it. Later launches only
install when requirements.txt has changed (e.g. a Dependabot update).

Packages are installed with uv (https://docs.astral.sh/uv/), itself installed
into .venv by pip on first launch: it downloads in parallel and links packages
from its cache, so a reinstall after a requirements.txt change takes well under
a second. Without uv, plain pip does the same, more slowly. Requirements marked
"# optional" may fail without stopping the app; only their feature turns off.
ExifTool downloads at the same time (backend/exiftool.py).
"""

import hashlib
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(APP_DIR, '.venv')
REQUIREMENTS = os.path.join(APP_DIR, 'requirements.txt')
REQUIREMENTS_STAMP = os.path.join(VENV_DIR, '.requirements.sha256')
_BOOTSTRAP_ENV = 'FOTONERVIC_IN_VENV'   # set before restarting, so a mismatch can't loop

# ─── Python environment ─────────────────────────────────────────────────────

def _venv_bin(name):
    if os.name == 'nt':
        return os.path.join(VENV_DIR, 'Scripts', name + '.exe')
    return os.path.join(VENV_DIR, 'bin', name)


def _venv_python():
    return _venv_bin('python')


def _in_venv():
    return os.path.realpath(sys.prefix) == os.path.realpath(VENV_DIR)


def _parse_requirements():
    """(required, optional) requirement strings from requirements.txt. A line
    is optional when its comment contains "optional"."""
    required, optional = [], []
    with open(REQUIREMENTS) as f:
        for line in f:
            spec, _, comment = line.partition('#')
            spec = spec.strip()
            if spec:
                (optional if 'optional' in comment.lower() else required).append(spec)
    return required, optional


def _pip_install(*specs):
    return subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', *specs]
    ).returncode == 0


def _uv(required, optional):
    """Path of uv in .venv, installing it with pip first if needed (the uv line
    in requirements.txt, so Dependabot keeps it current). None if that fails."""
    uv = _venv_bin('uv')
    if not os.path.exists(uv):
        spec = next((s for s in required + optional if s.split('>')[0].split('=')[0].strip() == 'uv'), 'uv')
        print('Installing uv, the fast package installer, with pip...')
        t = time.time()
        if _pip_install(spec) and os.path.exists(uv):
            print(f'  uv ready ({time.time() - t:.1f} s)')
        else:
            print('  uv could not be installed; using pip instead (slower).')
    return uv if os.path.exists(uv) else None


def _installer(uv):
    """install(*specs) -> bool, with uv when available, else pip."""
    if uv is None:
        return _pip_install
    def install(*specs):
        # --native-tls: use the macOS keychain, as curl does, so TLS-inspecting
        # proxies work (uv otherwise uses its own certificate list)
        return subprocess.run([uv, 'pip', 'install', '--quiet', '--native-tls',
                               '--python', sys.executable, *specs]).returncode == 0
    return install


def _install_requirements():
    with open(REQUIREMENTS, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    try:
        with open(REQUIREMENTS_STAMP) as f:
            if f.read().strip() == digest:
                print('Dependencies up to date.')   # already installed for this requirements.txt
                return
    except OSError:
        pass

    required, optional = _parse_requirements()
    started = time.time()
    first = not os.path.exists(REQUIREMENTS_STAMP)
    print(('Installing' if first else 'requirements.txt changed; updating') + ' dependencies...')
    uv = _uv(required, optional)
    install = _installer(uv)
    names = [spec.split('>')[0].split('=')[0].split('<')[0].strip() for spec in required + optional]
    print(f'Installing {len(names)} packages with {"uv" if uv else "pip"}: {", ".join(names)}')
    # One pass for everything; if something fails, the required ones, then each
    # optional one on its own, so a failure only turns off that feature
    if not install(*required, *optional):
        if required and not install(*required):
            sys.exit('Could not install the required packages (' + ', '.join(required) + '). '
                     'Check your internet connection and run the app again.')
        for spec in optional:
            if not install(spec):
                print(f'  Could not install optional {spec}; the feature that needs it is turned off.')
    with open(REQUIREMENTS_STAMP, 'w') as f:
        f.write(digest)
    print(f'Dependencies ready ({time.time() - started:.1f} s).')


def _bootstrap():
    """Run inside .venv (creating it first if needed), with requirements.txt installed."""
    if not _in_venv() and not os.environ.get(_BOOTSTRAP_ENV):
        python = _venv_python()
        if not os.path.exists(python):
            print('Creating the app\'s Python environment in .venv ...')
            t = time.time()
            import venv
            venv.EnvBuilder(with_pip=True).create(VENV_DIR)
            print(f'  .venv created ({time.time() - t:.1f} s)')
        os.environ[_BOOTSTRAP_ENV] = '1'
        os.execv(python, [python, '-u', os.path.abspath(__file__), *sys.argv[1:]])
    # ExifTool needs nothing from pip, so its download (if due) runs alongside the install
    from backend.exiftool import ensure_exiftool
    ensure_exiftool()
    _install_requirements()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    _bootstrap()

    from http.server import ThreadingHTTPServer

    from backend.config import APP_TITLE
    from backend.server import ScannerHandler

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5900
    print(f'Starting the web server on port {port}...')
    print()
    print('╔══════════════════════════════════════════════╗')
    print(f'║{APP_TITLE.center(46)}║')
    print(f'║  Open http://localhost:{port} in your browser  ║')
    print('╚══════════════════════════════════════════════╝')
    print()
    threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('127.0.0.1', port), ScannerHandler)
    # server.sh stop sends SIGTERM, which by default ends Python without any
    # clean-up; exit normally instead, so worker processes are shut down too
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        print('\nShutting down.')
        server.server_close()
