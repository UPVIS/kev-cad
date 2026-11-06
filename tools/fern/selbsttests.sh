#!/bin/zsh
# Selbsttests der App (kernel/tools/selbsttests.py) auf dem Mac mini: Testvariante, Kernel, Projekt- und Katalogkopie hinüber,
# Lauf dort, Berichte zurück. So liegt kein Dialog auf Kevins Hauptbildschirm. Der Lauf wartet in der Testschlange nicht:
# Er braucht die Konsolen-Sitzung, nicht den Testplatz.
#
#   tools/fern.sh testbau st
#   tools/fern/selbsttests.sh "build/Kev CAD Test st.app" "$HOME/Documents/Kev CAD/Kugelschieber Variante B" [Tests …]
#
# Berichte in build/selbsttests/<Test>/, Überblick in ergebnis.json. Kevins Projekt und Katalog bleiben unberührt.
set -e
REPO="${0:A:h:h:h}"
APP="${1:?Testvariante fehlt}"; PROJEKT="${2:?Projektordner fehlt}"; shift 2
HOST=${KEVCAD_FERN_HOST:-mac-mini}
R=KevCAD-Bau/selbsttests
NAME="${APP:t}"; PNAME="${PROJEKT:t}"
KATALOG="$HOME/Library/Application Support/de.upvis.kevcad/katalog"

ssh -n "$HOST" "mkdir -p $R/app $R/proj $R/katalog"
rsync -az --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache "$REPO/kernel/" "$HOST:$R/kernel/"
rsync -az --delete "$APP/" "$HOST:$R/app/${NAME// /\\ }/"
# Der Ersatz-Kernel liest die Testdateien des Protokolls
F=app/KevCADCore/Tests/KevCADCoreTests/Fixtures
ssh -n "$HOST" "mkdir -p $R/$F"
rsync -az --delete "$REPO/$F/" "$HOST:$R/$F/"
rsync -az --delete "$REPO/samples/" "$HOST:$R/samples/"
rsync -az --exclude .kevcad/cache --exclude output "$PROJEKT/" "$HOST:$R/proj/${PNAME// /\\ }/"
[ -d "$KATALOG" ] && rsync -az "$KATALOG/" "$HOST:$R/katalog/"
TESTS="${(j: :)${(q)@}}"
ssh -n "$HOST" "cd $R/kernel && export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH LANG=de_DE.UTF-8 LC_ALL=de_DE.UTF-8 && uv sync -q; \
  cd .. && kernel/.venv/bin/python -u kernel/tools/selbsttests.py 'app/$NAME' 'proj/$PNAME' $TESTS --katalog katalog --ausgabe ausgabe"
mkdir -p "$REPO/build/selbsttests"
rsync -az "$HOST:$R/ausgabe/" "$REPO/build/selbsttests/"
echo "Berichte: $REPO/build/selbsttests"
