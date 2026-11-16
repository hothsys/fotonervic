# Logging

Foto Nerve Shatter logs through Python's standard `logging` module, set up once in `backend/log.py` (first thing in `app.py`, so even setting up the Python environment is logged). Every module logs through its own logger (`logging.getLogger(__name__)`), so each line says which part of the app wrote it.

## Where it goes

| Destination | What it has |
|---|---|
| **`~/Library/Logs/FotoNerveShatter/app.log`** (macOS; `~/.local/state/FotoNerveShatter/app.log` elsewhere) | The persistent log: every run, with a timestamp, level, and source on each line. Rotates at 5 MB, keeping three old files (`app.log.1` to `app.log.3`, 20 MB at most). Console.app shows it too (under Log Reports). |
| **The console** | Plain lines (warnings and errors labelled `WARNING:` / `ERROR:`). `server.sh` (and both macOS launchers, which use it) shows them while the server starts and keeps them in `.server.log` in the project folder, overwritten each start. With `python app.py` (e.g. on Windows) they appear in that terminal. |

`.server.log` also catches what libraries print directly rather than through `logging`, e.g. LibRaw's `data corrupted at ...` lines when a thumbnail or Blur Check decodes a damaged RAW file.

## Levels

Set with `LOG_LEVEL` in `app.conf` (default `INFO`):

| Level | Logged |
|---|---|
| `INFO` | Setup with timings (creating `.venv`, installing uv and packages, or "Dependencies up to date."), ExifTool ready / downloading / installed, the server's port, Python version, PID, and log file; each scan's start (folder, file count) and summary (files, damaged files by status, a scan-specific tally such as how metadata was read or how many photos are blurry, duration); cancellations; RAW worker processes starting; recovered files sent (Export Preview, Repair, Salvage, CSV exports); cache cleared; a watched volume appearing or going; downloads (ExifTool, the AI model); shutdown. |
| `WARNING` | Fallbacks and failures that don't stop the app: an optional package or uv that didn't install (with the installer's output), ExifTool unavailable or a failed download (with each retry), a RAW worker crashing (and the file retried alone), every error response the server sends (method, path, status, reason). |
| `ERROR` | Unexpected errors, with their full traceback: anything a request handler, a scan, or a background thread didn't catch. |
| `DEBUG` | Everything above plus one line per file scanned (status, metadata source or blur result) and every HTTP request. Written to the file only; the console stays at INFO. |

Example (`INFO`):

```
2026-11-15 15:24:44 INFO    app: Serving Foto Nerve Shatter on port 5900 (Python 3.13.0, PID 6790, log file ~/Library/Logs/FotoNerveShatter/app.log)...
2026-11-15 15:24:45 INFO    backend.scan: Scan Directory started: /Volumes/Card/DCIM
2026-11-15 15:24:45 INFO    backend.scan: Scan Directory: 491 files to check
2026-11-15 15:24:45 INFO    backend.integrity: RAW integrity checks: 4 worker processes started
2026-11-15 15:25:45 INFO    backend.scan: Scan Directory finished: 491 files in 60.1 s; damaged: 3 partial, 1 corrupt
2026-11-15 15:25:50 WARNING backend.server: GET /api/integrity -> 404: File not found
```

## What `server.sh` shows

`./server.sh start` (and `restart`) shows the console output as the server starts, indented under its own messages, so you can see setup progress instead of a silent wait:

```
Starting Foto Nerve Shatter on port 5900 (log: .server.log)...
  ExifTool 13.63 ready.
  Dependencies up to date.
  Serving Foto Nerve Shatter on port 5900 (Python 3.13.0, PID 6714, log file ...)...
Foto Nerve Shatter started in 1 s (PID 6714) at http://localhost:5900
```

During a long quiet step it prints `...still starting (N s)` every 5 seconds. If ExifTool is still downloading when the server is up, it says so. If the server fails to start, it shows the rest of the console output, which says why.

## Reading the log

```bash
./server.sh logs                                          # follow app.log live (last 50 lines first)
grep -E 'WARNING|ERROR' ~/Library/Logs/FotoNerveShatter/app.log   # just problems
grep 'finished:' ~/Library/Logs/FotoNerveShatter/app.log          # scan summaries
open -a Console ~/Library/Logs/FotoNerveShatter/app.log           # in Console.app
```

## Version control

Neither log is in the project's git: `app.log` lives outside the project, and `.server.log` is ignored (the `*.log` rule in `.gitignore`).
