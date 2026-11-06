#!/bin/zsh
# Aufbau-Video auf dem Mac mini (kernel/tools/aufbau_fern.py): Testvariante, Kernel, Projekt- und Katalogkopie hinüber,
# rechnen und rendern dort, Videos und Zeitplan zurück. So liegt kein Fenster auf Kevins Hauptbildschirm.
#
#   tools/fern.sh testbau abnahme
#   tools/fern/aufbau-video.sh "build/Kev CAD Test abnahme.app" "<Projektordner>" wunsch.json [Ziel]
#   tools/fern/aufbau-video.sh - "<Projektordner>"      nur rechnen und die Befunde nennen (ohne App)
#
# wunsch.json: Argumente von animation(aktion="aufbau"), etwa {"dauer_s": 26, "blickwinkel": ["orbit", "iso"]}.
# Ziel (Vorgabe build/aufbau-video): Videos und <name>_zeitplan.json. Kevins Projekt und Katalog bleiben unberührt.
set -e
REPO="${0:A:h:h:h}"
APP="${1:?Testvariante oder - fehlt}"; PROJEKT="${2:?Projektordner fehlt}"; WUNSCH="${3:-}"
ZIEL="${4:-$REPO/build/aufbau-video}"
HOST=${KEVCAD_FERN_HOST:-mac-mini}
R=KevCAD-Bau/aufbau-video
NAME="${APP:t}"; PNAME="${PROJEKT:t}"
KATALOG="$HOME/Library/Application Support/de.upvis.kevcad/katalog"

ssh -n "$HOST" "mkdir -p $R/app $R/proj $R/katalog && rm -rf $R/ergebnis"
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache "$REPO/kernel/" "$HOST:$R/kernel/"
[ "$APP" != "-" ] && rsync -az --delete "$APP/" "$HOST:$R/app/${NAME// /\\ }/"
rsync -az --delete --exclude .kevcad/cache --exclude output "$PROJEKT/" "$HOST:$R/proj/${PNAME// /\\ }/"
[ -d "$KATALOG" ] && rsync -az "$KATALOG/" "$HOST:$R/katalog/"
ARGS="'proj/$PNAME' --katalog katalog --ziel ergebnis"
[ "$APP" != "-" ] && ARGS="$ARGS --app 'app/$NAME'"
if [ -n "$WUNSCH" ]; then
  rsync -az "$WUNSCH" "$HOST:$R/wunsch.json"
  ARGS="$ARGS --wunsch wunsch.json"
fi
ssh -n "$HOST" "cd $R/kernel && export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH LANG=de_DE.UTF-8 LC_ALL=de_DE.UTF-8 && uv sync -q; \
  cd .. && kernel/.venv/bin/python -u kernel/tools/aufbau_fern.py $ARGS"
if [ "$APP" != "-" ]; then
  mkdir -p "$ZIEL"
  rsync -az "$HOST:$R/ergebnis/" "$ZIEL/"
  echo "Ergebnis: $ZIEL"
fi
