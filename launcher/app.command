#!/usr/bin/env bash
# Template for the Finder launcher. launcher/build-app.sh copies it to
# <APP_NAME>.command in the project root; edit this file, not the copy.
#
# Double-click in Finder to start the app. Press Return (or close the window) to stop it.

cd "$(dirname "$0")" || exit 1
source ./app.conf
APP_TITLE="${APP_TITLE:-$APP_NAME}"

# Finder launches may not load your shell profile; make sure a Homebrew or
# python.org python3 (with Pillow) is found before the bare system one
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

./server.sh start || { echo; read -r -p "Press Return to close."; exit 1; }

trap './server.sh stop; exit' HUP INT TERM

echo
read -r -p "$APP_TITLE is running. Press Return to stop it. "
./server.sh stop
