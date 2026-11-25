# Getting started

Foto Nerve Shatter runs as a local web server at [http://localhost:5900](http://localhost:5900) and opens your browser when it starts. There's nothing to install by hand: on first launch it creates its own Python environment (`.venv/` in the project folder, so your system Python is untouched), installs [`requirements.txt`](../requirements.txt) into it with [uv](https://docs.astral.sh/uv/) (a fast installer, set up automatically), and downloads ExifTool for Exif Info at the same time. That's about 40 MB, so the first launch takes 5 to 30 seconds depending on your connection. Later launches start in about a second; when `requirements.txt` changes (e.g. a Dependabot update), the reinstall takes under a second.

## macOS

Double-click **`FotoNerveShatter.app`** in the project folder. Foto Nerve Shatter starts in the background (no Terminal window) and your browser opens.

- **First launch:** if macOS asks whether Foto Nerve Shatter can access your Downloads folder or a removable volume, click **Allow**. Foto Nerve Shatter needs this to scan your photos.
- **On another Mac:** if macOS says *"Apple could not verify FotoNerveShatter is free of malware"*, or the app says it *can't find its project folder* (or `sh: ./app.conf: No such file or directory`), that's Gatekeeper: the launchers are signed locally, not notarized by Apple, so macOS blocks copies that arrive by download, AirDrop, or zip. Either:
  - **Rebuild the launchers on that Mac (recommended).** In Terminal, from the project folder, run `launcher/build-app.sh` once. Launchers built on the Mac itself aren't blocked.
  - **Or clear the quarantine flag** without rebuilding: in Terminal, from the project folder, run `xattr -dr com.apple.quarantine .`

  System Settings' **Open Anyway** isn't enough on its own: it gets past the warning, but macOS then runs the app from a temporary copy where it can't find `app.conf` and `server.sh`.
- **To stop it or reopen the browser:** double-click FotoNerveShatter.app again. A dialog says Foto Nerve Shatter is already running and offers **Open in Browser** or **Stop Foto Nerve Shatter**. If you keep another copy of the project and launch the app from there, it detects the running instance on the configured port and shows the same dialog.
- **Dock shortcut:** drag FotoNerveShatter.app onto the Dock. Keep the app itself in the project folder, because it uses `server.sh` next to it.

Prefer a Terminal window? Double-click **FotoNerveShatter.command** instead; it starts Foto Nerve Shatter from a Terminal window, and pressing Return there stops it. You can also use the `server.sh` commands below (`./server.sh logs` follows the server log; see [Logging](logging.md)).

## Linux

From the project folder:

```bash
./server.sh start         # start in the background and open the browser
./server.sh stop          # stop it
./server.sh status        # check whether it's running
./server.sh logs          # follow the app's log (~/Library/Logs/FotoNerveShatter/app.log)
./server.sh restart
```

Add a port number to `start` or `restart` (e.g. `./server.sh start 8080`) to use a different port. Alternatively, edit `app.conf` (`PORT=5900`) so FotoNerveShatter.app and `server.sh` share the same setting.

## Windows

From the project folder in Command Prompt or PowerShell:

```bash
python app.py             # start (use "py app.py" if "python" isn't found)
python app.py 8080        # start on a different port
```

Leave the window open while you use Foto Nerve Shatter, and press **Ctrl+C** in it to stop. (Under WSL, use the Linux instructions.)

## Requirements

- Python 3.12+ (macOS includes Perl and curl, which ExifTool's download uses)

Everything else is installed automatically into `.venv/` from [`requirements.txt`](../requirements.txt), which Dependabot keeps current:

- **Pillow**, **numpy**: required
- **uv**: the installer `app.py` uses for the rest (installed with pip first; if it can't be, pip is used instead)
- **rawpy** (full RAW support), **pillow-heif** (HEIC/HEIF), **onnxruntime** (Blur Check's AI quality model), **PyExifTool** (runs ExifTool for Exif Info): optional, marked `# optional` in `requirements.txt`. Each is installed on its own, so if one fails (e.g. no build for a new Python version yet) only that feature is turned off.

No external web framework is needed; it uses Python's built-in `http.server`. To start over with a clean environment, delete `.venv/` and launch again.
