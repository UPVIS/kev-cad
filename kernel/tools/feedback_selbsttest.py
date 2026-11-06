"""Selbsttest V2-6 Sprach-Feedback mit echtem Kernel und echter App (Testvariante), ohne Mikrofon und ohne Eingaben.

    tools/fern.sh testbau sprache
    kernel/.venv/bin/python -u kernel/tools/feedback_selbsttest.py "$HOME/Documents/Kev CAD/Kugelschieber Variante B"

Das Projekt wird kopiert, nie verändert. ``say`` spricht einen Text in eine Datei; die App bekommt sie als Testeingang
(KEVCAD_SPRACHE_TONDATEI), Maus und Striche laufen im Selbsttest der App (KEVCAD_SELFTEST=sprache) über dieselben Wege
wie die echte Maus. Das Fenster liegt hinter dem Schreibtischbild (KEVCAD_TEST_VERSTECKT), nichts fragt nach Rechten.

Dieses Skript spielt den Agenten: ``feedback(warten_s)`` über MCP wartet, ``kevcad-feedback`` läuft daneben als
Hintergrundbefehl. Gemessen wird die Zeit von ↩ bis zum Paket beim Agenten (Budget: unter 1 s) und bis der Befehl endet,
dazu die Zeit vom Ende eines Worts bis zum Text (Budget: unter 0,3 s). Während die App spricht, prüft es die Sperre.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp_types import Implementation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from messen import KATALOG, kopieren  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TEXT = "Mach das hier etwas höher. Und diesen Griff hier machst du bitte breiter. Den Rest lässt du so."
ENV_NAMEN = ("KEVCAD_CATALOG_DIR", "KEVCAD_DRUCK_CACHE", "KEVCAD_DRUCK_ABGLEICH", "KEVCAD_BAMBU_APP",
             "KEVCAD_FESTKOERPER_CACHE", "KEVCAD_FILAMENTE", "KEVCAD_DRUCKER_SSDP")


def ton_erzeugen(ziel: Path, stimme: str) -> float:
    subprocess.run(["say", "-v", stimme, "-r", "170", "-o", str(ziel), TEXT], check=True)
    aus = subprocess.run(["afinfo", str(ziel)], check=True, capture_output=True, text=True).stdout
    for zeile in aus.splitlines():
        if "estimated duration" in zeile:
            return float(zeile.split(":")[1].split()[0])
    raise RuntimeError("Tonlänge unbekannt")


def skript(dauer: float, pause: bool) -> list[dict]:
    """Zeigen beim ersten Satz, zeigen und zeichnen beim zweiten, drehen beim dritten, ↩ kurz nach dem Ton."""
    schritte = [{"t": 0.2, "art": "zeigen", "ziel": 0}, {"t": dauer * 0.42, "art": "zeigen", "ziel": 1},
                {"t": dauer * 0.5, "art": "strich", "ziel": 1}, {"t": dauer * 0.72, "art": "drehen", "dauer": 2.0}]
    ende = dauer + 0.7
    if pause:
        schritte += [{"t": ende, "art": "anhalten"}, {"t": ende + 1.0, "art": "weiter"}]
        ende += 1.5
    schritte.append({"t": ende, "art": "fertig"})
    return schritte


class Agent:
    """MCP über HTTP wie die Brücke, mit langer Lesezeit."""

    def __init__(self, port: int) -> None:
        self.port = port

    async def __aenter__(self) -> Client:
        self.http = create_mcp_http_client(timeout=httpx2.Timeout(30.0, read=1900.0))
        await self.http.__aenter__()
        transport = streamable_http_client(f"http://127.0.0.1:{self.port}/mcp", http_client=self.http)
        self.client = Client(transport, mode="legacy", cache=None,
                             client_info=Implementation(name="feedback-selbsttest", version="1"))
        return await self.client.__aenter__()

    async def __aexit__(self, *exc: object) -> None:
        await self.client.__aexit__(*exc)
        await self.http.__aexit__(*exc)


def text(res) -> str:
    return "\n".join(b.text for b in res.content if getattr(b, "type", None) == "text")


async def agent_lauf(port: int, ausgabe: Path, frist_s: float) -> dict:
    """Wartet als Agent; prüft währenddessen, was der Agent zu hören bekommt, solange Kevin spricht."""
    ergebnis: dict = {"sperre": {}}
    ende = time.monotonic() + frist_s
    async with Agent(port) as zweiter:  # zweite Sitzung: prüft die Sperre, während die erste wartet
        async with Agent(port) as erster:
            async with anyio.create_task_group() as tg:

                async def sperre_pruefen() -> None:
                    while time.monotonic() < ende:
                        s = text(await zweiter.call_tool("status", {}))
                        if "Kevin spricht gerade" in s:
                            ergebnis["sperre"]["status"] = next(z for z in s.splitlines() if "Kevin spricht" in z)
                            t0 = time.monotonic()
                            r = await zweiter.call_tool("run", {})
                            ergebnis["sperre"]["run"] = {"antwort_ms": round((time.monotonic() - t0) * 1000),
                                                         "fehler": bool(r.is_error), "text": text(r)[:90]}
                            r = await zweiter.call_tool("view", {"standard": "top"})
                            ergebnis["sperre"]["view"] = {"fehler": bool(r.is_error), "text": text(r)[:90]}
                            return
                        await anyio.sleep(0.2)

                tg.start_soon(sperre_pruefen)
                res = await erster.call_tool("feedback", {"warten_s": frist_s})
                ergebnis["angekommen_unix"] = time.time()
                ergebnis["text"] = text(res)
                ergebnis["bild"] = sum(1 for b in res.content if getattr(b, "type", None) == "image")
                ergebnis["fehler"] = bool(res.is_error)
                nochmal = await erster.call_tool("feedback", {"warten_s": 0})
                ergebnis["danach"] = text(nochmal)[:100]
                tg.cancel_scope.cancel()
    return ergebnis


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("projekt", help="Projektordner (wird kopiert, nie verändert)")
    ap.add_argument("--app", default=str(REPO / "build/Kev CAD Test sprache.app"))
    ap.add_argument("--stimme", default="Anna")
    ap.add_argument("--frist-s", type=float, default=240.0)
    ap.add_argument("--pause", action="store_true", help="mit V anhalten und weitersprechen")
    ap.add_argument("--katalog", default=None)
    args = ap.parse_args()

    app = Path(args.app)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    port = int(info["KevCADPort"])
    prozess = info["CFBundleExecutable"]
    # Nur die Begrüßung bei Wortlaut: Das Mikrofon bleibt zu
    hallo = subprocess.run([str(app / "Contents/MacOS" / prozess)], env={**os.environ, "KEVCAD_SELFTEST": "wortlaut"},
                           capture_output=True, text=True, timeout=30)
    print(hallo.stdout.strip() or f"Wortlaut: kein Ergebnis (Ausgang {hallo.returncode})", flush=True)
    arbeit, kopie = kopieren(Path(args.projekt).expanduser(), Path(args.katalog).expanduser() if args.katalog else KATALOG)
    ausgabe = Path(tempfile.mkdtemp(prefix="fb-selbsttest-", dir=arbeit))
    ton = ausgabe / "sprache.aiff"
    dauer = ton_erzeugen(ton, args.stimme)
    (ausgabe / "skript.json").write_text(json.dumps(skript(dauer, args.pause)))
    print(f"Ton {dauer:.1f} s, Projekt {kopie}, Port {port}", flush=True)

    env = {"KEVCAD_SELFTEST": "sprache", "KEVCAD_SELFTEST_PROJEKT": str(kopie), "KEVCAD_SELFTEST_AUSGABE": str(ausgabe),
           "KEVCAD_SPRACHE_TONDATEI": str(ton), "KEVCAD_SPRACHE_SKRIPT": str(ausgabe / "skript.json"),
           "KEVCAD_TEST_VERSTECKT": "1", "KEVCAD_PROJECTS_DIR": str(arbeit),
           **{k: os.environ[k] for k in ENV_NAMEN if k in os.environ}}
    befehl = ["open", "-g", "-n", "--stdout", str(ausgabe / "app.log"), "--stderr", str(ausgabe / "app.log")]
    for k, v in env.items():
        befehl += ["--env", f"{k}={v}"]
    subprocess.run([*befehl, str(app)], check=True)

    bericht_datei = ausgabe / "selftest-sprache.json"
    try:
        beginn = time.monotonic()
        while time.monotonic() - beginn < 60:  # Kernel-Server da?
            try:
                import socket

                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                time.sleep(0.25)
        hintergrund = subprocess.Popen(
            [sys.executable, "-m", "kevcad_kernel.feedback_cli", "--port", str(port), "--warten-s", str(args.frist_s)],
            stdout=subprocess.PIPE, text=True)
        hintergrund_ende: dict = {}

        def warten() -> None:
            hintergrund_ende["ausgabe"] = hintergrund.stdout.read().strip() if hintergrund.stdout else ""
            hintergrund.wait()
            hintergrund_ende["unix"] = time.time()
            hintergrund_ende["code"] = hintergrund.returncode

        faden = threading.Thread(target=warten)
        faden.start()
        agent = anyio.run(agent_lauf, port, ausgabe, args.frist_s)
        faden.join(10)
        ende = time.monotonic() + 30
        while not bericht_datei.exists() and time.monotonic() < ende:
            time.sleep(0.1)
        bericht = json.loads(bericht_datei.read_text()) if bericht_datei.exists() else {}
    finally:
        subprocess.run(["pkill", "-x", prozess], check=False)

    print("\n".join(bericht.get("pruefungen", [])))
    print("\n--- beim Agenten ---\n" + agent.get("text", ""))
    print(f"\nBilder im Ergebnis: {agent.get('bild')}, danach: {agent.get('danach')}")
    print(f"Sperre: {json.dumps(agent.get('sperre'), ensure_ascii=False)}")
    if bericht.get("fertig_unix"):
        ms = (agent["angekommen_unix"] - bericht["fertig_unix"]) * 1000
        print(f"↩ bis Paket beim Agenten: {ms:.0f} ms (Budget 1000)")
        print(f"↩ bis Datei geschrieben (App): {(bericht['paket_unix'] - bericht['fertig_unix']) * 1000:.0f} ms")
        if hintergrund_ende.get("unix"):
            print(f"↩ bis Hintergrundbefehl endet: {(hintergrund_ende['unix'] - bericht['fertig_unix']) * 1000:.0f} ms, "
                  f"Ausgang {hintergrund_ende.get('code')}: {hintergrund_ende.get('ausgabe')}")
    latenz = bericht.get("wort_latenz_ms") or []
    if latenz:
        q = statistics.quantiles(latenz, n=10) if len(latenz) > 1 else latenz * 9
        print(f"Wort als Text nach Wortende: Median {statistics.median(latenz):.0f} ms, 90 % {q[8]:.0f} ms, "
              f"max {max(latenz):.0f} ms, {len(latenz)} Wörter (Budget 300)")
    if bericht.get("drehen"):
        print(f"Drehen ohne Sitzung: {bericht.get('drehen_ohne_sitzung')}")
        print(f"Drehen während des Sprechens: {bericht['drehen']}")
    print(f"Paket: {bericht.get('datei')}")
    if not os.environ.get("KEVCAD_BEHALTEN"):
        shutil.rmtree(arbeit, ignore_errors=True)
    else:
        print(f"Arbeitsordner: {arbeit}")
    return 0 if bericht.get("ok") and not agent.get("fehler") else 1


if __name__ == "__main__":
    sys.exit(main())
