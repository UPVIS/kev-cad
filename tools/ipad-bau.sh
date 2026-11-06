#!/bin/bash
# iPad-Bauten von Kev CAD (PLAN-IPAD.md). Bis tools/fern.sh die iPad-Ziele selbst baut, ist dies der Weg, vor einem Commit
# auch die iPad-Seite zu übersetzen (CLAUDE.md, „Mac und iPad“).
#
#   tools/ipad-bau.sh kern            KevCADCore mit KevCADWire und Viewport für den iPad-Simulator übersetzen
#   tools/ipad-bau.sh kern geraet     dasselbe für ein echtes iPad (ohne Signatur)
#   tools/ipad-bau.sh test            Tests des Kerns im iPad-Simulator (ohne Simulatorfenster, Schema KevCADCore-Package)
#
# Läuft hier unter der gemeinsamen Sperre /tmp/vb-xcodebuild.lock und wartet vorher bis zu 10 Minuten auf 25 % freien
# Speicher. Bauordner und Xcode-Zwischenspeicher liegen auf UPVIS ULTRA (die Systemplatte ist knapp), ohne die Platte unter
# build/ipad. Protokoll: build/ipad-<art>-<ziel>.log; Ausgang wie xcodebuild.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

ART=${1:-}
ZIEL=${2:-simulator}
SCHEMA=KevCADCore
AKTION=build
case "$ART" in
  kern) ;;
  test)
    # Simulator nur über xcodebuild starten: Er bootet ohne Fenster, Kevins Bildschirm bleibt frei
    SCHEMA=KevCADCore-Package
    AKTION=test
    ZIEL=test ;;
  *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
case "$ZIEL" in
  simulator) DEST='generic/platform=iOS Simulator'; EXTRA=() ;;
  geraet) DEST='generic/platform=iOS'; EXTRA=(CODE_SIGNING_ALLOWED=NO) ;;
  test) DEST="platform=iOS Simulator,name=${KEVCAD_IPAD_SIM:-iPad Pro 13-inch (M5)}"; EXTRA=() ;;
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

start=$(date +%s)
echo "==> $ART für iPad ($ZIEL), Protokoll $LOG"
(cd app/KevCADCore && lockf -k /tmp/vb-xcodebuild.lock xcodebuild -scheme "$SCHEMA" -destination "$DEST" \
  -derivedDataPath "$DD" "${CACHE[@]}" ${EXTRA[@]+"${EXTRA[@]}"} "$AKTION") > "$LOG" 2>&1
rc=$?
dauer=$(($(date +%s) - start))
if [ $rc -ne 0 ]; then
  grep -E "error:" "$LOG" | sed -E 's#^.*/(app/)#\1#' | sort -u | head -40
  if grep -qE "OnDiskCAS|CAS cannot be initialized|Xcode build system has crashed" "$LOG"; then
    echo "Der Zwischenspeicher ($CAS) scheint beschädigt: Ordner umbenennen (Regel xcode-compilation-cache)."
  fi
  echo "==> fehlgeschlagen nach ${dauer} s (Ausgang $rc)"
else
  [ "$AKTION" = test ] && grep -E "Executed [0-9]+ tests|Test run with [0-9]+ tests" "$LOG" | tail -2
  echo "==> gut, ${dauer} s"
fi
exit $rc
