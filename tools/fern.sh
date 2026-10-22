#!/bin/bash
# Kev CAD auf dem Mac mini bauen und testen statt auf Kevins MacBook.
#
# Kevin am 22.10.2026: „Du hast die Möglichkeit, auch den Mac mini als Bildrechner und Testrechner zu nutzen. Da kannst du
# auch Bauplätze drauf verwenden, wenn das den Hauptrechner entlastet und den gesamten Prozess beschleunigt.“ Hier bleibt
# nur, was fast nichts kostet: das App-Symbol erzeugen (dem Mini fehlt rsvg-convert), die Quellen spiegeln, Ergebnisse
# zurückholen und installieren. Vorbild ist tools/agenten/fern.sh von Tessera, deutlich einfacher.
#
# Aufruf aus einem Worktree (oder dem Repo):
#   tools/fern.sh tests [kürzel]    ./build.sh --core-tests auf dem Mini (swift test und pytest), Ausgabe live, Ausgang wie dort
#   tools/fern.sh testbau [name]    Testvariante „Kev CAD Test[ name]“ auf dem Mini bauen und nach build/ holen. Die App
#                                   startet den Kernel dieses Worktrees (kernel/.venv, wird hier mit uv sync aufgefrischt).
#                                   Danach wie gewohnt: open -g -n "build/Kev CAD Test ….app"
#   tools/fern.sh release           Installationsbau auf dem Mini, App, Kernel und Skill holen (Paket build/bundle) und hier
#                                   installieren wie ./build.sh (tools/auto-update.sh nutzt das)
#   tools/fern.sh status            Plätze, Schlange und Speicher auf dem Mini
#   tools/fern.sh einrichten        Mini vorbereiten oder prüfen: Ordner, xcodegen, uv, Metal-Toolchain, Xcode-Fassung
#
# Kürzel: Name des Auftrags auf dem Mini, Vorgabe KEVCAD_FERN_ID, sonst der Ordnername des Worktrees. Auf dem Mini liegt
# alles unter ~/KevCAD-Bau (siehe tools/fern/mini.sh): zwei Bauplätze mit festen, warmen Bäumen, ein Testplatz, Schlange
# nach Ankunft. Übertragen wird gepackt (rsync -z) ohne Bauordner und Umgebungen (tools/fern/ausschluss.txt).
#
# Rückfall: Ist der Mini nicht erreichbar (ssh antwortet nicht binnen 8 s; das Ergebnis gilt zwei Minuten), reißt die
# Verbindung ab oder fehlt ihm ein Werkzeug, läuft derselbe Auftrag hier mit ./build.sh unter der gemeinsamen Sperre
# /tmp/vb-xcodebuild.lock, vorher wartet er auf 25 % freien Speicher (höchstens 10 Minuten).
#   KEVCAD_FERN=lokal   immer hier (etwa wenn der Mini gebraucht wird); auch die Datei ~/.kevcad-nur-macbook
#   KEVCAD_FERN=mini    nie hier: ohne Mini Ausgang 255
#   KEVCAD_FERN_HOST    anderer ssh-Name (Vorgabe mac-mini; mac-mini-ts über Tailscale)
#   KEVCAD_FERN_FRIST   Frist eines Laufs auf dem Mini in Sekunden (3600)
#   KEVCAD_FERN_SRC, KEVCAD_FERN_OUT   andere Quelle bzw. Ablage statt build/ (Proben; mit KEVCAD_FERN=mini schreibt fern.sh
#                       dann nichts in die Quelle, solange dort das App-Symbol aktuell ist)
# Zeiten je Aufruf: ~/Library/Logs/Kev CAD/fern.tsv (Beginn, Art, Kürzel, Rechner, Ausgang, gesamt, hin, Mini, zurück).
set -uo pipefail

FERN_DIR="$(cd "$(dirname "$0")" && pwd)"
# Quelle und Ablage der Ergebnisse; anders nur für Proben (etwa release aus build-src, ohne dort zu schreiben).
REPO="${KEVCAD_FERN_SRC:-$(cd "$FERN_DIR/.." && pwd)}"
cd "$REPO" || exit 1
REPO="$(pwd)"
OUT="${KEVCAD_FERN_OUT:-$REPO/build}"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
HOST=${KEVCAD_FERN_HOST:-mac-mini}
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
RSH="ssh ${SSH_OPTS[*]}"
# Kurze Befehle ohne stdin (-n), damit ssh keine Eingaben des Aufrufers schluckt.
mini() { ssh -n "${SSH_OPTS[@]}" "$HOST" "$@"; }
REMOTE=KevCAD-Bau
BUILD_LOCK=/tmp/vb-xcodebuild.lock
LOGDIR="$HOME/Library/Logs/Kev CAD"
INSTALL_ROOT="${KEVCAD_INSTALL_ROOT:-$HOME/Library/Application Support/de.upvis.kevcad/install}"

usage() { sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; }

MODE=${1:-}
[ $# -gt 0 ] && shift
NAME=""; ID_ARG=""
case "$MODE" in
  tests) ID_ARG=${1:-} ;;
  testbau) NAME=${1:-} ;;
  release|status|einrichten) ;;
  -h|--help|hilfe) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac
ID=${ID_ARG:-${KEVCAD_FERN_ID:-$(basename "$REPO")}}
ID=$(printf '%s' "$ID" | tr -c 'A-Za-z0-9._-' '_')

now() { perl -MTime::HiRes=time -e 'printf "%.2f", time'; }
secs() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }
q() { printf '%q' "$1"; }

# Erreichbar? Ein Fehlschlag gilt zwei Minuten, damit nicht jeder Aufruf acht Sekunden wartet.
MINI_GONE_MARK="/tmp/kevcad-fern-mini-weg-$HOST"
mini_reachable() {
  if [ -e "$MINI_GONE_MARK" ] && [ $(( $(date +%s) - $(stat -f %m "$MINI_GONE_MARK") )) -lt 120 ]; then
    return 1
  fi
  if ssh -n -o ConnectTimeout=8 "${SSH_OPTS[@]}" "$HOST" "mkdir -p $REMOTE/auftrag $REMOTE/quelle $REMOTE/ergebnis" 2>/dev/null
  then
    rm -f "$MINI_GONE_MARK"; return 0
  fi
  : > "$MINI_GONE_MARK"
  return 1
}

if [ "$MODE" = status ]; then
  mini_reachable || { echo "Mac mini ($HOST) nicht erreichbar."; exit 255; }
  # mini.sh liegt nur in Schnappschüssen; für den Blick auf die Plätze reicht der letzte beliebige.
  mini "s=\$(ls -td $REMOTE/quelle/*/tools/fern/mini.sh 2>/dev/null | head -1);
    [ -n \"\$s\" ] && KEVCAD_FERN_WACHE=0 /bin/bash \"\$s\" status || echo 'Noch kein Auftrag auf dem Mini.'"
  exit $?
fi

if [ "$MODE" = einrichten ]; then
  mini_reachable || { echo "Mac mini ($HOST) nicht erreichbar."; exit 255; }
  rc=0
  echo "==> Ordner ~/$REMOTE"
  mini "mkdir -p $REMOTE/auftrag $REMOTE/quelle $REMOTE/ergebnis $REMOTE/platz $REMOTE/sperren \
    $REMOTE/protokoll $REMOTE/cache $REMOTE/werkzeuge" || rc=1
  echo "==> xcodegen"
  xg=$(command -v xcodegen) || { echo "xcodegen fehlt auch hier (brew install xcodegen)"; exit 1; }
  xg_home=$(cd "$(dirname "$(readlink -f "$xg")")/.." && pwd)
  local_ver=$(xcodegen --version 2>/dev/null)
  remote_ver=$(mini "$REMOTE/werkzeuge/xcodegen/bin/xcodegen --version" 2>/dev/null)
  if [ "$local_ver" != "$remote_ver" ]; then
    # Nur Systembibliotheken, aber die SettingPresets müssen neben dem Programm liegen (../share/xcodegen).
    rsync -a --delete -e "$RSH" "$xg_home/bin" "$xg_home/share" "$HOST:$REMOTE/werkzeuge/xcodegen/" || rc=1
    remote_ver=$(mini "$REMOTE/werkzeuge/xcodegen/bin/xcodegen --version" 2>/dev/null)
  fi
  echo "Mini: ${remote_ver:-fehlt} (hier: $local_ver)"
  echo "==> uv"
  if ! mini ".local/bin/uv --version" 2>/dev/null; then
    # Kein Installationsskript aus dem Netz: dieselbe Binärdatei wie hier (beide arm64).
    mini "mkdir -p .local/bin" && scp -q -o BatchMode=yes "$(command -v uv)" "$HOST:.local/bin/uv" || rc=1
    mini ".local/bin/uv --version" || rc=1
  fi
  echo "==> Metal-Toolchain"
  if ! mini "xcrun metal --version 2>/dev/null | head -1"; then
    echo "fehlt, lade nach (xcodebuild -downloadComponent MetalToolchain, ohne Passwort, rund 840 MB) …"
    mini "xcodebuild -downloadComponent MetalToolchain 2>&1 | tr '\r' '\n' | tail -2; xcrun metal --version | head -1" || rc=1
  fi
  echo "==> Xcode"
  here=$(xcodebuild -version 2>/dev/null | tr '\n' ' ')
  there=$(mini "xcodebuild -version" 2>/dev/null | tr '\n' ' ')
  echo "MacBook: $here"; echo "Mini:    $there"
  [ "$here" = "$there" ] || echo "Achtung: verschiedene Xcode-Fassungen, die installierte App käme vom Xcode des Mini."
  exit $rc
fi

mkdir -p "$LOGDIR"
T0=$(now); UP=0; REMOTE_SECS=0; DOWN=0; WHERE=mini

log_times() {
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -r "${T0%.*}" '+%Y-%m-%d %H:%M:%S')" "$MODE${NAME:+ $NAME}" "$ID" \
    "$WHERE" "$1" "$(secs "$T0" "$(now)")" "$UP" "$REMOTE_SECS" "$DOWN" >> "$LOGDIR/fern.tsv" 2>/dev/null
}

# Vor dem Bauen hier warten, bis mindestens 25 % Speicher frei sind (höchstens 10 Minuten), wie tools/auto-update.sh.
wait_for_memory() {
  local i free
  for i in $(seq 1 60); do
    free=$(memory_pressure 2>/dev/null | tail -1 | grep -oE '[0-9]+' | tail -1)
    { [ -z "$free" ] || [ "$free" -ge 25 ]; } && return 0
    [ "$i" -eq 1 ] && echo "Warte auf freien Speicher ($free % frei)"
    sleep 10
  done
  return 0
}

# Der lokale Weg wie bisher: ./build.sh unter der gemeinsamen Sperre mit VoiceBridge.
run_local() {
  WHERE=macbook
  local cmd=(./build.sh) rc
  case "$MODE" in
    tests) cmd=(./build.sh --core-tests) ;;
    testbau) cmd=(./build.sh --test); [ -n "$NAME" ] && cmd+=("$NAME") ;;
  esac
  wait_for_memory
  lockf -k "$BUILD_LOCK" "${cmd[@]}"
  rc=$?
  log_times $rc
  exit $rc
}

fallback() {
  echo "==> Mac mini: $1. $MODE läuft hier auf dem MacBook (./build.sh unter $BUILD_LOCK)." >&2
  if [ "${KEVCAD_FERN:-}" = mini ]; then
    echo "==> KEVCAD_FERN=mini: kein Rückfall, Auftrag später neu starten." >&2
    log_times 255
    exit 255
  fi
  run_local
}

if [ "${KEVCAD_FERN:-}" = lokal ] || [ -e "$HOME/.kevcad-nur-macbook" ]; then
  echo "==> Nur MacBook (KEVCAD_FERN=lokal oder ~/.kevcad-nur-macbook): $MODE läuft hier." >&2
  run_local
fi
mini_reachable || fallback "nicht erreichbar ($HOST)"

APP_TEST="Kev CAD Test${NAME:+ $NAME}"
JOB_ID="$ID-$(date +%Y%m%d-%H%M%S)-$$"
case "$MODE" in tests) KIND=tests ;; testbau) KIND=testbau ;; release) KIND=bundle ;; esac

# Was hier vorbereitet wird: das Symbol (rsvg-convert fehlt dem Mini) und für testbau die Kernel-Umgebung dieses
# Worktrees, die die Test-App hier startet. Beides ist schnell und baut nichts.
if [ "$KIND" != tests ]; then
  ./build.sh --icon || exit 1
fi
if [ "$KIND" = testbau ]; then
  (cd kernel && uv sync -q) || { echo "uv sync im Kernel fehlgeschlagen"; exit 1; }
fi

# Buildnummer und Stand von hier (der Schnappschuss hat kein .git); der Pfad, unter dem die App ihren Kernel findet.
BUILD_NUMBER=$(git rev-list --count HEAD 2>/dev/null || echo 1)
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "")
[ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] && COMMIT="$COMMIT+"
if [ "$KIND" = bundle ]; then APP_REPO=$INSTALL_ROOT; else APP_REPO=$REPO; fi

# Hochladen in einen eigenen Schnappschuss je Auftrag; unveränderte Dateien verlinkt rsync aus dem letzten des Kürzels.
T_UP=$(now)
# Nach Inhalt (-c), nicht nach Zeitstempel: Eine andere Arbeitskopie desselben Stands (build-src nach git reset) hat
# andere Zeitstempel, und openrsync kopiert dann jede Datei aus der Grundlage mit einer eigenen, erst am Ende
# geschlossenen Datei. Am 22.10.2026 scheiterte so das erste echte Update bei rund 500 Dateien am Limit von 256 offenen
# Dateien der ssh-Sitzung („copy_file fromfd: openat: Too many open files“). Mit -c verlinkt rsync gleiche Inhalte
# unabhängig vom Zeitstempel und kopiert nur Geändertes; das höhere Limit fängt große Änderungen ab.
if ! rsync -azc --delete --exclude-from="$FERN_DIR/fern/ausschluss.txt" --link-dest="../../quelle/$ID" -e "$RSH" \
  --rsync-path="ulimit -n 10240 2>/dev/null; rsync" ./ "$HOST:$REMOTE/auftrag/$JOB_ID/"; then
  fallback "Hochladen fehlgeschlagen"
fi
UP=$(secs "$T_UP" "$(now)")
echo "==> fern: $MODE${NAME:+ $NAME} für $ID auf dem Mac mini (hochgeladen in $UP s)"

remote_cmd="cd $REMOTE/auftrag/$(q "$JOB_ID") && exec env KEVCAD_FERN_ID=$(q "$ID") KEVCAD_BUILD_NUMBER=$(q "$BUILD_NUMBER")"
remote_cmd="$remote_cmd KEVCAD_COMMIT_ID=$(q "$COMMIT") KEVCAD_APP_REPO=$(q "$APP_REPO") KEVCAD_FERN_FRIST=$(q "${KEVCAD_FERN_FRIST:-3600}")"
remote_cmd="$remote_cmd /bin/bash tools/fern/mini.sh $(q "$JOB_ID") $KIND $(q "$NAME")"
# Herzschlag in stdin: Endet dieses fern.sh, endet er, und der Mini gibt den Auftrag samt Plätzen auf (tools/fern/mini.sh).
T_REMOTE=$(now)
ssh "${SSH_OPTS[@]}" "$HOST" "$remote_cmd" < <(while kill -0 $$ 2>/dev/null; do echo 2>/dev/null || break; sleep 5; done)
rc=$?
REMOTE_SECS=$(secs "$T_REMOTE" "$(now)")
case $rc in
  # Nur dieser Auftrag geht aufs MacBook; der nächste fragt den Mini wieder (die Marke setzt nur die Erreichbarkeitsprobe).
  255) fallback "Verbindung abgerissen" ;;
  86) fallback "ihm fehlt ein Werkzeug (tools/fern.sh einrichten)" ;;
esac

# Ergebnis holen
T_DOWN=$(now)
if [ $rc -eq 0 ]; then
  case "$KIND" in
    testbau)
      mkdir -p "$OUT"
      if rsync -az --delete -e "$RSH" "$HOST:$REMOTE/ergebnis/$JOB_ID/app.app/" "$OUT/$APP_TEST.app/"; then
        # Hier signieren (ad hoc wie build.sh) und bei Launch Services abmelden wie jede Build-Kopie.
        codesign --force --deep --sign - --timestamp=none "$OUT/$APP_TEST.app" >/dev/null 2>&1
        /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
          -u "$OUT/$APP_TEST.app" >/dev/null 2>&1
        echo "==> Fertig (vom Mac mini): $OUT/$APP_TEST.app"
      else
        fallback "Abholen der App fehlgeschlagen"
      fi
      ;;
    bundle)
      mkdir -p "$OUT"
      if rsync -az --delete -e "$RSH" "$HOST:$REMOTE/ergebnis/$JOB_ID/bundle/" "$OUT/bundle/"; then
        DOWN=$(secs "$T_DOWN" "$(now)")
        ./build.sh --install-bundle "$OUT/bundle" || rc=$?
      else
        fallback "Abholen des Pakets fehlgeschlagen"
      fi
      ;;
  esac
fi
[ "$KIND" = bundle ] || DOWN=$(secs "$T_DOWN" "$(now)")
mini "rm -rf $REMOTE/ergebnis/$(q "$JOB_ID")" 2>/dev/null
echo "==> fern: hin $UP s, Mini $REMOTE_SECS s, zurück $DOWN s, gesamt $(secs "$T0" "$(now)") s, Ausgang $rc"
log_times $rc
exit $rc
