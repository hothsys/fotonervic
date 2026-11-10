"""App configuration: paths, app.conf settings, and the scan worker count."""

import os

# The project root (this file is backend/config.py): index.html, app.conf, models/
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_app_config():
    """Read KEY="value" lines from app.conf, which the shell scripts also source."""
    cfg = {}
    try:
        with open(os.path.join(APP_DIR, 'app.conf')) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                cfg[key.strip()] = val.strip().strip('"\'')
    except OSError:
        pass
    return cfg


_APP_CONFIG = _read_app_config()
APP_NAME  = _APP_CONFIG.get('APP_NAME') or os.path.basename(APP_DIR)
APP_TITLE = _APP_CONFIG.get('APP_TITLE') or APP_NAME

# Parallel file checks per scan
WORKER_THREADS = 4
