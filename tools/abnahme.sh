#!/bin/zsh
# V2 abnehmen, ohne die installierte Fassung anzufassen (ABNAHME-V2.md): baut die Testvariante „abnahme“ aus diesem Stand,
# legt Kopien von Katalog und Projekt nach ~/Documents/Kev CAD Abnahme und startet die App damit. Die installierte App,
# ihr MCP-Server und die echten Projekte bleiben, wie sie sind.
#
#   tools/abnahme.sh ["Projektordner"]     Vorgabe: Kugelschieber Variante B
set -e
REPO="${0:A:h:h}"
cd "$REPO"
PROJEKT="${1:-$HOME/Documents/Kev CAD/Kugelschieber Variante B}"
ORT="$HOME/Documents/Kev CAD Abnahme"
KATALOG="$HOME/Library/Application Support/de.upvis.kevcad/katalog"
APP="build/Kev CAD Test abnahme.app"

mkdir -p "$ORT"
[ -d "$ORT/${PROJEKT:t}" ] || rsync -a --exclude .kevcad/cache --exclude output "$PROJEKT/" "$ORT/${PROJEKT:t}/"
[ -d "$ORT/.katalog" ] || rsync -a "$KATALOG/" "$ORT/.katalog/"
tools/fern.sh testbau abnahme
PORT=$(/usr/libexec/PlistBuddy -c 'Print :KevCADPort' "$APP/Contents/Info.plist")
open -n --env KEVCAD_PROJECTS_DIR="$ORT" --env KEVCAD_CATALOG_DIR="$ORT/.katalog" "$APP"

cat <<TEXT

Kev CAD Test abnahme läuft. Projektkopie: $ORT/${PROJEKT:t}

Für einen Agenten am Viewer einmal eintragen, dann in einer neuen Sitzung arbeiten:

  claude mcp add kevcad-abnahme -s user -e KEVCAD_PORT=$PORT -e KEVCAD_LAUNCH_ON_START=0 -- "$REPO/kernel/.venv/bin/kevcad-mcp"

Erster Satz an den Agenten: „Nimm den MCP-Server kevcad-abnahme und lies zuerst $REPO/skill/kev-cad/SKILL.md.“
Danach wieder austragen: claude mcp remove kevcad-abnahme -s user
TEXT
