#!/bin/bash
# iPad-Bauten von Kev CAD (PLAN-IPAD.md). Bis tools/fern.sh die iPad-Ziele selbst baut, ist dies der Weg, vor einem Commit
# auch die iPad-Seite zu übersetzen (CLAUDE.md, „Mac und iPad“).
#
#   tools/ipad-bau.sh kern            KevCADCore mit KevCADWire und Viewport für den iPad-Simulator übersetzen
#   tools/ipad-bau.sh kern geraet     dasselbe für ein echtes iPad (ohne Signatur)
#   tools/ipad-bau.sh test            Tests des Kerns im iPad-Simulator (ohne Simulatorfenster, Schema KevCADCore-Package)
#   tools/ipad-bau.sh app             iPad-App (Ziel KevCADPad) für den Simulator bauen, nach "build/Kev CAD iPad.app"
#   tools/ipad-bau.sh gesten          Gesten-Tests (XCUITest, UITests/KevCADPad) im iPad-Simulator, ohne Simulatorfenster
#   tools/ipad-bau.sh release         iPad-App als Release für ein echtes iPad übersetzen, ohne Signatur: findet, was sonst
#                                     erst das Archiv für TestFlight zeigt (Code unter #if DEBUG); tools/fern.sh ipadrelease
#   tools/ipad-bau.sh symbol          nur das App-Symbol aus app/icon.svg erzeugen (steht nicht im Git)
#   tools/ipad-bau.sh starten         Simulator booten (ohne Simulator.app, kein Fenster), App installieren, im Demomodus
#                                     starten, Bildschirmfoto nach build/ipad-start.png
#   tools/ipad-bau.sh stoppen [immer] App beenden; den Simulator herunterfahren, wenn `starten` ihn gebootet hat (lief er
#                                     schon, etwa für die Tests eines anderen Agenten, bleibt er an; mit `immer` auch dann)
#   tools/ipad-bau.sh foto [datei]    starten, Foto, stoppen in einem Zug unter der Simulator-Sperre (für mehrere Agenten
#                                     zugleich der Weg zum Bild; ohne Datei build/ipad-start.png)
#   tools/ipad-bau.sh selbsttest      Selbsttest der Oberfläche in der gebauten App (KEVCAD_SELFTEST=pad, Demo-Lauf, ohne
#                                     Mac) unter der Simulator-Sperre; Bericht und Bilder nach build/ipad-selbsttest/
#
# Simulator: KEVCAD_IPAD_SIM (Vorgabe „iPad Pro 13-inch (M5)“). Umgebung der App beim Start: KEVCAD_IPAD_DEMO (Vorgabe
# „kern“: Demo-Lauf des App-Kerns mit echter Geometrie; „metal“ oder „aus“ für die anderen Demowege bzw. ohne Vorgabe),
# KEVCAD_IPAD_WARTEN (Sekunden bis zum Bildschirmfoto, Vorgabe 8).
#
# Es gibt einen Simulator für alle Arbeitskopien: `test`, `foto` und tools/ipad-kette.sh nehmen dafür die Sperre
# /tmp/kevcad-ipad-sim.lock (immer vor der Bausperre, nie umgekehrt). `starten` und `stoppen` einzeln nur, wenn kein
# anderer Agent den Simulator braucht.
# Bauten laufen hier unter der gemeinsamen Sperre /tmp/vb-xcodebuild.lock und warten vorher bis zu 10 Minuten auf 25 %
# freien Speicher. Bauordner und Xcode-Zwischenspeicher liegen auf UPVIS ULTRA (die Systemplatte ist knapp), ohne die
# Platte unter build/ipad. Protokoll: build/ipad-<art>-<ziel>.log; Ausgang wie xcodebuild.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

ART=${1:-}
ZIEL=${2:-simulator}
SCHEMA=KevCADCore
AKTION=build
KONF=Debug
SIM_NAME="${KEVCAD_IPAD_SIM:-iPad Pro 13-inch (M5)}"
PAD_BUNDLE_ID=de.upvis.kevcad.ipad
PAD_APP="$REPO/build/Kev CAD iPad.app"
GEBOOTET="$REPO/build/ipad-sim-gebootet"

hilfe() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

# UDID des Simulators mit diesem Namen (der neueste, falls es mehrere Laufzeiten gibt)
sim_udid() {
  xcrun simctl list devices available -j | /usr/bin/python3 -c '
import json, sys
name = sys.argv[1]
treffer = [d for laufzeit, ds in json.load(sys.stdin)["devices"].items() for d in ds if d["name"] == name]
print(treffer[-1]["udid"] if treffer else "")' "$SIM_NAME"
}

sim_zustand() {
  xcrun simctl list devices -j | /usr/bin/python3 -c '
import json, sys
u = sys.argv[1]
print(next((d["state"] for ds in json.load(sys.stdin)["devices"].values() for d in ds if d["udid"] == u), ""))' "$1"
}

# App-Symbol aus app/icon.svg (wie build.sh das Symbol des Mac): randlos, ohne Transparenz, das iPad rundet selbst ab.
# Das PNG steht nicht im Git; jede frische Arbeitskopie (der Takt in tools/ipad-testflight-takt.sh) erzeugt es neu,
# sonst lehnt App Store Connect den Build ab (90023, 90713: kein Symbol, kein CFBundleIconName).
symbol() {
  local png="app/Sources/KevCADPad/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
  [ ! -f "$png" ] || [ app/icon.svg -nt "$png" ] || return 0
  command -v rsvg-convert > /dev/null || { echo "rsvg-convert fehlt (brew install librsvg)"; return 1; }
  sed 's|<rect x="64" y="64" width="896" height="896" rx="200"|<rect x="0" y="0" width="1024" height="1024"|' app/icon.svg \
    | rsvg-convert -w 1024 -h 1024 -o "$png.tmp.png" || return 1
  if command -v magick > /dev/null; then
    magick "$png.tmp.png" -background "#151B24" -alpha remove -alpha off "$png" && rm -f "$png.tmp.png"
  else
    mv "$png.tmp.png" "$png"
  fi
}

case "$ART" in
  symbol) symbol; exit $? ;;
  kern) ;;
  test)
    # Simulator nur über xcodebuild starten: Er bootet ohne Fenster, Kevins Bildschirm bleibt frei
    SCHEMA=KevCADCore-Package
    AKTION=test
    ZIEL=test ;;
  app)
    SCHEMA=KevCADPad
    ZIEL=simulator ;;
  gesten)
    # XCUITest der App (I-3b): wie test nur über xcodebuild, unter der Simulator-Sperre
    SCHEMA=KevCADPad
    AKTION=test
    ZIEL=test ;;
  release)
    # Wie das Archiv für TestFlight (Release, echtes iPad), aber ohne Signatur und ohne Export: prüft nur das Übersetzen
    SCHEMA=KevCADPad
    KONF=Release
    ZIEL=geraet ;;
  foto)
    # Unter der Simulator-Sperre: starten, Foto kopieren, stoppen (ein anderer Agent wartet so, statt mitten hineinzufunken)
    if [ -z "${KEVCAD_IPAD_SIM_GESPERRT:-}" ]; then
      exec env KEVCAD_IPAD_SIM_GESPERRT=1 lockf -k /tmp/kevcad-ipad-sim.lock "$0" foto "${2:-}"
    fi
    "$0" starten || { "$0" stoppen > /dev/null; exit 1; }
    ziel="${2:-}"
    [ -n "$ziel" ] && cp "$REPO/build/ipad-start.png" "$ziel" && echo "==> Foto: $ziel"
    "$0" stoppen
    exit 0 ;;
  selbsttest)
    # Wie foto: unter der Simulator-Sperre starten (mit KEVCAD_SELFTEST=pad), auf den Bericht warten, stoppen
    if [ -z "${KEVCAD_IPAD_SIM_GESPERRT:-}" ]; then
      exec env KEVCAD_IPAD_SIM_GESPERRT=1 lockf -k /tmp/kevcad-ipad-sim.lock "$0" selbsttest
    fi
    KEVCAD_IPAD_SELBSTTEST=pad KEVCAD_IPAD_WARTEN=1 "$0" starten > /dev/null || { "$0" stoppen > /dev/null; exit 1; }
    UDID=$(sim_udid)
    DATEN=$(xcrun simctl get_app_container "$UDID" "$PAD_BUNDLE_ID" data)
    BERICHT="$DATEN/Library/Application Support/$PAD_BUNDLE_ID/selftest-pad/bericht.txt"
    for _ in $(seq 1 120); do
      grep -q "^ENDE" "$BERICHT" 2>/dev/null && break
      sleep 1
    done
    rm -rf "$REPO/build/ipad-selbsttest"
    cp -R "$(dirname "$BERICHT")" "$REPO/build/ipad-selbsttest" 2>/dev/null
    "$0" stoppen > /dev/null
    if [ -f "$REPO/build/ipad-selbsttest/bericht.txt" ]; then
      cat "$REPO/build/ipad-selbsttest/bericht.txt"
      grep -q "^ENDE bestanden" "$REPO/build/ipad-selbsttest/bericht.txt"
      exit $?
    fi
    echo "Kein Bericht nach 120 s (läuft der Selbsttest im Debug-Bau?)"
    exit 1 ;;
  starten)
    [ -d "$PAD_APP" ] || { echo "Erst bauen: tools/ipad-bau.sh app"; exit 1; }
    UDID=$(sim_udid)
    [ -n "$UDID" ] || { echo "Simulator „${SIM_NAME}“ fehlt (xcrun simctl list devices)"; exit 1; }
    # Nur simctl: bootet ohne Simulator.app, es erscheint kein Fenster auf Kevins Bildschirm
    if [ "$(sim_zustand "$UDID")" != "Booted" ]; then
      echo "==> Simulator „${SIM_NAME}“ booten (ohne Fenster)"
      xcrun simctl boot "$UDID" || exit 1
      mkdir -p "$REPO/build" && echo "$UDID" > "$GEBOOTET"
    else
      echo "==> Simulator „${SIM_NAME}“ läuft schon"
    fi
    xcrun simctl bootstatus "$UDID" > /dev/null || exit 1
    echo "==> App installieren und starten"
    xcrun simctl terminate "$UDID" "$PAD_BUNDLE_ID" > /dev/null 2>&1 || true
    xcrun simctl install "$UDID" "$PAD_APP" || exit 1
    # Ohne das Blatt zum Koppeln, damit das Foto die Oberfläche zeigt (PadStart.kopplungsBlattBeimStart)
    UMGEBUNG=(SIMCTL_CHILD_KEVCAD_PAD_OHNE_KOPPLUNGSBLATT=1)
    [ -n "${KEVCAD_IPAD_SELBSTTEST:-}" ] && UMGEBUNG+=("SIMCTL_CHILD_KEVCAD_SELFTEST=$KEVCAD_IPAD_SELBSTTEST")
    case "${KEVCAD_IPAD_DEMO:-kern}" in
      aus) ;;
      *) UMGEBUNG+=(SIMCTL_CHILD_KEVCAD_DEMO=1 "SIMCTL_CHILD_KEVCAD_DEMO_VIEWPORT=${KEVCAD_IPAD_DEMO:-kern}"
           SIMCTL_CHILD_KEVCAD_DEMO_STATE=live) ;;
    esac
    # I-4: Werkzeugkranz beim Start offen zeigen (nur Debug-Bauten), etwa KEVCAD_KRANZ=ansichten
    [ -n "${KEVCAD_KRANZ:-}" ] && UMGEBUNG+=("SIMCTL_CHILD_KEVCAD_KRANZ=$KEVCAD_KRANZ")
    env "${UMGEBUNG[@]}" xcrun simctl launch "$UDID" "$PAD_BUNDLE_ID" || exit 1
    sleep "${KEVCAD_IPAD_WARTEN:-8}"
    FOTO="$REPO/build/ipad-start.png"
    xcrun simctl io "$UDID" screenshot "$FOTO" > /dev/null 2>&1 || { echo "Bildschirmfoto ging nicht"; exit 1; }
    echo "==> Bildschirmfoto: $FOTO"
    exit 0 ;;
  stoppen)
    UDID=$(sim_udid)
    [ -n "$UDID" ] || exit 0
    xcrun simctl terminate "$UDID" "$PAD_BUNDLE_ID" > /dev/null 2>&1 || true
    if [ -f "$GEBOOTET" ] || [ "$ZIEL" = immer ]; then
      echo "==> Simulator „${SIM_NAME}“ herunterfahren"
      xcrun simctl shutdown "$UDID" > /dev/null 2>&1 || true
      rm -f "$GEBOOTET"
    else
      echo "==> App beendet; der Simulator lief schon vor dem Start und bleibt an (mit „stoppen immer“ auch aus)"
    fi
    exit 0 ;;
  *) hilfe; exit 2 ;;
esac
case "$ZIEL" in
  simulator) DEST='generic/platform=iOS Simulator'; EXTRA=() ;;
  geraet) DEST='generic/platform=iOS'; EXTRA=(CODE_SIGNING_ALLOWED=NO) ;;
  test) DEST="platform=iOS Simulator,name=$SIM_NAME"; EXTRA=() ;;
  *) echo "Ziel: simulator oder geraet"; exit 2 ;;
esac

if [ -d "/Volumes/UPVIS ULTRA/_cache" ]; then
  BASIS="/Volumes/UPVIS ULTRA/_cache/kevcad-ipad"
  CAS="/Volumes/UPVIS ULTRA/_cache/xcode-cas/kevcad"
else
  BASIS="$REPO/build/ipad"
  CAS=""
fi
mkdir -p "$BASIS" "$REPO/build"
DD="$BASIS/dd-$ART"
LOG="$REPO/build/ipad-$ART-$ZIEL.log"

# Speicher: der MacBook hat 16 GB, andere Bauten laufen mit
for _ in $(seq 1 60); do
  frei=$(memory_pressure 2>/dev/null | awk -F': ' '/free percentage/ {gsub("%", "", $2); print $2}')
  if [ -z "$frei" ] || [ "$frei" -ge 25 ]; then break; fi
  sleep 10
done

# Wie build.sh: Zwischenspeicher mit herausgerechneten Pfaden, damit jede Arbeitskopie die Übersetzungen der anderen nutzt
map='$(OBJROOT)/GeneratedModuleMaps=/^gmm $(MODULE_CACHE_DIR)=/^mcache '"${REPO// /\\ }"'=/^repo'
CACHE=(COMPILATION_CACHE_ENABLE_CACHING=YES CLANG_ENABLE_CODE_COVERAGE=NO
  SWIFT_ENABLE_PREFIX_MAPPING=YES CLANG_ENABLE_PREFIX_MAPPING=YES
  SWIFT_ENABLE_PROJECT_PREFIX_MAPPING=YES CLANG_ENABLE_PROJECT_PREFIX_MAPPING=YES
  "SWIFT_OTHER_PREFIX_MAPPINGS=$map" "CLANG_OTHER_PREFIX_MAPPINGS=$map")
# Tests suchen ihre Testdateien über #filePath (WireTestSupport, Fixtures): Mit herausgerechneten Pfaden zeigte das auf
# /^src (Regel xcode-compilation-cache, „Preis der Projekt-Zuordnung“). Testbauten deshalb ohne Zuordnung.
[ "$AKTION" = test ] && CACHE=(COMPILATION_CACHE_ENABLE_CACHING=YES CLANG_ENABLE_CODE_COVERAGE=NO)
[ -n "$CAS" ] && CACHE+=("COMPILATION_CACHE_CAS_PATH=$CAS")

# Systemplatte: unter 4 GB frei nicht bauen oder testen (der Simulator und Xcode schreiben dort Kleinigkeiten, andere Agenten
# auch; am 07.11.2026 lief sie mitten in einem Testlauf voll). KEVCAD_IPAD_PLATZ_GB ändert die Schwelle.
frei_gb=$(df -k /System/Volumes/Data 2>/dev/null | awk 'NR==2 {print int($4 / 1048576)}')
if [ -n "$frei_gb" ] && [ "$frei_gb" -lt "${KEVCAD_IPAD_PLATZ_GB:-4}" ]; then
  echo "==> Systemplatte fast voll (${frei_gb} GB frei, unter ${KEVCAD_IPAD_PLATZ_GB:-4} GB): $ART angehalten"
  exit 28
fi

start=$(date +%s)
echo "==> $ART für iPad ($ZIEL), Protokoll $LOG"
# Kurzfassung der Paritätsprüfung Mac/iPad (tools/paritaet.py); sie hält nichts auf.
[ -f tools/paritaet.py ] && { python3 tools/paritaet.py --kurz 2>/dev/null || true; }
if [ "$ART" = app ] || [ "$ART" = gesten ] || [ "$ART" = release ]; then
  command -v xcodegen > /dev/null || { echo "xcodegen fehlt (brew install xcodegen)"; exit 1; }
  symbol || exit 1
  xcodegen generate --spec app/project.yml --quiet || exit 1
  BUILD_NUMBER=$(git rev-list --count HEAD 2>/dev/null || echo 1)
  COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "")
  [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] && COMMIT="$COMMIT+"
  # Nur arm64: Der Simulator auf dem Mac mit Apple-Chip braucht kein x86_64 (sonst übersetzt alles doppelt)
  NUR=()
  SIM_SPERRE=()
  if [ "$ART" = gesten ]; then
    # KEVCAD_GESTEN_NUR=testName: nur dieser Test (kurze Runden)
    NUR=("-only-testing:KevCADPadUITests${KEVCAD_GESTEN_NUR:+/GestenUITests/$KEVCAD_GESTEN_NUR}" -parallel-testing-enabled NO)
    SIM_SPERRE=(lockf -k /tmp/kevcad-ipad-sim.lock)
  fi
  (cd app && ${SIM_SPERRE[@]+"${SIM_SPERRE[@]}"} lockf -k /tmp/vb-xcodebuild.lock xcodebuild -project KevCAD.xcodeproj \
    -scheme "$SCHEMA" -configuration "$KONF" -destination "$DEST" -derivedDataPath "$DD" "${CACHE[@]}" ARCHS=arm64 \
    ONLY_ACTIVE_ARCH=YES KEVCAD_BUILD="$BUILD_NUMBER" KEVCAD_COMMIT="$COMMIT" ${EXTRA[@]+"${EXTRA[@]}"} \
    ${NUR[@]+"${NUR[@]}"} "$AKTION") > "$LOG" 2>&1
  rc=$?
else
  SIM_SPERRE=()
  [ "$AKTION" = test ] && SIM_SPERRE=(lockf -k /tmp/kevcad-ipad-sim.lock)
  (cd app/KevCADCore && ${SIM_SPERRE[@]+"${SIM_SPERRE[@]}"} lockf -k /tmp/vb-xcodebuild.lock xcodebuild -scheme "$SCHEMA" -destination "$DEST" \
    -derivedDataPath "$DD" "${CACHE[@]}" ${EXTRA[@]+"${EXTRA[@]}"} "$AKTION") > "$LOG" 2>&1
  rc=$?
fi
dauer=$(($(date +%s) - start))
if [ $rc -ne 0 ]; then
  grep -E "error:" "$LOG" | sed -E 's#^.*/(app/)#\1#' | sort -u | head -40
  if grep -qE "OnDiskCAS|CAS cannot be initialized|Xcode build system has crashed" "$LOG"; then
    echo "Der Zwischenspeicher ($CAS) scheint beschädigt: Ordner umbenennen (Regel xcode-compilation-cache)."
  fi
  echo "==> fehlgeschlagen nach ${dauer} s (Ausgang $rc)"
else
  [ "$AKTION" = test ] && grep -E "Executed [0-9]+ tests|Test run with [0-9]+ tests|Test Case .* (passed|failed)" "$LOG" | tail -8
  if [ "$ART" = app ]; then
    rm -rf "$PAD_APP"
    cp -R "$DD/Build/Products/Debug-iphonesimulator/Kev CAD.app" "$PAD_APP" || { rc=1; echo "App fehlt im Bauordner"; }
    [ $rc -eq 0 ] && echo "==> App: $PAD_APP"
  fi
  [ $rc -eq 0 ] && echo "==> gut, ${dauer} s"
fi
exit $rc
