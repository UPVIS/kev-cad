#!/bin/zsh
# Selbsttest V2-7 (kernel/tools/kachel_selbsttest.py) auf dem Mac mini: Testvariante, Kernel, Projekt- und Katalogkopie
# hinüber, Test dort, Ergebnis und Fensterbilder zurück. So liegt kein Fenster auf Kevins Hauptbildschirm.
#
#   tools/fern.sh testbau k7
#   tools/fern/kachel-selbsttest.sh "build/Kev CAD Test k7.app" "$HOME/Documents/Kev CAD/Kugelschieber Variante B" [Ziel]
#
# Ziel (Vorgabe build/kachel-selbsttest): ergebnis.json und fotos/. Kevins Projekt und Katalog bleiben unberührt.
set -e
REPO="${0:A:h:h:h}"
APP="${1:?Testvariante fehlt}"; PROJEKT="${2:?Projektordner fehlt}"; ZIEL="${3:-$REPO/build/kachel-selbsttest}"
HOST=${KEVCAD_FERN_HOST:-mac-mini}
R=KevCAD-Bau/kachel-selbsttest
NAME="${APP:t}"; PNAME="${PROJEKT:t}"
KATALOG="$HOME/Library/Application Support/de.upvis.kevcad/katalog"

ssh -n "$HOST" "mkdir -p $R/app $R/proj $R/katalog"
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache "$REPO/kernel/" "$HOST:$R/kernel/"
rsync -az --delete "$APP/" "$HOST:$R/app/${NAME// /\\ }/"
rsync -az --exclude .kevcad/cache --exclude output "$PROJEKT/" "$HOST:$R/proj/${PNAME// /\\ }/"
[ -d "$KATALOG" ] && rsync -az "$KATALOG/" "$HOST:$R/katalog/"
ssh -n "$HOST" "cd $R/kernel && export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH LANG=de_DE.UTF-8 LC_ALL=de_DE.UTF-8 && uv sync -q; \
  cd .. && rm -rf fotos ergebnis.json && kernel/.venv/bin/python -u kernel/tools/kachel_selbsttest.py 'app/$NAME' 'proj/$PNAME' \
  --katalog katalog --json ergebnis.json --fotos fotos"
mkdir -p "$ZIEL"
rsync -az "$HOST:$R/ergebnis.json" "$HOST:$R/fotos" "$ZIEL/"
echo "Ergebnis: $ZIEL"
