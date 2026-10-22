#!/usr/bin/env bash
# Aktualisiert die installierte App (Tools-Stapel) auf den aktuellen Stand von main.
#
# Wird von .githooks/post-commit und .githooks/post-merge im Hintergrund gestartet, sobald auf main ein neuer Stand
# entsteht (Commit, Merge, Pull). Gebaut wird in einer eigenen, sauberen Arbeitskopie von main
# (~/Library/Application Support/de.upvis.kevcad/build-src), damit halbfertige Änderungen im Repo nie installiert
# werden. Mehrere Auslöser hintereinander werden zu einem Lauf zusammengefasst.
#
# Gebaut wird auf dem Mac mini, wenn er erreichbar ist (tools/fern.sh release: Paket dort bauen, hier installieren),
# sonst hier wie bisher mit ./build.sh unter der gemeinsamen Sperre. Installieren, Neustart und Wiederherstellen laufen
# immer hier.
#
# Von Hand:  tools/auto-update.sh          Protokoll: ~/Library/Logs/Kev CAD/update.log
# Abschalten: KEVCAD_NO_AUTOUPDATE=1 beim Commit setzen oder `git config core.hooksPath ""`.
# Probe ohne Kevins App: KEVCAD_UPDATE_PROBE=<Ordner> (Arbeitskopie, Installation, Protokoll und Sperren dort, keine
# Mitteilungen, kein Neustart) und KEVCAD_UPDATE_REF=<Zweig> (Vorgabe main). Der Ordner muss neu oder leer sein; danach
# `git worktree remove --force <Ordner>/support/build-src`.
set -uo pipefail
# Git setzt in Hooks GIT_INDEX_FILE und Co.; die stören die Befehle in der eigenen Arbeitskopie.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO="$(dirname "$(cd "$(dirname "$0")/.." && git rev-parse --path-format=absolute --git-common-dir)")"
REF="${KEVCAD_UPDATE_REF:-main}"
PROBE="${KEVCAD_UPDATE_PROBE:-}"
if [ -n "$PROBE" ]; then
  mkdir -p "$PROBE"
  PROBE="$(cd "$PROBE" && pwd)"
  SUPPORT="$PROBE/support"
  LOGDIR="$PROBE/logs"
  export KEVCAD_INSTALL_DIR="$PROBE/Tools"
else
  SUPPORT="$HOME/Library/Application Support/de.upvis.kevcad"
  LOGDIR="$HOME/Library/Logs/Kev CAD"
fi
export KEVCAD_INSTALL_ROOT="$SUPPORT/install"
SRC="$SUPPORT/build-src"
LOG="$LOGDIR/update.log"
LOCK="$SUPPORT/update.lock"
PENDING="$SUPPORT/update.pending"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
# Fester Name auf dem Mac mini: Der Installationsbau findet dort seinen warmen Bauplatz wieder.
export KEVCAD_FERN_ID="${KEVCAD_FERN_ID:-release}"

mkdir -p "$SUPPORT" "$LOGDIR"

notify() {
  if [ -n "$PROBE" ]; then
    echo "$(date '+%H:%M:%S') Mitteilung (Probe, nicht gezeigt): $1: $2" >> "$LOG"
    return
  fi
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

APP="${KEVCAD_INSTALL_DIR:-$HOME/Applications/Tools}/Kev CAD.app"
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

# Bauen und installieren: auf dem Mac mini über tools/fern.sh release (Rückfall auf ./build.sh hier unter der Sperre
# macht fern.sh selbst), bei einem Stand ohne fern.sh wie bisher direkt hier.
build_and_install() {
  if [ -x "$SRC/tools/fern.sh" ]; then
    "$SRC/tools/fern.sh" release
  else
    wait_for_memory && lockf -k "$BUILD_LOCK" "$SRC/build.sh"
  fi
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
  changed=$(git -C "$REPO" diff --name-only "$old" "$REF")
  if echo "$changed" | grep -qE '^(app/|build\.sh$)'; then echo full
  elif echo "$changed" | grep -qE '^kernel/(src/|pyproject\.toml$|uv\.lock$)'; then echo full
  elif echo "$changed" | grep -qE '^(tools/capture/(Sources|scripts)/|tools/capture/Package\.swift$|fotomess/(src/|swift/|pyproject\.toml$|uv\.lock$))'; then echo full
  elif echo "$changed" | grep -qE '^skill/'; then echo skill
  else echo none
  fi
}

while :; do
  rm -f "$PENDING"
  COMMIT=$(git -C "$REPO" rev-parse --short "$REF")
  KIND=$(change_kind)
  if [ "$KIND" = "none" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') $REF $COMMIT: nur Doku/Tests geändert, kein Update nötig" >> "$LOG"
  elif [ "$KIND" = "skill" ]; then
    {
      echo "$(date '+%Y-%m-%d %H:%M:%S') $REF $COMMIT: nur der Skill geändert, kopiere ihn"
      if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
        git -C "$REPO" worktree add --detach "$SRC" "$REF"
      fi
      git -C "$SRC" checkout -q --detach "$REF" && git -C "$SRC" reset -q --hard "$REF" \
        && rsync -a --delete "$SRC/skill/" "$SUPPORT/install/skill/"
    } >> "$LOG" 2>&1
  else
    {
      echo
      echo "=== $(date '+%Y-%m-%d %H:%M:%S') Update auf $REF $COMMIT"
      if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
        git -C "$REPO" worktree add --detach "$SRC" "$REF"
      fi
      git -C "$SRC" checkout -q --detach "$REF" && git -C "$SRC" reset -q --hard "$REF" && build_and_install
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
