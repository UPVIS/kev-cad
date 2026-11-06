#!/bin/bash
# iPad-Fassung von Kev CAD zu TestFlight (PLAN-IPAD.md, I-9; Regel apple-app-verteilung).
#
#   tools/ipad-testflight.sh                Archiv fürs iPad, Export für App Store Connect, Hochladen, Testgruppe „Kevin“
#   tools/ipad-testflight.sh --nur-archiv   nur Archiv und Export (ohne Hochladen); prüft Signatur und Profil
#
# Signiert wird mit Kevins Team (2GX7UC98J6) und dem Team-Schlüssel aus dem Schlüsselbund (asc-mit-schluessel): Xcode legt
# das Profil selbst an, ohne angemeldetes Xcode. Hochladen braucht den App-Eintrag in App Store Connect (Bundle-ID
# de.upvis.kevcad.ipad; den legt Kevin einmal im Browser an). Die Build-Nummer ist die höchste dort plus 1.
# Bauordner, Archiv und Export liegen auf UPVIS ULTRA. Lokal unter der gemeinsamen Sperre.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
BUNDLE_ID="${KEVCAD_PAD_BUNDLE_ID:-de.upvis.kevcad.ipad}"
TEAM=2GX7UC98J6
NUR_ARCHIV=0
[ "${1:-}" = "--nur-archiv" ] && NUR_ARCHIV=1

BASIS="/Volumes/UPVIS ULTRA/_cache/kevcad-ipad"
[ -d "/Volumes/UPVIS ULTRA/_cache" ] || BASIS="$REPO/build/ipad"
ARCHIV="$BASIS/KevCADPad.xcarchive"
EXPORT="$BASIS/testflight"
LOG="$REPO/build/ipad-testflight.log"
mkdir -p "$BASIS" "$REPO/build"

# App in App Store Connect und nächste Build-Nummer
APP_ID=$(asc-api GET "/v1/apps?filter%5BbundleId%5D=$BUNDLE_ID&limit=1" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin).get('data') or []; print(d[0]['id'] if d else '')" 2>/dev/null)
if [ -n "$APP_ID" ]; then
  LETZTE=$(asc-api GET "/v1/builds?filter%5Bapp%5D=$APP_ID&sort=-version&limit=1" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin).get('data') or []; print(d[0]['attributes']['version'] if d else 0)" 2>/dev/null)
  NR=$(( ${LETZTE%%.*} + 1 ))
else
  [ "$NUR_ARCHIV" = 1 ] || { echo "Kein App-Eintrag für $BUNDLE_ID in App Store Connect (Kevin legt ihn einmal an)."; exit 1; }
  NR=1
fi
COMMIT=$(git rev-parse --short HEAD)
echo "==> Kev CAD fürs iPad, Build $NR ($COMMIT), Protokoll $LOG"

cat > "$BASIS/ExportOptions.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>app-store-connect</string>
  <key>teamID</key><string>$TEAM</string>
  <key>signingStyle</key><string>automatic</string>
  <key>destination</key><string>export</string>
  <key>uploadSymbols</key><true/>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
EOF

xcodegen generate --spec app/project.yml --quiet || exit 1
rm -rf "$ARCHIV" "$EXPORT"
# Archiv und Export mit dem Team-Schlüssel (nur für die Dauer des Befehls auf der Platte)
asc-mit-schluessel bash -c '
  set -e
  AUTH=(-allowProvisioningUpdates -authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID"
        -authenticationKeyIssuerID "$ASC_ISSUER_ID")
  lockf -k /tmp/vb-xcodebuild.lock xcodebuild -project app/KevCAD.xcodeproj -scheme KevCADPad -configuration Release \
    -destination "generic/platform=iOS" -archivePath "'"$ARCHIV"'" -derivedDataPath "'"$BASIS"'/dd-archiv" "${AUTH[@]}" \
    DEVELOPMENT_TEAM='"$TEAM"' CODE_SIGN_STYLE=Automatic KEVCAD_PAD_BUNDLE_ID='"$BUNDLE_ID"' KEVCAD_BUILD='"$NR"' \
    KEVCAD_COMMIT='"$COMMIT"' COMPILATION_CACHE_ENABLE_CACHING=YES CLANG_ENABLE_CODE_COVERAGE=NO archive
  xcodebuild -exportArchive -archivePath "'"$ARCHIV"'" -exportPath "'"$EXPORT"'" \
    -exportOptionsPlist "'"$BASIS"'/ExportOptions.plist" "${AUTH[@]}"
' > "$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  grep -E "error:|\*\* (ARCHIVE|EXPORT) FAILED|No profiles|requires a provisioning" "$LOG" | sed -E 's#^.*/(app/)#\1#' | sort -u | head -20
  echo "==> Archiv oder Export gescheitert (Ausgang $rc)"
  exit $rc
fi
IPA=$(ls "$EXPORT"/*.ipa 2>/dev/null | head -1)
[ -n "$IPA" ] || { echo "Keine .ipa im Export"; exit 1; }
echo "==> Exportiert: $IPA ($(du -h "$IPA" | cut -f1))"
[ "$NUR_ARCHIV" = 1 ] && exit 0

echo "==> Hochladen zu App Store Connect"
asc-mit-schluessel bash -c 'xcrun altool --upload-app -f "'"$IPA"'" -t ios --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"' \
  >> "$LOG" 2>&1 || { tail -20 "$LOG"; echo "==> Hochladen gescheitert"; exit 1; }

# Interne Testgruppe „Kevin“ mit Zugriff auf alle Builds (einmal), Kevin als Tester wie bei den anderen Apps
GRUPPE=$(asc-api GET "/v1/apps/$APP_ID/betaGroups" 2>/dev/null \
  | python3 -c "import sys,json; g=[x for x in json.load(sys.stdin).get('data') or [] if x['attributes']['name']=='Kevin']; print(g[0]['id'] if g else '')")
if [ -z "$GRUPPE" ]; then
  GRUPPE=$(asc-api POST /v1/betaGroups "{\"data\":{\"type\":\"betaGroups\",\"attributes\":{\"name\":\"Kevin\",\"isInternalGroup\":true,\"hasAccessToAllBuilds\":true},\"relationships\":{\"app\":{\"data\":{\"type\":\"apps\",\"id\":\"$APP_ID\"}}}}}" \
    | python3 -c "import sys,json; print((json.load(sys.stdin).get('data') or {}).get('id',''))")
  echo "==> Testgruppe „Kevin“ angelegt ($GRUPPE)"
fi
# Kevin als Tester: derselbe wie in einer anderen App mit Gruppe „Kevin“
TESTER=$(asc-api GET "/v1/betaTesters?limit=50" 2>/dev/null \
  | python3 -c "import sys,json; t=[x['id'] for x in json.load(sys.stdin).get('data') or []]; print(t[0] if len(t)==1 else '')")
if [ -n "$GRUPPE" ] && [ -n "$TESTER" ]; then
  asc-api POST "/v1/betaGroups/$GRUPPE/relationships/betaTesters" "{\"data\":[{\"type\":\"betaTesters\",\"id\":\"$TESTER\"}]}" > /dev/null 2>&1
fi
echo "==> Hochgeladen: Build $NR. App Store Connect verarbeitet ihn (meist 5 bis 30 Minuten), danach steht er in TestFlight."
