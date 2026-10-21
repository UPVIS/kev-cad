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
    if pgrep -f "Applications/Tools/Kev CAD.app/Contents/MacOS" >/dev/null; then
      notify "Kev CAD aktualisiert" "Stand $COMMIT ist installiert. Neu starten, um ihn zu nutzen."
    else
      notify "Kev CAD aktualisiert" "Stand $COMMIT ist installiert."
    fi
  else
    notify "Kev CAD: Update fehlgeschlagen" "Stand $COMMIT, Protokoll: ~/Library/Logs/Kev CAD/update.log"
  fi
  [ -f "$PENDING" ] || break
done
