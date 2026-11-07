#!/bin/bash
# Kettentest Mac ↔ iPad (PLAN-IPAD.md, I-2b und I-3b): Die Mac-Testvariante startet versteckt mit eigenem Kernel und legt
# einen Kopplungscode an, die iPad-App im Simulator übernimmt ihn (ohne Kamera), verbindet sich über den TLS-Eingang, und
# über MCP baut der Kernel ein kleines Modell. Am Ende ein Bildschirmfoto des iPad; alles wird wieder beendet.
#
# I-6 (Live-Kopplung): Der Code geht mit falschem Namen und ohne Adressen ans iPad, so findet es den Mac nur über die
# Kennung im Bonjour-Eintrag. Danach folgt die Ansicht in beide Richtungen (Testweg des Kernels, `test_kopplung`), die
# Eigene Ansicht bleibt stehen, und beim Wechsel zurück kommt der Stand des führenden Geräts.
#   KEVCAD_KETTE_NAME=echt   Code unverändert (mit Namen und Adressen) ans iPad
#
#   tools/ipad-kette.sh            Voraussetzung: tools/fern.sh testbau ipad und tools/ipad-bau.sh app
#
# Keine Fenster auf Kevins Bildschirm: Die Mac-Testvariante läuft mit KEVCAD_TEST_VERSTECKT=1, der Simulator bootet nur über
# simctl. Ergebnis und Bild unter build/ipad-kette/. Ausgang 0 nur, wenn das iPad am Eingang verbunden war und das Modell
# gebaut wurde.
set -uo pipefail
# Ein Simulator und eine Mac-Testvariante „ipad“ für alle Arbeitskopien: der ganze Test unter der Simulator-Sperre
if [ -z "${KEVCAD_IPAD_SIM_GESPERRT:-}" ]; then
  exec env KEVCAD_IPAD_SIM_GESPERRT=1 lockf -k /tmp/kevcad-ipad-sim.lock "$0" "$@"
fi
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
  [ -n "${DNSSD_PID:-}" ] && kill "$DNSSD_PID" 2>/dev/null
  pkill -x "Kev CAD Test ipad" 2>/dev/null
  xcrun simctl terminate "$UDID" de.upvis.kevcad.ipad > /dev/null 2>&1
  [ "${GEBOOTET:-0}" = 1 ] && xcrun simctl shutdown "$UDID" > /dev/null 2>&1
}
trap aufraeumen EXIT

rm -f "$OUT/kopplung.txt"
pkill -x "Kev CAD Test ipad" 2>/dev/null
open -g -n --env KEVCAD_TEST_VERSTECKT=1 --env KEVCAD_KERNEL_TESTWEG=1 --env "KEVCAD_TEST_KOPPLUNG_DATEI=$OUT/kopplung.txt" "$MAC_APP"
for i in $(seq 1 90); do [ -s "$OUT/kopplung.txt" ] && break; sleep 1; done
[ -s "$OUT/kopplung.txt" ] || { echo "Kein Kopplungscode nach 90 s"; exit 1; }
echo "==> Kopplungscode nach ${i} s"
CODE="$(cat "$OUT/kopplung.txt")"
if [ "${KEVCAD_KETTE_NAME:-umbenannt}" != echt ]; then
  # Mac „umbenannt“ und ohne Adressen: Das iPad findet ihn nur über seine Kennung (TXT mac)
  CODE="$(/usr/bin/python3 -I - "$CODE" << 'PYEOF'
import base64, json, sys
schema = "kevcad://koppeln/"
b64 = sys.argv[1].strip()[len(schema):].replace("-", "+").replace("_", "/")
code = json.loads(base64.b64decode(b64 + "=" * (-len(b64) % 4)))
code["name"] = "Umbenannter Mac (Kettentest)"
code["wege"] = []
roh = base64.b64encode(json.dumps(code, sort_keys=True).encode()).decode()
print(schema + roh.replace("+", "-").replace("/", "_").rstrip("="))
PYEOF
)" || exit 1
  echo "==> Code mit falschem Namen und ohne Adressen: nur Bonjour über die Kennung"
  # Meldet die Mac-App ihren Dienst? (Ohne Erlaubnis für das lokale Netzwerk unterdrückt macOS das still.) Sonst ein
  # Stellvertreter mit Kennung und Port der Testvariante, damit wenigstens die Suche des iPad geprüft ist.
  MAC_KENNUNG=$(/usr/bin/python3 -I -c 'import base64,json,sys; s=sys.argv[1].strip()[17:].replace("-","+").replace("_","/"); print(json.loads(base64.b64decode(s+"="*(-len(s)%4)))["mac"])' "$(cat "$OUT/kopplung.txt")")
  PORT0=$(/usr/libexec/PlistBuddy -c "Print :KevCADPort" "$MAC_APP/Contents/Info.plist" 2>/dev/null || echo 47850)
  script -q "$OUT/bonjour.txt" dns-sd -B _kevcad._tcp local. > /dev/null 2>&1 &
  B_PID=$!
  sleep 3
  kill "$B_PID" 2>/dev/null; pkill -f "dns-sd -B _kevcad._tcp" 2>/dev/null
  if grep -q " Add .*_kevcad._tcp" "$OUT/bonjour.txt" 2>/dev/null; then
    echo "==> Mac-App meldet ihren Bonjour-Dienst"
  else
    echo "!!  Mac-App meldet keinen Bonjour-Dienst (Erlaubnis „Lokales Netzwerk“?): Stellvertreter per dns-sd"
    dns-sd -R "Kev CAD Kettentest" _kevcad._tcp local. $((PORT0 + 2)) v=1 "mac=$MAC_KENNUNG" > /dev/null 2>&1 &
    DNSSD_PID=$!
  fi
fi

GEBOOTET=0
if ! xcrun simctl list devices | grep -F "$UDID) (Booted)" > /dev/null; then
  xcrun simctl boot "$UDID" || exit 1
  GEBOOTET=1
fi
xcrun simctl bootstatus "$UDID" > /dev/null || exit 1
xcrun simctl terminate "$UDID" de.upvis.kevcad.ipad > /dev/null 2>&1
xcrun simctl install "$UDID" "$PAD_APP" || exit 1
SIMCTL_CHILD_KEVCAD_PAD_KOPPLUNG="$CODE" SIMCTL_CHILD_KEVCAD_PAD_OHNE_KOPPLUNGSBLATT=1 \
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

# I-6: Ansicht in beide Richtungen über den Testweg des Kernels (nur mit KEVCAD_KERNEL_TESTWEG=1)
"$PY" -I - "$PORT" > "$OUT/ansicht.txt" 2>&1 << 'PYEOF'
import json, sys, time, urllib.parse, urllib.request

PORT = int(sys.argv[1])

def befehl(**args):
    q = urllib.parse.urlencode({"cmd": "test_kopplung", "args": json.dumps(args)})
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/test/view_cmd?{q}", timeout=20) as r:
        res = json.loads(r.read())
    if not res.get("ok"):
        raise SystemExit(f"test_kopplung {args}: {res}")
    return json.loads(res.get("message") or "{}")

def warten(art, ansicht, frist=6.0):
    ende = time.monotonic() + frist
    while True:
        s = befehl(art=art)
        if s.get("ansicht") == ansicht or time.monotonic() > ende:
            return s
        time.sleep(0.25)

fehler = []
def pruefe(bed, text):
    print(("ok    " if bed else "FEHLER ") + text, flush=True)
    if not bed:
        fehler.append(text)

for art in ("mac", "ipad"):
    s = befehl(art=art)
    pruefe(s.get("modus") == "gemeinsam" and s.get("geraete", 0) >= 2, f"{art}: Gemeinsame Ansicht, {s.get('geraete')} Geräte")
befehl(art="mac", ansicht="top")
s = warten("ipad", "top")
pruefe(s.get("ansicht") == "top", f"Mac dreht auf Oben, iPad folgt ({s.get('ansicht')}, {s.get('latenz_ms')} ms)")
pruefe(befehl(art="mac").get("fuehrt") is True, "Mac führt")
time.sleep(0.6)
befehl(art="ipad", ansicht="front")
s = warten("mac", "front")
pruefe(s.get("ansicht") == "front", f"iPad dreht auf Vorne, Mac folgt ({s.get('ansicht')}, {s.get('latenz_ms')} ms)")
pruefe(befehl(art="ipad").get("fuehrt") is True, "iPad führt nach seinem Griff")
befehl(art="ipad", modus="eigen")
time.sleep(0.5)
befehl(art="mac", ansicht="right")
time.sleep(1.5)
s = befehl(art="ipad")
pruefe(s.get("ansicht") == "front", f"Eigene Ansicht am iPad bleibt stehen ({s.get('ansicht')})")
befehl(art="ipad", modus="gemeinsam")
s = warten("ipad", "right")
pruefe(s.get("ansicht") == "right", f"Zurück in der Gemeinsamen Ansicht: Stand des Mac ({s.get('ansicht')})")
mac, pad = befehl(art="mac"), befehl(art="ipad")
print(f"Verzögerung (Median): iPad → Mac {mac.get('latenz_ms')} ms aus {mac.get('messungen')}, "
      f"Mac → iPad {pad.get('latenz_ms')} ms aus {pad.get('messungen')}")
sys.exit(1 if fehler else 0)
PYEOF
ergebnis=$?
cat "$OUT/ansicht.txt"
[ $ergebnis = 0 ] || { echo "Ansicht folgt nicht in beide Richtungen"; exit 1; }
echo "==> Ansicht folgt in beide Richtungen"
exit 0
