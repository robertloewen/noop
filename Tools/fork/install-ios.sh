#!/bin/bash
# Fork-only: build the iPhone app and install it on a connected iPhone, no Xcode clicks needed.
#
# Regenerates the project through generate-ios.sh (no embedded watch app, team from
# Config/BundleIdSecrets.xcconfig), builds the NOOPiOS scheme for a device and installs NOOP.app with
# devicectl. The iPhone must be paired with this Mac: by cable, or over Wi-Fi once "Connect via network"
# is ticked for it in Xcode (Window > Devices and Simulators).
#
# Usage:  Tools/fork/install-ios.sh [device]
#   device: name or identifier as `xcrun devicectl list devices` prints it. Defaults to $NOOP_DEVICE.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"

device="${1:-${NOOP_DEVICE:-}}"
if [ -z "$device" ]; then
  echo "No device given. Pass one, or export NOOP_DEVICE. Paired devices:" >&2
  xcrun devicectl list devices >&2 || true
  exit 1
fi

derived="build/fork-ios"   # build/ is gitignored
Tools/fork/generate-ios.sh

xcodebuild -project Strand.xcodeproj -scheme NOOPiOS -configuration Debug \
  -destination 'generic/platform=iOS' -derivedDataPath "$derived" \
  -allowProvisioningUpdates build | tail -n 20

app="$derived/Build/Products/Debug-iphoneos/NOOP.app"
[ -d "$app" ] || { echo "Build output not found at $app" >&2; exit 1; }

xcrun devicectl device install app --device "$device" "$app"
echo "Installed NOOP on $device."
