#!/usr/bin/env bash
# Build an unsigned Release Mapay.ipa for AltStore (see AGENTS.md › Platform: iPhone only).
#
#   cd frontend && scripts/build-ipa.sh
#
# Builds the web app, syncs it into the iOS project, builds App.app for iphoneos without code
# signing, and zips it as Payload/App.app → frontend/build/Mapay.ipa. AltStore re-signs it with
# the free Apple ID when you open the .ipa on the iPhone. Run it on the Mac.
set -euo pipefail

cd "$(dirname "$0")/.."
npm run build
npx cap sync ios

cd ios/App
# Capacitor 8 projects use Swift Package Manager (App.xcodeproj); older ones use CocoaPods (App.xcworkspace).
if [ -d App.xcworkspace ]; then container=(-workspace App.xcworkspace); else container=(-project App.xcodeproj); fi
xcodebuild "${container[@]}" -scheme App -configuration Release -sdk iphoneos \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build

out="$(cd ../.. && pwd)/build"
rm -rf "$out/Payload" && mkdir -p "$out/Payload"
cp -R build/Build/Products/Release-iphoneos/App.app "$out/Payload/"
(cd "$out" && rm -f Mapay.ipa && zip -qr Mapay.ipa Payload && rm -rf Payload)
echo "Built $out/Mapay.ipa"
