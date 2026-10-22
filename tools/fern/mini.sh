#!/bin/bash
# Gegenstück von tools/fern.sh auf dem Mac mini. Läuft immer aus dem Schnappschuss des Auftrags
# (~/KevCAD-Bau/auftrag/<id>/tools/fern/mini.sh) und passt damit zu genau dem Stand, den es baut.
#
#   bash tools/fern/mini.sh <id> tests|testbau|bundle [name]    (startet tools/fern.sh)
#   bash tools/fern/mini.sh status                               Plätze, Schlange, Speicher
#
# Ordner auf dem Mini, alle unter ~/KevCAD-Bau (Tessera und andere Projekte haben eigene, die hier nie berührt werden):
#   auftrag/<id>   Schnappschuss eines Auftrags, von fern.sh hochgeladen (rsync --link-dest auf quelle/<Kürzel>)
#   quelle/<K>     letzter Schnappschuss je Kürzel, Grundlage für den nächsten Abgleich
#   platz/a, b     feste Bäume der beiden Bauplätze mit warmem Bauordner (.build, build/DerivedData, kernel/.venv)
#   ergebnis/<id>  was fern.sh danach abholt (Test-App, Paket)
#   sperren/       Plätze a, b, test und die Schlange; protokoll/auftraege.tsv (je Auftrag eine Zeile) und
#                  protokoll/mini.log (Ablauf, auch nach Abriss der Verbindung); cache/uv; werkzeuge/xcodegen
#
# Plätze: Ein Auftrag nimmt einen freien Bauplatz, zuerst den, an dem sein Kürzel zuletzt war, und spiegelt seinen
# Schnappschuss nach Inhalt hinein: Unveränderte Dateien behalten ihren Zeitstempel, also bleibt der Bauordner warm, auch
# wenn vorher ein anderer Agent dort gebaut hat. Den zweiten Bauplatz gibt es nur bei mindestens 25 % freiem Speicher.
# `tests` baut die Tests im Bauplatz und nimmt für den Lauf zusätzlich den Testplatz: Die Kernel-Tests nutzen feste Ports
# (47996 bis 47999) und feste Sockets unter /tmp, zwei Läufe zugleich kämen sich in die Quere. Ein Bau im anderen Platz
# läuft daneben weiter. Gewartet wird in einer Schlange nach Ankunft, jede Platzvergabe unter einer kurzen Sperre (lockf).
#
# Wache: fern.sh schreibt alle 5 s eine Zeile in stdin. Kommt 60 s keine oder endet stdin (fern.sh beendet, Verbindung
# weg), bricht der Auftrag ab und gibt seine Plätze frei. KEVCAD_FERN_WACHE=0 schaltet das ab (Aufruf von Hand).
# Frist für einen Lauf: KEVCAD_FERN_FRIST Sekunden (3600).
#
# Ausgang: der des Auftrags; 86 heißt „auf dem Mini nicht möglich“ (Werkzeug fehlt), fern.sh baut dann lokal.
set -uo pipefail

ROOT="$HOME/KevCAD-Bau"
LOCKS="$ROOT/sperren"
QUEUE="$LOCKS/schlange"
MUTEX="$LOCKS/.vergabe"
TREES="$ROOT/platz"
RESULTS="$ROOT/ergebnis"
JOBS="$ROOT/auftrag"
SOURCES="$ROOT/quelle"
HOMES="$ROOT/heimat"
RUNNING="$ROOT/laufend"
LOGS="$ROOT/protokoll"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SNAP="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="$ROOT/werkzeuge/xcodegen/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
export UV_CACHE_DIR="$ROOT/cache/uv"
mkdir -p "$QUEUE/bau" "$QUEUE/test" "$TREES" "$RESULTS" "$JOBS" "$SOURCES" "$HOMES" "$RUNNING" "$LOGS"

alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
mem_free() { memory_pressure 2>/dev/null | tail -1 | grep -oE '[0-9]+' | tail -1; }
# Ablauf je Auftrag in protokoll/mini.log, auch wenn die Verbindung weg ist und niemand mehr die Ausgabe liest.
note() { echo "$(date '+%Y-%m-%d %H:%M:%S') ${JOB_ID:-?} [$$] $*" >> "$LOGS/mini.log" 2>/dev/null; }

# Ist ein Platz frei? Verwaiste Sperren (Halter und seine Prozessgruppe tot) werden dabei entfernt. Nur unter MUTEX.
slot_free() {
  local d="$LOCKS/$1" p g
  [ -d "$d" ] || return 0
  p=$(cat "$d/pid" 2>/dev/null); g=$(cat "$d/gruppe" 2>/dev/null)
  alive "$p" && return 1
  [ -n "$g" ] && kill -0 -- "-$g" 2>/dev/null && return 1
  rm -rf "$d"
  return 0
}

slot_info() {
  local s d out=""
  for s in a b test; do
    d="$LOCKS/$s"
    if [ -d "$d" ] && alive "$(cat "$d/pid" 2>/dev/null)"; then
      out="$out $s: $(cat "$d/wer" 2>/dev/null) seit $(( $(date +%s) - $(cat "$d/seit" 2>/dev/null || date +%s) )) s;"
    else
      out="$out $s: frei;"
    fi
  done
  printf '%s' "${out# }"
}

# --- Teilbefehle, die mini.sh unter MUTEX von sich selbst aufruft -------------------------------------------------
case "${1:-}" in
  _ticket)
    # $2 Halter-pid, $3 bau|test: Marke in der Schlange ziehen (fortlaufende Nummer)
    n=$(( $(cat "$LOCKS/zaehler" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$LOCKS/zaehler"
    t="$QUEUE/$3/$(printf '%09d' "$n")"
    echo "$2" > "$t"
    echo "$t"
    exit 0
    ;;
  _take)
    # $2 Halter-pid, $3 Marke, $4 bau|test, $5 bevorzugter Platz: nimmt einen Platz, wenn die Marke vorn steht
    holder=$2; ticket=$3; kind=$4; pref=${5:-}
    for t in "$QUEUE/$kind"/*; do
      [ -e "$t" ] || continue
      alive "$(cat "$t" 2>/dev/null)" || rm -f "$t"
    done
    head=$(ls "$QUEUE/$kind" 2>/dev/null | sort | head -1)
    [ "$QUEUE/$kind/$head" = "$ticket" ] || exit 1
    if [ "$kind" = test ]; then candidates="test"; else candidates="$pref a b"; fi
    for s in $candidates; do
      case "$s" in a|b|test) ;; *) continue ;; esac
      slot_free "$s" || continue
      if [ "$kind" = bau ]; then
        other=a; [ "$s" = a ] && other=b
        if ! slot_free "$other"; then
          free=$(mem_free)
          [ -n "$free" ] && [ "$free" -lt 25 ] && continue
        fi
      fi
      mkdir "$LOCKS/$s" 2>/dev/null || continue
      echo "$holder" > "$LOCKS/$s/pid"
      echo "${KEVCAD_FERN_ID:-?} $KIND" > "$LOCKS/$s/wer"
      date +%s > "$LOCKS/$s/seit"
      rm -f "$ticket"
      echo "$s"
      exit 0
    done
    exit 1
    ;;
  status)
    echo "Plätze: $(slot_info)"
    echo "Schlange: Bau $(ls "$QUEUE/bau" | wc -l | tr -d ' '), Test $(ls "$QUEUE/test" | wc -l | tr -d ' ')"
    memory_pressure | tail -1
    df -h "$HOME" | tail -1 | awk '{print "Platte: " $4 " frei"}'
    exit 0
    ;;
esac

# --- Auftrag ------------------------------------------------------------------------------------------------------
JOB_ID=${1:?Auftrags-ID fehlt}
KIND=${2:?Art fehlt (tests, testbau, bundle)}
NAME=${3:-}
ID=${KEVCAD_FERN_ID:?KEVCAD_FERN_ID fehlt}
FRIST=${KEVCAD_FERN_FRIST:-3600}
export KIND KEVCAD_FERN_ID
case "$KIND" in tests|testbau|bundle) ;; *) echo "mini.sh: unbekannte Art $KIND"; exit 2 ;; esac

HELD=""; TICKET=""; JOB_PID=""; TIMER_PID=""; WATCH_PID=""; WAITED=0; T_START=$(date +%s); FINISHING=0

finish() {
  local rc=$1
  [ "$FINISHING" = 1 ] && return
  FINISHING=1
  trap '' TERM INT HUP PIPE
  # Ab hier nichts mehr an fern.sh: Ist die Verbindung weg, hält bash den Text einer gescheiterten Ausgabe im Puffer und
  # gibt ihn an die nächste Befehlsersetzung weiter (so blieb beim ersten Abriss-Versuch ein Platz belegt).
  exec >>"$LOGS/mini.log" 2>&1
  note "Ende $rc (Plätze:${HELD:- keine})"
  [ -n "$JOB_PID" ] && kill -TERM -- "-$JOB_PID" 2>/dev/null
  [ -n "$TIMER_PID" ] && kill -TERM -- "-$TIMER_PID" 2>/dev/null
  [ -n "$WATCH_PID" ] && kill "$WATCH_PID" 2>/dev/null
  local s holder
  for s in $HELD; do
    holder=""; read -r holder < "$LOCKS/$s/pid" 2>/dev/null
    if [ "$holder" = "$$" ]; then rm -rf "$LOCKS/$s"; else note "Platz $s gehört nicht mehr mir ($holder)"; fi
  done
  [ -n "$TICKET" ] && rm -f "$TICKET"
  rm -f "$RUNNING/$JOB_ID"
  # Ohne Erfolg gibt es nichts abzuholen (fern.sh ist dann im Rückfall oder schon weg).
  [ "$rc" = 0 ] || rm -rf "$RESULTS/$JOB_ID"
  # Der Schnappschuss wird die Grundlage des nächsten Abgleichs dieses Kürzels (fern.sh: rsync --link-dest).
  # Unter der Vergabesperre, weil zwei Aufträge desselben Kürzels zugleich enden können.
  if [ -d "$SNAP" ]; then
    lockf -k -t 30 "$MUTEX" /bin/bash -c 'rm -rf "$2.alt"; if [ -d "$2" ]; then mv "$2" "$2.alt"; fi
      mv "$1" "$2" && rm -rf "$2.alt"' _ "$SNAP" "$SOURCES/$ID" || rm -rf "$SNAP"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ID" "$KIND" "${NAME:--}" "$rc" "$WAITED" \
    "$(( $(date +%s) - T_START ))" >> "$LOGS/auftraege.tsv"
  [ "$rc" = 255 ] && rc=1
  exit "$rc"
}
# Abbruch (Wache, Frist, kill) und abgerissene Verbindung (SIGPIPE beim Schreiben): aufräumen und Plätze freigeben.
# Als Falle statt ignoriert, damit die Kinder (xcodebuild, swift, pytest) SIGPIPE wie gewohnt bekommen.
on_signal() {
  trap '' PIPE
  [ "$1" = PIPE ] || echo "==> Mini: Auftrag abgebrochen ($1)" 2>/dev/null
  exec >>"$LOGS/mini.log" 2>&1
  note "Signal $1"
  finish "$2"
}
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT
trap 'on_signal HUP 129' HUP
trap 'on_signal PIPE 141' PIPE

# Werkzeuge prüfen, bevor ein Platz belegt wird
if ! command -v uv >/dev/null; then
  echo "==> Mini: uv fehlt (~/.local/bin/uv); einrichten mit tools/fern.sh einrichten"; finish 86
fi
if [ "$KIND" != tests ]; then
  if ! command -v xcodegen >/dev/null; then
    echo "==> Mini: xcodegen fehlt (~/KevCAD-Bau/werkzeuge); einrichten mit tools/fern.sh einrichten"; finish 86
  fi
  if ! xcrun metal --version >/dev/null 2>&1; then
    echo "==> Mini: Metal-Toolchain fehlt (nach einem Xcode-Update?); nachholen mit tools/fern.sh einrichten"; finish 86
  fi
fi

# Alte Reste aufräumen: Schnappschüsse und Ergebnisse abgebrochener Aufträge, Grundlagen lange nicht benutzter Kürzel.
# Nach ctime, nicht mtime: rsync übernimmt die mtime des Worktrees, ein frischer Schnappschuss kann also „alt“ aussehen.
find "$JOBS" "$RESULTS" -mindepth 1 -maxdepth 1 -ctime +1 -not -path "$SNAP" -exec rm -rf {} + 2>/dev/null
find "$SOURCES" -mindepth 1 -maxdepth 1 -ctime +14 -exec rm -rf {} + 2>/dev/null

if [ "${KEVCAD_FERN_WACHE:-1}" != 0 ]; then
  exec 3<&0
  (
    trap '' PIPE
    while IFS= read -r -t 60 _ <&3; do :; done
    note "Wache: kein Herzschlag mehr"
    echo "==> Mini: fern.sh meldet sich nicht mehr (beendet oder Verbindung weg), breche ab" >&2
    kill -TERM $$ 2>/dev/null
  ) &
  WATCH_PID=$!
  exec 3<&-
fi
exec </dev/null

# Wartet auf einen Platz der Art $1 (bau|test) und setzt SLOT.
acquire() {
  local kind=$1 pref="" t0 s next=0
  [ "$kind" = bau ] && pref=$(cat "$HOMES/$ID" 2>/dev/null)
  TICKET=$(lockf -k "$MUTEX" /bin/bash "$SELF" _ticket "$$" "$kind")
  t0=$(date +%s)
  while :; do
    if s=$(lockf -k "$MUTEX" /bin/bash "$SELF" _take "$$" "$TICKET" "$kind" "$pref"); then
      SLOT=$s; HELD="$HELD $s"; TICKET=""
      WAITED=$(( WAITED + $(date +%s) - t0 ))
      return 0
    fi
    if [ $(( $(date +%s) - t0 )) -ge $next ]; then
      echo "==> Mini: warte auf einen Platz für $kind ($(slot_info))"
      next=$(( next + 60 ))
    fi
    sleep 2
  done
}

# Führt "$@" in eigener Prozessgruppe aus (abbrechbar samt Kindern), mit Frist.
run() {
  local rc
  set -m
  "$@" &
  JOB_PID=$!
  ( sleep "$FRIST"; echo "==> Mini: Frist von $FRIST s überschritten, breche ab"; kill -TERM -- "-$JOB_PID" 2>/dev/null ) &
  TIMER_PID=$!
  set +m
  local s
  for s in $HELD; do echo "$JOB_PID" > "$LOCKS/$s/gruppe"; done
  wait "$JOB_PID"; rc=$?
  note "Lauf $1 endet mit $rc"
  JOB_PID=""
  kill -TERM -- "-$TIMER_PID" 2>/dev/null; TIMER_PID=""
  return $rc
}

# Spiegelt den Schnappschuss nach Inhalt in den Baum des Platzes: ohne Zeitstempel (-c statt -t), damit unveränderte
# Dateien ihren alten behalten und geänderte einen neuen bekommen. Bauordner und Umgebungen stehen in ausschluss.txt und
# bleiben deshalb stehen.
sync_tree() {
  TREE="$TREES/$SLOT"
  mkdir -p "$TREE"
  rsync -rlpc --delete --exclude-from="$SNAP/tools/fern/ausschluss.txt" "$SNAP/" "$TREE/" || {
    echo "==> Mini: Spiegeln in den Platz $SLOT fehlgeschlagen"; finish 1; }
  echo "$SLOT" > "$HOMES/$ID"
  cd "$TREE" || finish 1
}

echo "$$" > "$RUNNING/$JOB_ID"
note "Beginn $KIND ${NAME:-} für $ID"
acquire bau
sync_tree
note "Platz $SLOT"
echo "==> Mini: Platz $SLOT ($(sysctl -n hw.ncpu) Kerne, $(mem_free) % Speicher frei)"
T_RUN=$(date +%s)
mkdir -p "$RESULTS/$JOB_ID"

case "$KIND" in
  tests)
    LOG="$TREE/build/fern-tests-bau.log"
    mkdir -p "$TREE/build"
    echo "==> Mini: Tests bauen"
    run /bin/bash -c 'cd kernel && uv sync -q && cd ../app/KevCADCore && swift build --build-tests' > "$LOG" 2>&1
    rc=$?
    if [ $rc -ne 0 ]; then
      grep -E "error:" "$LOG" | head -30; tail -5 "$LOG"
      echo "==> Mini: Bauen der Tests fehlgeschlagen ($rc)"; finish $rc
    fi
    tail -1 "$LOG"
    acquire test
    echo "==> Mini: Tests laufen (Testplatz)"
    run ./build.sh --core-tests
    rc=$?
    ;;
  testbau)
    run ./build.sh --test ${NAME:+"$NAME"}
    rc=$?
    APP="Kev CAD Test${NAME:+ $NAME}"
    # Unter festem Namen ohne Leerzeichen ablegen: rsync von openrsync kann entfernte Pfade nicht schützen (kein -s).
    if [ $rc -eq 0 ]; then
      cp -c -R "build/$APP.app" "$RESULTS/$JOB_ID/app.app" 2>/dev/null || cp -R "build/$APP.app" "$RESULTS/$JOB_ID/app.app" \
        || rc=1
    fi
    ;;
  bundle)
    run ./build.sh --bundle
    rc=$?
    if [ $rc -eq 0 ]; then
      cp -c -R build/bundle "$RESULTS/$JOB_ID/bundle" 2>/dev/null || cp -R build/bundle "$RESULTS/$JOB_ID/bundle" || rc=1
    fi
    ;;
esac
echo "==> Mini: Plätze${HELD}, gewartet $WAITED s, Lauf $(( $(date +%s) - T_RUN )) s, Ausgang $rc"
finish $rc
