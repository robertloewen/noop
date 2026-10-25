#!/bin/bash
# Fork-only: `xcodegen generate` for an iPhone-only build under a free Apple ID.
#
# A Personal Team can only provision for devices it has registered. Without a paired Apple Watch the
# embedded watch app (NOOPWatch + its complications) cannot be signed and the NOOPiOS build fails. This
# script generates the project from a copy of project.yml with that one embed dependency removed, so
# upstream's project.yml stays untouched and the upstream sync never conflicts on it.
#
# It also carries the signing team over: when Config/BundleIdSecrets.xcconfig has no DEVELOPMENT_TEAM
# yet but the existing Strand.xcodeproj does (because a team was picked in Xcode), the id is written to
# the xcconfig, so it survives every later regeneration.
#
# Usage (from anywhere inside the repo):  Tools/fork/generate-ios.sh
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"

spec="project.yml"
fork_spec="project.fork.yml"   # gitignored; must sit beside project.yml so relative paths resolve
secrets="Config/BundleIdSecrets.xcconfig"
watch_dep='^      - target: NOOPWatch$'

command -v xcodegen >/dev/null || { echo "xcodegen not found: brew install xcodegen" >&2; exit 1; }

# Exactly one match, or stop: if upstream restructures project.yml, a silent no-op would bring the
# signing failure back with no hint why.
count=$(grep -c "$watch_dep" "$spec" || true)
if [ "$count" != "1" ]; then
  echo "Expected exactly one NOOPWatch embed line in $spec, found $count." >&2
  echo "project.yml changed upstream; update watch_dep in $0." >&2
  exit 1
fi

if [ ! -f "$secrets" ]; then
  echo "$secrets is missing. Create it first:" >&2
  echo "  cp Config/BundleIdSecrets.example.xcconfig $secrets  (then set BUNDLE_ID_PREFIX)" >&2
  exit 1
fi

if ! grep -q '^[[:space:]]*DEVELOPMENT_TEAM[[:space:]]*=' "$secrets"; then
  team=$(grep -ho 'DEVELOPMENT_TEAM = [A-Z0-9]\{10\};' Strand.xcodeproj/project.pbxproj 2>/dev/null \
    | sort -u | head -1 | sed 's/DEVELOPMENT_TEAM = //; s/;//' || true)
  if [ -n "$team" ]; then
    printf '\n// Added by Tools/fork/generate-ios.sh from the team picked in Xcode.\nDEVELOPMENT_TEAM = %s\n' "$team" >> "$secrets"
    echo "Saved DEVELOPMENT_TEAM = $team to $secrets."
  else
    echo "Note: no DEVELOPMENT_TEAM yet. Pick your team once in Xcode, then run this script again."
  fi
fi

grep -v "$watch_dep" "$spec" > "$fork_spec"
xcodegen generate --spec "$fork_spec"
echo "Generated Strand.xcodeproj without the embedded watch app. Build the NOOPiOS scheme."
