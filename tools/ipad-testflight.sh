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
# Nach dem Hochladen: Stand merken (testflight.stand in der Ablage der App: Commit, Nummer, Zeit; liest der Takt
# tools/ipad-testflight-takt.sh) und Testhinweise setzen (Änderungen an der App seit dem letzten Build, oder
# KEVCAD_PAD_NOTIZ). KEVCAD_PAD_PLATZ=<Name> nimmt eigene Bauordner darunter (der Takt baut aus einer eigenen Arbeitskopie).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
BUNDLE_ID="${KEVCAD_PAD_BUNDLE_ID:-de.upvis.kevcad.ipad}"
TEAM=2GX7UC98J6
NUR_ARCHIV=0
[ "${1:-}" = "--nur-archiv" ] && NUR_ARCHIV=1
STAND="${KEVCAD_PAD_STAND:-$HOME/Library/Application Support/de.upvis.kevcad/testflight.stand}"
VORHER=""
[ -f "$STAND" ] && read -r VORHER _ < "$STAND"

BASIS="/Volumes/UPVIS ULTRA/_cache/kevcad-ipad${KEVCAD_PAD_PLATZ:+/$KEVCAD_PAD_PLATZ}"
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

# Das App-Symbol steht nicht im Git: In einer frischen Arbeitskopie fehlte es, und App Store Connect lehnte Build 2 ab
tools/ipad-bau.sh symbol || { echo "==> App-Symbol ließ sich nicht erzeugen"; exit 1; }
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
  if [ -n "$GRUPPE" ]; then
    echo "==> Testgruppe „Kevin“ angelegt ($GRUPPE)"
  else
    echo "==> Testgruppe „Kevin“ ließ sich nicht anlegen: in App Store Connect › TestFlight selbst anlegen (intern, alle Builds)"
  fi
fi
# Tester: alle aus den internen Gruppen der anderen Apps des Teams (interne Gruppen nehmen nur Nutzer von App Store
# Connect). Apple führt interne Tester je App als eigenen Eintrag mit derselben Mail-Adresse; einen Eintrag aus einer
# anderen App nimmt eine neue Gruppe nicht an (409 „Tester(s) cannot be assigned“, 07.11.2026). Deshalb über die
# Mail-Adresse neu anlegen, gleich in der Gruppe, und die Einladung ausdrücklich schicken.
if [ -n "$GRUPPE" ]; then
  python3 - "$GRUPPE" "$APP_ID" << 'PYEOF'
import json, subprocess, sys

gruppe, app = sys.argv[1], sys.argv[2]


def api(*args):
    r = subprocess.run(["asc-api", *args], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout) if r.stdout.strip() else {}


def tester(gruppe_id):
    """Tester einer Gruppe nach Mail-Adresse (klein geschrieben)."""
    antwort = api("GET", f"/v1/betaGroups/{gruppe_id}/betaTesters?limit=200") or {}
    return {t["attributes"]["email"].lower(): t["attributes"] for t in antwort.get("data") or []
            if t["attributes"].get("email")}


gesucht = {}
for g in (api("GET", "/v1/betaGroups?limit=200") or {}).get("data") or []:
    if g["id"] != gruppe and g["attributes"].get("isInternalGroup"):
        for mail, a in tester(g["id"]).items():
            gesucht.setdefault(mail, a)
schon = tester(gruppe)
for mail, a in sorted(gesucht.items()):
    if mail in schon:
        continue
    koerper = {"data": {"type": "betaTesters",
                        "attributes": {"email": a["email"], "firstName": a.get("firstName"), "lastName": a.get("lastName")},
                        "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": gruppe}]}}}}
    neu = ((api("POST", "/v1/betaTesters", json.dumps(koerper)) or {}).get("data") or {}).get("id")
    if neu:
        api("POST", "/v1/betaTesterInvitations", json.dumps({"data": {"type": "betaTesterInvitations", "relationships": {
            "app": {"data": {"type": "apps", "id": app}}, "betaTester": {"data": {"type": "betaTesters", "id": neu}}}}}))
jetzt = tester(gruppe)
if jetzt:
    print(f"==> Tester in der Gruppe „Kevin“: {len(jetzt)}, neu eingeladen: {len(set(jetzt) - set(schon))}")
else:
    print("==> Kein Tester in der Gruppe: in App Store Connect › TestFlight › Gruppe „Kevin“ selbst eintragen")
PYEOF
fi

# Stand merken: Der Takt baut erst wieder, wenn sich die App danach ändert
mkdir -p "$(dirname "$STAND")"
echo "$COMMIT $NR $(date +%s)" > "$STAND"

# Testhinweise in TestFlight: was sich seit dem letzten Build an der App geändert hat
if [ -n "${KEVCAD_PAD_NOTIZ:-}" ]; then
  NOTIZ="$KEVCAD_PAD_NOTIZ"
else
  if [ -n "$VORHER" ] && git cat-file -e "$VORHER^{commit}" 2>/dev/null; then
    AENDERUNGEN=$(git log --no-merges --format='- %s' "$VORHER..$COMMIT" -- app Package.swift | head -15)
  else
    AENDERUNGEN=$(git log --no-merges --format='- %s' -8 "$COMMIT" -- app Package.swift)
  fi
  NOTIZ="Stand $COMMIT vom $(date '+%d.%m.%Y, %H:%M') Uhr."
  [ -n "$AENDERUNGEN" ] && NOTIZ="$NOTIZ"$'\n\n'"Seit dem letzten Build:"$'\n'"$AENDERUNGEN"
fi
python3 -I tools/ipad-testhinweise.py "$APP_ID" "$NR" "$NOTIZ"
echo "==> Hochgeladen: Build $NR. App Store Connect verarbeitet ihn (meist 5 bis 30 Minuten), danach steht er in TestFlight."
