# Logging

Foto Nerve Shatter doesn't keep an application log of its own. What the server prints to its console is the log, and where that goes depends on how you start it.

## Where the output goes

| Started with | Output |
|---|---|
| `FotoNerveShatter.app`, `FotoNerveShatter.command`, or `./server.sh start` | `.server.log` in the project folder |
| `python app.py` (e.g. on Windows) | The terminal window it runs in |

`server.sh` (which both macOS launchers use) runs the server in the background and redirects its output to `.server.log`. The file is overwritten each time the server starts, so it only covers the current run.

## What's in it

- **Startup**: the banner with the app title and URL.
- **Dependency install**: packages installed on first run, and a note if the optional onnxruntime install failed.
- **Library warnings**: e.g. LibRaw's `data corrupted at ...` lines when a thumbnail or Blur Check decodes a damaged RAW file. (The integrity check captures LibRaw's output itself to compute the corruption percentage, so those lines don't appear for Scan Directory.)
- **Errors**: Python tracebacks if something fails unexpectedly.

HTTP request lines (the standard `http.server` access log) are deliberately suppressed. Scan results aren't logged; use each scan's **Export CSV** for a record.

If the server fails to start, `server.sh start` prints the last 20 lines of `.server.log`.

## Reading the log

```bash
./server.sh logs                 # follow it live
tail -n 50 .server.log           # the most recent output
grep -i error .server.log        # just errors
```

## Version control

`.server.log` is ignored by git (the `*.log` rule in `.gitignore`), as are `server.sh`'s other runtime files, `.server.pid` and `.server.port`.
