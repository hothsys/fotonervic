# Logging

Foto Nerve Shatter doesn't keep an application log of its own. What the server prints to its console is the log, and where that goes depends on how you start it.

## Where the output goes

| Started with | Output |
|---|---|
| `FotoNerveShatter.app`, `FotoNerveShatter.command`, or `./server.sh start` | `.server.log` in the project folder |
| `python app.py` (e.g. on Windows) | The terminal window it runs in |

`server.sh` (which both macOS launchers use) runs the server in the background and redirects its output to `.server.log`. The file is overwritten each time the server starts, so it only covers the current run.

## What's in it

- **Setup**, with timings: creating `.venv` (first launch), installing uv, which packages were installed and how long it took, or "Dependencies up to date." when nothing changed.
- **ExifTool**: "ExifTool 13.63 ready.", or why it's being downloaded and the outcome ("ExifTool 13.63 installed (4.5 s)." or the failure and its cause, with up to two automatic retries).
- **Startup**: "Starting the web server on port …" and the banner with the app title and URL.
- **Library warnings**: e.g. LibRaw's `data corrupted at ...` lines when a thumbnail or Blur Check decodes a damaged RAW file. (The integrity check captures LibRaw's output itself to compute the corruption percentage, so those lines don't appear for Scan Directory.)
- **Errors**: Python tracebacks if something fails unexpectedly.

HTTP request lines (the standard `http.server` access log) are deliberately suppressed. Scan results aren't logged; use each scan's **Export CSV** for a record.

## What `server.sh` shows

`./server.sh start` (and `restart`) shows the log as the server starts, indented under its own messages, so you can see setup progress instead of a silent wait:

```
Starting Foto Nerve Shatter on port 5900 (log: .server.log)...
  ExifTool 13.63 ready.
  Dependencies up to date.
  Starting the web server on port 5900...
Foto Nerve Shatter started in 1 s (PID 6714) at http://localhost:5900
```

During a long quiet step it prints `...still starting (N s)` every 5 seconds. If ExifTool is still downloading when the server is up, it says so (the download finishes in the background; `./server.sh logs` shows the result). If the server fails to start, it shows the rest of the log, which says why.

## Reading the log

```bash
./server.sh logs                 # follow it live
tail -n 50 .server.log           # the most recent output
grep -i error .server.log        # just errors
```

## Version control

`.server.log` is ignored by git (the `*.log` rule in `.gitignore`), as are `server.sh`'s other runtime files, `.server.pid` and `.server.port`.
