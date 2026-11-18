"""Logging for the whole app: setup_logging() once, first thing in app.py, then
each module logs through logging.getLogger(__name__).

Two destinations:
  * a persistent, rotating log file in the OS's standard place
    (~/Library/Logs/<APP_NAME>/app.log on macOS, also shown by Console.app;
    ~/.local/state/<APP_NAME>/app.log elsewhere), with a timestamp, level, and
    source on every line. `./server.sh logs` follows it.
  * the console (stdout) as plain lines, warnings and errors labelled, which
    server.sh shows while the server starts and keeps in .server.log.

The level comes from LOG_LEVEL in app.conf (default INFO). DEBUG adds per-file
scan results and HTTP requests, to the file only.
Standard library only: app.py sets this up before any packages are installed.
"""

import logging
import logging.handlers
import os
import platform
import sys
import threading

from backend.config import APP_NAME, _APP_CONFIG

LOG_FILE_MAX_BYTES = 5 * 1024 * 1024  # rotate at 5 MB...
LOG_FILE_BACKUPS = 3  # ...keeping app.log.1 to app.log.3 (20 MB at most)


def log_dir():
    if platform.system() == "Darwin":
        return os.path.expanduser(f"~/Library/Logs/{APP_NAME}")
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, APP_NAME)


LOG_FILE = os.path.join(log_dir(), "app.log")


class _ConsoleFormatter(logging.Formatter):
    """Plain message; warnings and errors get their level in front."""

    def format(self, record):
        message = record.getMessage()
        if record.levelno >= logging.WARNING:
            message = f"{record.levelname}: {message}"
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        return message


def setup_logging():
    """Configure the root logger (once per process). Returns the log file path,
    or None if it couldn't be created (console logging still works)."""
    root = logging.getLogger()
    if getattr(root, "_app_configured", False):
        return LOG_FILE if any(isinstance(h, logging.FileHandler) for h in root.handlers) else None
    level = getattr(logging, str(_APP_CONFIG.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(max(level, logging.INFO))  # DEBUG detail goes to the file only
    console.setFormatter(_ConsoleFormatter())
    root.addHandler(console)

    log_file = None
    try:
        os.makedirs(log_dir(), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_FILE_MAX_BYTES, backupCount=LOG_FILE_BACKUPS, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        root.addHandler(file_handler)
        log_file = LOG_FILE
    except OSError as e:
        logging.getLogger(__name__).warning(
            f"Logging to the console only: cannot write {LOG_FILE} ({e})"
        )

    # Libraries' own debug chatter (e.g. Pillow's plugin loading) isn't useful here
    for noisy in ("PIL", "urllib3", "exiftool"):
        logging.getLogger(noisy).setLevel(max(level, logging.INFO))

    # Errors nothing else caught: log them with their traceback instead of losing them
    def log_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger("app").critical("Unhandled error", exc_info=(exc_type, exc, tb))

    sys.excepthook = log_uncaught
    threading.excepthook = lambda args: logging.getLogger("app").error(
        f"Unhandled error in thread {args.thread.name if args.thread else '?'}",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )

    root._app_configured = True
    return log_file
