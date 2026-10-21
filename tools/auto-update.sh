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

# Gemeinsame Sperre mit VoiceBridge: auf dem 16-GB-Mac höchstens ein xcodebuild zur selben Zeit (der Mac fror am
# 20.10.2026 unter Speicherdruck ein). Vor dem Bauen warten, bis mindestens 25 % Speicher frei sind (höchstens 10 min).
BUILD_LOCK="/tmp/vb-xcodebuild.lock"
wait_for_memory() {
  local i free
  for i in $(seq 1 60); do
    free=$(memory_pressure 2>/dev/null | tail -1 | grep -oE '[0-9]+' | tail -1)
    [ -z "$free" ] || [ "$free" -ge 25 ] && return 0
    [ "$i" -eq 1 ] && echo "Warte auf freien Speicher ($free % frei)"
    sleep 10
  done
  return 0
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

# Was hat sich seit der installierten Version geändert? app (App neu bauen und neu starten), kernel (Kernel neu
# installieren und neu starten), skill (nur kopieren), sonst nichts (reine Doku, Tests, Beispiele).
change_kind() {
  local old changed
  old=$(cut -d' ' -f1 "$SUPPORT/install/VERSION" 2>/dev/null | tr -d '+')
  [ -n "$old" ] && git -C "$REPO" cat-file -e "$old^{commit}" 2>/dev/null || { echo full; return; }
  changed=$(git -C "$REPO" diff --name-only "$old" main)
  if echo "$changed" | grep -qE '^(app/|build\.sh$)'; then echo full
  elif echo "$changed" | grep -qE '^kernel/(src/|pyproject\.toml$|uv\.lock$)'; then echo full
  elif echo "$changed" | grep -qE '^skill/'; then echo skill
  else echo none
  fi
}

while :; do
  rm -f "$PENDING"
  COMMIT=$(git -C "$REPO" rev-parse --short main)
  KIND=$(change_kind)
  if [ "$KIND" = "none" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') main $COMMIT: nur Doku/Tests geändert, kein Update nötig" >> "$LOG"
  elif [ "$KIND" = "skill" ]; then
    {
      echo "$(date '+%Y-%m-%d %H:%M:%S') main $COMMIT: nur der Skill geändert, kopiere ihn"
      if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
        git -C "$REPO" worktree add --detach "$SRC" main
      fi
      git -C "$SRC" checkout -q --detach main && git -C "$SRC" reset -q --hard main \
        && rsync -a --delete "$SRC/skill/" "$SUPPORT/install/skill/"
    } >> "$LOG" 2>&1
  else
    {
      echo
      echo "=== $(date '+%Y-%m-%d %H:%M:%S') Update auf main $COMMIT"
      if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
        git -C "$REPO" worktree add --detach "$SRC" main
      fi
      git -C "$SRC" checkout -q --detach main && git -C "$SRC" reset -q --hard main && wait_for_memory \
        && lockf -k "$BUILD_LOCK" "$SRC/build.sh"
    } >> "$LOG" 2>&1
    rc=$?
    if [ $rc -eq 0 ]; then
      relaunch "$COMMIT"
    else
      notify "Kev CAD: Update fehlgeschlagen" "Stand $COMMIT, Protokoll: ~/Library/Logs/Kev CAD/update.log"
    fi
  fi
  [ -f "$PENDING" ] || break
done
