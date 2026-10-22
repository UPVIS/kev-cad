#!/bin/bash
# Kev Scan (iPhone-App für LiDAR-Scans, ios/KevScan, Vertrag SCAN.md) bauen und auf Kevins iPhone spielen.
#
#   tools/kevscan.sh bauen         Release für das Gerät bauen, Ergebnis nach build/KevScan.app
#   tools/kevscan.sh installieren  build/KevScan.app auf das iPhone spielen (devicectl)
#   tools/kevscan.sh alles         beides (Vorgabe)
#   tools/kevscan.sh starten       App auf dem iPhone starten
#   tools/kevscan.sh geraet        geraet.json vom iPhone holen (Videoformate laut ARKit, gemessene Fotogröße)
#
# Gebaut wird für iOS allgemein ('generic/platform=iOS'), das iPhone muss dafür nicht erreichbar sein. Signiert mit Team
# 2GX7UC98J6, automatische Signierung, -allowProvisioningUpdates (Vorbild: VoiceBridge/Tools/build-and-install.sh).
# Gebaut wird unter der mit VoiceBridge gemeinsamen Sperre /tmp/vb-xcodebuild.lock und erst bei mindestens 25 % freiem
# Speicher. DerivedData liegt in /tmp/kevscan-build und wird nach dem Bau gelöscht (die Systemplatte ist knapp).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
IOS_DIR="$ROOT/ios/KevScan"
DERIVED=/tmp/kevscan-build
LOG=/tmp/kevscan-build.log
OUT="$ROOT/build/KevScan.app"
BUNDLE_ID=de.upvis.kevscan
LOCK=/tmp/vb-xcodebuild.lock
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }

warte_auf_speicher() {
  local frei waited=0
  while true; do
    frei=$(memory_pressure 2>/dev/null | tail -1 | grep -oE '[0-9]+' | tail -1)
    [ -z "$frei" ] && return 0
    [ "$frei" -ge 25 ] && return 0
    if [ "$waited" -ge 600 ]; then
      echo "Nach 10 Minuten immer noch nur $frei % Speicher frei, baue trotzdem."
      return 0
    fi
    [ $(( waited % 120 )) -eq 0 ] && echo "Nur $frei % Speicher frei, warte …"
    sleep 20
    waited=$(( waited + 20 ))
  done
}

bauen() {
  command -v xcodegen >/dev/null || { echo "xcodegen fehlt: brew install xcodegen"; return 1; }
  (cd "$IOS_DIR" && xcodegen generate --quiet) || { echo "xcodegen gescheitert."; return 1; }
  warte_auf_speicher
  rm -rf "$DERIVED"
  echo "==> Baue Kev Scan (Release, iOS-Gerät) …"
  lockf -k "$LOCK" xcodebuild -project "$IOS_DIR/KevScan.xcodeproj" -scheme KevScan -configuration Release \
    -destination 'generic/platform=iOS' -allowProvisioningUpdates -derivedDataPath "$DERIVED" build >"$LOG" 2>&1
  local status=$?
  grep -E "error:|\*\* BUILD" "$LOG" | sort -u | head -40
  local app="$DERIVED/Build/Products/Release-iphoneos/KevScan.app"
  # Auch ein gescheiterter Bau kann ein leeres Bündel hinterlassen: ohne Programmdatei nichts übernehmen.
  if [ "$status" -ne 0 ] || [ ! -x "$app/KevScan" ]; then
    echo "Bau gescheitert, Protokoll: $LOG"
    rm -rf "$DERIVED"
    return 1
  fi
  mkdir -p "$ROOT/build"
  rm -rf "$OUT"
  ditto "$app" "$OUT"
  rm -rf "$DERIVED"
  echo "Gebaut: build/KevScan.app ($(du -sh "$OUT" | cut -f1))"
}

# Erstes erreichbares echtes iPhone ("connected" oder "available (paired)").
finde_iphone() {
  xcrun devicectl list devices 2>/dev/null \
    | grep -i iphone | grep -v "unavailable" | grep -v "simulated" \
    | grep -oE '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}|[0-9A-F]{8}-[0-9A-F]{16}' | head -1
}

iphone_oder_hinweis() {
  local device
  device=$(finde_iphone) || true
  if [ -z "$device" ]; then
    echo "iPhone nicht über devicectl erreichbar. iPhone entsperrt in die Nähe legen (gleiches WLAN oder Kabel), dann:"
    echo "  tools/kevscan.sh installieren"
    xcrun devicectl list devices 2>&1 | grep -i iphone | grep -v simulated
    return 2
  fi
  echo "$device"
}

installieren() {
  [ -x "$OUT/KevScan" ] || { echo "Noch nichts gebaut: tools/kevscan.sh bauen"; return 1; }
  local device out
  device=$(iphone_oder_hinweis) || { echo "$device"; return 2; }
  echo "==> Spiele Kev Scan auf das iPhone ($device) …"
  out=$(xcrun devicectl device install app --device "$device" "$OUT" 2>&1) || true
  if ! grep -qi "installed" <<<"$out"; then
    echo "Installation gescheitert:"
    grep -iE "rror|fail|locked|unlock" <<<"$out" | head -8
    return 1
  fi
  echo "Auf dem iPhone installiert."
}

starten() {
  local device
  device=$(iphone_oder_hinweis) || { echo "$device"; return 2; }
  xcrun devicectl device process launch --device "$device" "$BUNDLE_ID" 2>&1 | grep -vE "^\s*$" | tail -3
}

geraet() {
  local device tmp
  device=$(iphone_oder_hinweis) || { echo "$device"; return 2; }
  tmp=$(mktemp -d)
  if xcrun devicectl device copy from --device "$device" --domain-type appDataContainer \
       --domain-identifier "$BUNDLE_ID" --source "Library/Application Support/geraet.json" \
       --destination "$tmp/geraet.json" >/dev/null 2>&1; then
    cat "$tmp/geraet.json"
  else
    echo "geraet.json nicht abrufbar (App noch nie gestartet oder iPhone gesperrt)."
  fi
  rm -rf "$tmp"
}

case "${1:-alles}" in
  bauen) bauen ;;
  installieren) installieren ;;
  alles) bauen && installieren ;;
  starten) starten ;;
  geraet) geraet ;;
  -h|--help|hilfe) usage ;;
  *) usage; exit 1 ;;
esac
