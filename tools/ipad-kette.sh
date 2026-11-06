#!/bin/bash
# Kettentest Mac ↔ iPad (PLAN-IPAD.md, I-2b und I-3b): Die Mac-Testvariante startet versteckt mit eigenem Kernel und legt
# einen Kopplungscode an, die iPad-App im Simulator übernimmt ihn (ohne Kamera), verbindet sich über den TLS-Eingang, und
# über MCP baut der Kernel ein kleines Modell. Am Ende ein Bildschirmfoto des iPad; alles wird wieder beendet.
#
#   tools/ipad-kette.sh            Voraussetzung: tools/fern.sh testbau ipad und tools/ipad-bau.sh app
#
# Keine Fenster auf Kevins Bildschirm: Die Mac-Testvariante läuft mit KEVCAD_TEST_VERSTECKT=1, der Simulator bootet nur über
# simctl. Ergebnis und Bild unter build/ipad-kette/. Ausgang 0 nur, wenn das iPad am Eingang verbunden war und das Modell
# gebaut wurde.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/build/ipad-kette"
MAC_APP="$REPO/build/Kev CAD Test ipad.app"
PAD_APP="$REPO/build/Kev CAD iPad.app"
SIM_NAME="${KEVCAD_IPAD_SIM:-iPad Pro 13-inch (M5)}"
PY="$REPO/kernel/.venv/bin/python"
mkdir -p "$OUT"
[ -d "$MAC_APP" ] || { echo "Erst bauen: tools/fern.sh testbau ipad"; exit 1; }
[ -d "$PAD_APP" ] || { echo "Erst bauen: tools/ipad-bau.sh app"; exit 1; }
[ -x "$PY" ] || { echo "Kernel-Umgebung fehlt (cd kernel && uv sync)"; exit 1; }
UDID=$(xcrun simctl list devices available | grep -F "$SIM_NAME (" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')
[ -n "$UDID" ] || { echo "Simulator „$SIM_NAME“ fehlt"; exit 1; }

aufraeumen() {
  pkill -x "Kev CAD Test ipad" 2>/dev/null
  xcrun simctl terminate "$UDID" de.upvis.kevcad.ipad > /dev/null 2>&1
  [ "${GEBOOTET:-0}" = 1 ] && xcrun simctl shutdown "$UDID" > /dev/null 2>&1
}
trap aufraeumen EXIT

rm -f "$OUT/kopplung.txt"
pkill -x "Kev CAD Test ipad" 2>/dev/null
open -g -n --env KEVCAD_TEST_VERSTECKT=1 --env "KEVCAD_TEST_KOPPLUNG_DATEI=$OUT/kopplung.txt" "$MAC_APP"
for i in $(seq 1 90); do [ -s "$OUT/kopplung.txt" ] && break; sleep 1; done
[ -s "$OUT/kopplung.txt" ] || { echo "Kein Kopplungscode nach 90 s"; exit 1; }
echo "==> Kopplungscode nach ${i} s"

GEBOOTET=0
if ! xcrun simctl list devices | grep -F "$UDID) (Booted)" > /dev/null; then
  xcrun simctl boot "$UDID" || exit 1
  GEBOOTET=1
fi
xcrun simctl bootstatus "$UDID" > /dev/null || exit 1
xcrun simctl terminate "$UDID" de.upvis.kevcad.ipad > /dev/null 2>&1
xcrun simctl install "$UDID" "$PAD_APP" || exit 1
SIMCTL_CHILD_KEVCAD_PAD_KOPPLUNG="$(cat "$OUT/kopplung.txt")" SIMCTL_CHILD_KEVCAD_PAD_OHNE_KOPPLUNGSBLATT=1 \
  xcrun simctl launch "$UDID" de.upvis.kevcad.ipad > /dev/null || exit 1

# Warten, bis das iPad am Eingang hängt (Port: MCP-Port der Testvariante + 2)
PORT=$(/usr/libexec/PlistBuddy -c "Print :KevCADPort" "$MAC_APP/Contents/Info.plist" 2>/dev/null || echo 47850)
EINGANG=$((PORT + 2))
verbunden=0
for i in $(seq 1 "${KEVCAD_IPAD_VERBINDEN:-240}"); do
  if lsof -nP -iTCP:"$EINGANG" -sTCP:ESTABLISHED 2>/dev/null | grep -q "Kev"; then verbunden=1; break; fi
  sleep 1
done
[ "$verbunden" = 1 ] || { echo "iPad hat sich nach ${KEVCAD_IPAD_VERBINDEN:-240} s nicht verbunden"; exit 1; }
echo "==> iPad am Eingang (Port $EINGANG) nach ${i} s"

"$PY" -I - "$PORT" > "$OUT/mcp.txt" 2>&1 << 'PYEOF'
import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CODE = '''from build123d import *
from kevcad import show, step, param

breite = param("breite", 120)
step("Platte")
show(Box(breite, 80, 6), "Ständer/Platte")
step("Säule")
show(Cylinder(10, 60).moved(Location((30, 0, 33))), "Ständer/Säule")
'''

async def main(port: int) -> None:
    async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for name, args in (("modell", {"code": CODE}), ("run", {})):
                res = await s.call_tool(name, args)
                print(name, "->", " ".join(getattr(c, "text", "") for c in res.content)[:300].replace("\n", " | "))

asyncio.run(main(int(sys.argv[1])))
PYEOF
grep -q "run -> Lauf" "$OUT/mcp.txt" || { echo "Modell nicht gebaut:"; cat "$OUT/mcp.txt"; exit 1; }
echo "==> Modell gebaut: $(grep "run ->" "$OUT/mcp.txt" | cut -c1-90)"
sleep "${KEVCAD_IPAD_WARTEN:-8}"
xcrun simctl io "$UDID" screenshot "$OUT/ipad.png" > /dev/null 2>&1 && echo "==> Bildschirmfoto: $OUT/ipad.png"
exit 0
