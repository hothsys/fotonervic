#!/usr/bin/env python3
"""
Recursively scans directories for corrupt or partial image files.
Detects: truncated files, missing image data, corrupt headers,
and files with EXIF metadata but no recoverable image content.

Entry point: installs missing dependencies, then starts the server. The
application itself lives in backend/.
"""

import subprocess
import sys
import threading
import webbrowser

# ─── Auto-install dependencies on first run ─────────────────────────────────

def _ensure_dependencies():
    """Install missing packages from requirements.txt automatically."""
    required = {
        'PIL':         'Pillow>=10.0.0',
        'rawpy':       'rawpy>=0.18.0',
        'pillow_heif': 'pillow-heif>=0.13.0',
        'numpy':       'numpy>=1.24',
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print(f'Installing missing dependencies: {", ".join(missing)}')
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '--quiet'] + missing,
        )
        print('Dependencies installed successfully.')

    # Optional: runs Blur Check's AI quality model. Best effort, because Blur
    # Check falls back to its hand-built measure without it, so a failed
    # install (e.g. no wheel for this Python) mustn't stop the app starting.
    try:
        __import__('onnxruntime')
    except ImportError:
        print('Installing optional dependency: onnxruntime (AI blur scoring)')
        try:
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '--quiet', 'onnxruntime>=1.17'])
        except subprocess.CalledProcessError:
            print('  Could not install onnxruntime; Blur Check will use basic scoring.')

_ensure_dependencies()

from http.server import ThreadingHTTPServer   # noqa: E402 (after the dependency install)

from backend.config import APP_TITLE           # noqa: E402
from backend.server import ScannerHandler      # noqa: E402

# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5900
    print()
    print('╔══════════════════════════════════════════════╗')
    print(f'║{APP_TITLE.center(46)}║')
    print(f'║  Open http://localhost:{port} in your browser  ║')
    print('╚══════════════════════════════════════════════╝')
    print()
    threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('127.0.0.1', port), ScannerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
        server.server_close()
