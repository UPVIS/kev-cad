#!/usr/bin/env bash
# Aktualisiert die installierte App (Tools-Stapel) auf den aktuellen Stand von main.
#
# Wird von .githooks/post-commit und .githooks/post-merge im Hintergrund gestartet, sobald auf main ein neuer Stand
# entsteht (Commit, Merge, Pull). Gebaut wird in einer eigenen, sauberen Arbeitskopie von main
# (~/Library/Application Support/de.upvis.kevcad/build-src), damit halbfertige Änderungen im Repo nie installiert
# werden. Mehrere Auslöser hintereinander werden zu einem Lauf zusammengefasst.
#
# Von Hand:  tools/auto-update.sh          Protokoll: ~/Library/Logs/Kev CAD/update.log
# Abschalten: KEVCAD_NO_AUTOUPDATE=1 beim Commit setzen oder `git config core.hooksPath ""`.
set -uo pipefail
# Git setzt in Hooks GIT_INDEX_FILE und Co.; die stören die Befehle in der eigenen Arbeitskopie.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO="$(dirname "$(cd "$(dirname "$0")/.." && git rev-parse --path-format=absolute --git-common-dir)")"
SUPPORT="$HOME/Library/Application Support/de.upvis.kevcad"
SRC="$SUPPORT/build-src"
LOGDIR="$HOME/Library/Logs/Kev CAD"
LOG="$LOGDIR/update.log"
LOCK="$SUPPORT/update.lock"
PENDING="$SUPPORT/update.pending"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

mkdir -p "$SUPPORT" "$LOGDIR"

notify() {
  osascript -e "display notification \"$2\" with title \"$1\"" >/dev/null 2>&1 || true
}

APP="$HOME/Applications/Tools/Kev CAD.app"
BUNDLE_ID="de.upvis.kevcad"

app_running() { pgrep -f "$APP/Contents/MacOS/Kev CAD" >/dev/null; }

# Läuft die App, wird sie beendet (sie merkt sich dabei Projekt und Ansicht) und gleich wieder geöffnet; dank
# relaunch.request öffnet die neue Version dasselbe Projekt mit derselben Kamera.
relaunch() {
  if ! app_running; then
    notify "Kev CAD aktualisiert" "Stand $1 ist installiert."
    return
  fi
  local front
  front=$(osascript -e 'tell application "System Events" to get bundle identifier of first process whose frontmost is true' 2>/dev/null)
  touch "$SUPPORT/relaunch.request"
  osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1
  for _ in $(seq 1 40); do app_running || break; sleep 0.5; done
  if app_running; then
    rm -f "$SUPPORT/relaunch.request"
    notify "Kev CAD aktualisiert" "Stand $1 ist installiert. Bitte Kev CAD neu starten."
    return
  fi
  if [ "$front" = "$BUNDLE_ID" ]; then open "$APP"; else open -g "$APP"; fi
  echo "$(date '+%H:%M:%S') App neu gestartet (vorher vorne: ${front:-?})" >> "$LOG"
  notify "Kev CAD aktualisiert" "Stand $1 läuft, dein Projekt ist wieder offen."
}

# Läuft schon ein Update, nur vormerken; der laufende Durchgang baut danach noch einmal.
if ! mkdir "$LOCK" 2>/dev/null; then
  # verwaiste Sperre (älter als 30 min) aufräumen
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null || { touch "$PENDING"; exit 0; }
  else
    touch "$PENDING"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

while :; do
  rm -f "$PENDING"
  COMMIT=$(git -C "$REPO" rev-parse --short main)
  {
    echo
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') Update auf main $COMMIT"
    if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
      git -C "$REPO" worktree add --detach "$SRC" main
    fi
    git -C "$SRC" checkout -q --detach main && git -C "$SRC" reset -q --hard main && "$SRC/build.sh"
  } >> "$LOG" 2>&1
  rc=$?
  if [ $rc -eq 0 ]; then
    relaunch "$COMMIT"
  else
    notify "Kev CAD: Update fehlgeschlagen" "Stand $COMMIT, Protokoll: ~/Library/Logs/Kev CAD/update.log"
  fi
  [ -f "$PENDING" ] || break
done
