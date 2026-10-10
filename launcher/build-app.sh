#!/usr/bin/env bash
# Generate the macOS launchers in the project root, named from APP_NAME in
# app.conf:
#   <APP_NAME>.app      from launcher/launcher.applescript
#   <APP_NAME>.command  copied from launcher/app.command
# Launchers left over from a previous APP_NAME are removed.
#
# Rebuilding changes the app's code signature, so macOS will ask for
# Downloads/volume access again the next time it's launched.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=../app.conf
source "$ROOT/app.conf"

BUNDLE_ID="local.$(printf %s "$APP_NAME" | tr '[:upper:] ' '[:lower:]-').launcher"
APP="$ROOT/$APP_NAME.app"
COMMAND="$ROOT/$APP_NAME.command"

# Remove launchers generated under an earlier name: .app bundles with our
# local.*.launcher bundle ID, and .command copies of launcher/app.command
for old in "$ROOT"/*.app; do
  [[ -e "$old" && "$old" != "$APP" ]] || continue
  id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$old/Contents/Info.plist" 2>/dev/null || true)"
  if [[ "$id" == local.*.launcher ]]; then
    echo "Removing old launcher $(basename "$old")"
    rm -rf "$old"
  fi
done
for old in "$ROOT"/*.command; do
  [[ -e "$old" && "$old" != "$COMMAND" ]] || continue
  if cmp -s "$old" "$HERE/app.command"; then
    echo "Removing old launcher $(basename "$old")"
    rm -f "$old"
  fi
done

rm -rf "$APP"
osacompile -o "$APP" "$HERE/launcher.applescript"

cp "$HERE/app.icns" "$APP/Contents/Resources/applet.icns"
cp "$HERE/dialog.icns" "$APP/Contents/Resources/dialog.icns"
# osacompile also ships a default icon in Assets.car, which macOS prefers over
# applet.icns via CFBundleIconName; drop it so the app logo is used
rm -f "$APP/Contents/Resources/Assets.car"
plutil -remove CFBundleIconName "$APP/Contents/Info.plist"
plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$APP/Contents/Info.plist"
plutil -replace CFBundleName -string "$APP_NAME" "$APP/Contents/Info.plist"

# Editing the bundle invalidates osacompile's signature; re-sign ad hoc
codesign --force --deep --sign - "$APP"
touch "$APP"

cp "$HERE/app.command" "$COMMAND"
chmod +x "$COMMAND"

# The launchers are only ad hoc signed (no notarization), so Gatekeeper blocks
# them if they carry the quarantine flag. Building on this Mac makes them local,
# but cp and the icon copies above inherit the flag when the project folder was
# itself downloaded/AirDropped, so clear it from what was just generated.
xattr -dr com.apple.quarantine "$APP" "$COMMAND" 2>/dev/null || true

echo "Built $APP"
echo "Built $COMMAND"
