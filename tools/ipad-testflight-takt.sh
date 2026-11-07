#!/usr/bin/env bash
# iPad-Builds im Takt von main (PLAN-IPAD.md, I-9). Nach jedem Update der Mac-App startet tools/auto-update.sh dieses
# Skript im Hintergrund. Hat sich seit dem letzten TestFlight-Build etwas an der App geändert (app/, Package.swift), baut
# es aus einer eigenen, sauberen Arbeitskopie von main einen neuen Build und lädt ihn hoch (tools/ipad-testflight.sh),
# höchstens einen je Stunde; was in der Stunde dazukommt, geht mit dem nächsten Build raus. TestFlight spielt ihn auf
# Kevins iPad, wenn dort „Automatische Updates“ an ist.
#
#   tools/ipad-testflight-takt.sh            wie aus dem Update: wartet die Stunde seit dem letzten Build ab
#   tools/ipad-testflight-takt.sh --sofort   ohne Wartezeit (nur von Hand)
#
# Abschalten: KEVCAD_NO_TESTFLIGHT=1 beim Commit oder die Datei testflight.aus in
# ~/Library/Application Support/de.upvis.kevcad. Dort steht auch der letzte Build (testflight.stand: Commit, Nummer,
# Zeit; schreibt tools/ipad-testflight.sh). Protokoll: ~/Library/Logs/Kev CAD/update.log, Zeilen mit „iPad:“.
# Arbeitskopie und Bauordner liegen auf UPVIS ULTRA (_cache/kevcad-ipad/takt); fehlt die Platte, fällt der Build aus.
# Probe ohne Upload: KEVCAD_TAKT_PROBE=<Ordner> (Ablage, Protokoll und Arbeitskopie dort, keine Mitteilungen),
# KEVCAD_TAKT_BEFEHL=<Befehl> statt des Uploads (läuft in der Arbeitskopie, KEVCAD_PAD_STAND zeigt auf den Stand) und
# KEVCAD_TAKT_S=<Sekunden> statt der Stunde.
set -uo pipefail
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Repo: aus dem Update übergeben (es startet eine Kopie dieses Skripts), sonst das, in dem das Skript liegt
REPO="${KEVCAD_REPO:-$(dirname "$(cd "$(dirname "$0")/.." && git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")}"
REF=main
PROBE="${KEVCAD_TAKT_PROBE:-}"
if [ -n "$PROBE" ]; then
  mkdir -p "$PROBE"
  PROBE="$(cd "$PROBE" && pwd)"
  SUPPORT="$PROBE/support"
  LOG="$PROBE/update.log"
  BASIS="$PROBE/takt"
else
  SUPPORT="$HOME/Library/Application Support/de.upvis.kevcad"
  LOG="$HOME/Library/Logs/Kev CAD/update.log"
  BASIS="/Volumes/UPVIS ULTRA/_cache/kevcad-ipad/takt"
fi
SRC="$BASIS/src"
STAND="$SUPPORT/testflight.stand"
VERSUCH="$SUPPORT/testflight.versuch"
SPERRE="$SUPPORT/testflight.lock"
VORGEMERKT="$SUPPORT/testflight.pending"
TAKT_S="${KEVCAD_TAKT_S:-3600}"
SOFORT=0
[ "${1:-}" = "--sofort" ] && SOFORT=1

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') iPad: $*" >> "$LOG"; }
melden() {
  if [ -n "$PROBE" ]; then log "Mitteilung (Probe, nicht gezeigt): $1"; return; fi
  osascript -e "display notification \"$1\" with title \"Kev CAD fürs iPad\"" >/dev/null 2>&1 || true
}

[ "${KEVCAD_NO_TESTFLIGHT:-0}" = "1" ] && exit 0
[ -f "$SUPPORT/testflight.aus" ] && exit 0
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "Kein Repo: $REPO" >&2; exit 1; }
mkdir -p "$SUPPORT" "$(dirname "$LOG")"

# Höchstens ein Lauf zur selben Zeit; ein weiterer Auslöser merkt nur vor, der laufende nimmt danach den neuesten Stand
if ! mkdir "$SPERRE" 2>/dev/null; then
  pid=$(cat "$SPERRE/pid" 2>/dev/null)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    touch "$VORGEMERKT"
    exit 0
  fi
  rm -rf "$SPERRE"
  mkdir "$SPERRE" 2>/dev/null || { touch "$VORGEMERKT"; exit 0; }
fi
echo $$ > "$SPERRE/pid"
trap 'rm -rf "$SPERRE"' EXIT

# 0, wenn sich die App zwischen zwei Ständen geändert hat; ein unbekannter alter Stand zählt als Änderung
app_geaendert() {
  [ -n "$1" ] && git -C "$REPO" cat-file -e "$1^{commit}" 2>/dev/null || return 0
  ! git -C "$REPO" diff --quiet "$1" "$2" -- app Package.swift
}

while :; do
  rm -f "$VORGEMERKT"
  ZIEL=$(git -C "$REPO" rev-parse --short "$REF") || exit 1
  LETZTER=""
  ZULETZT=0
  [ -f "$STAND" ] && read -r LETZTER _ ZULETZT < "$STAND"
  if ! app_geaendert "$LETZTER" "$ZIEL"; then
    [ -f "$VORGEMERKT" ] && continue
    exit 0
  fi
  # Takt: frühestens eine Stunde nach dem letzten Build oder Versuch, dann mit dem dann neuesten Stand
  VERSUCHT=0
  [ -f "$VERSUCH" ] && read -r VERSUCHT < "$VERSUCH"
  [ "${VERSUCHT:-0}" -gt "${ZULETZT:-0}" ] && ZULETZT=$VERSUCHT
  WARTEN=$(( ${ZULETZT:-0} + TAKT_S - $(date +%s) ))
  if [ "$SOFORT" = "0" ] && [ "$WARTEN" -gt 0 ]; then
    log "Stand $ZIEL wartet auf den Takt, Build gegen $(date -r $(( $(date +%s) + WARTEN )) +%H:%M)"
    sleep "$WARTEN"
    continue
  fi
  SOFORT=0
  if [ -z "$PROBE" ] && [ ! -d "/Volumes/UPVIS ULTRA/_cache" ]; then
    log "UPVIS ULTRA fehlt, kein Build für Stand $ZIEL"
    exit 0
  fi
  date +%s > "$VERSUCH"
  # Eigene, saubere Arbeitskopie: Die des Mac-Updates springt währenddessen auf neue Stände
  if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
    mkdir -p "$BASIS"
    git -C "$REPO" worktree prune
    git -C "$REPO" worktree add --detach "$SRC" "$ZIEL" >> "$LOG" 2>&1 \
      || { log "Arbeitskopie $SRC ließ sich nicht anlegen"; exit 1; }
  fi
  git -C "$SRC" checkout -q --detach "$ZIEL" && git -C "$SRC" reset -q --hard "$ZIEL" \
    || { log "Arbeitskopie ließ sich nicht auf $ZIEL setzen"; exit 1; }
  # Speicher wie beim Mac-Update: bis zu 10 Minuten auf 25 % frei warten
  for _ in $(seq 1 60); do
    frei=$(memory_pressure 2>/dev/null | tail -1 | grep -oE '[0-9]+' | tail -1)
    { [ -z "$frei" ] || [ "$frei" -ge 25 ]; } && break
    sleep 10
  done
  log "Build für Stand $ZIEL startet"
  if [ -n "${KEVCAD_TAKT_BEFEHL:-}" ]; then
    AUSGABE=$(cd "$SRC" && KEVCAD_PAD_STAND="$STAND" bash -c "$KEVCAD_TAKT_BEFEHL" 2>&1)
  else
    AUSGABE=$(KEVCAD_PAD_PLATZ=takt KEVCAD_PAD_STAND="$STAND" "$SRC/tools/ipad-testflight.sh" 2>&1)
  fi
  rc=$?
  printf '%s\n' "$AUSGABE" | sed 's/^/    /' >> "$LOG"
  if [ $rc -ne 0 ]; then
    log "Build für Stand $ZIEL gescheitert (Ausgang $rc)"
    melden "Build für Stand $ZIEL gescheitert, Protokoll: ~/Library/Logs/Kev CAD/update.log"
    exit "$rc"
  fi
  log "Stand $ZIEL hochgeladen ($(printf '%s\n' "$AUSGABE" | grep -oE 'Build [0-9]+' | tail -1)), TestFlight verarbeitet ihn"
done
