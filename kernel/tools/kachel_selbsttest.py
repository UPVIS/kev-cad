"""Selbsttest V2-7 mit echtem Kernel und echter App (Testvariante), immer an einer Kopie.

Der Kernel läuft hier im Prozess samt MCP über HTTP; die App verbindet sich mit ihm (``KEVCAD_KERNEL_EXTERNAL=1``), im
Hintergrund. Der Agent ist dieser Test: Er ruft die Werkzeuge ``view``, ``status`` und ``projekt`` wie im Gespräch, das
Lagebild der App sagt, was wirklich offen ist. Die App misst die längste Pause ihres Hauptfadens (``statistik.pause_ms``
im Lagebild von Testvarianten).

    tools/fern.sh testbau k7
    tools/fern/kachel-selbsttest.sh "build/Kev CAD Test k7.app" "$HOME/Documents/Kev CAD/Kugelschieber Variante B"

Geprüft wird: Eine Kachel im Fokus führt in die Werkstatt, Lagebild und ``status`` nennen Modus, Kacheln, große Kachel und
Rand; jede Kachel geht beim zweiten Öffnen in unter 300 ms auf; Umschalten Fokus/Werkstatt, groß und Rand ohne Pause über
100 ms; die zweite Ansicht rechnet, folgt einem Kamerabefehl und lässt den Hauptfaden frei; ``projekt(name=…)`` zieht das
Projekt um. Das Skript fährt den Test auf dem Mac mini: Dort liegt kein Fenster auf Kevins Hauptbildschirm und fremde Last
verfälscht die Zeiten nicht. Der Viewer zeichnet dort nicht auf den Bildschirm (kein Bild je Takt), die Fensterbilder
(``VIEW_CMD test_foto``, nur Testvarianten) zeigen deshalb die Oberfläche ohne das Modell.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_selbsttest import statistik  # noqa: E402
from messen import KATALOG, MCP_PORT, kopieren  # noqa: E402

GRENZE_KACHEL_MS = 300.0
GRENZE_UMSCHALTEN_MS = 100.0
KACHELN = ["stueckliste", "zuschnitt", "zeichnung", "bauplan", "druck", "animation", "ansicht", "material", "simulation",
           "versionen", "details", "render"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("app", help="Testvariante (Kev CAD Test ….app)")
    ap.add_argument("projekt", help="Projektordner (wird kopiert, nie verändert)")
    ap.add_argument("--katalog", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--fotos", default=None, help="Ordner für Fensterbilder zum eigenen Ansehen, Kevin bekommt sie nicht")
    args = ap.parse_args()

    app_pfad = Path(args.app).resolve()
    info = plistlib.loads((app_pfad / "Contents/Info.plist").read_bytes())
    bundle_id, name = info["CFBundleIdentifier"], info.get("CFBundleExecutable") or app_pfad.stem
    if ".test" not in bundle_id:
        raise SystemExit(f"{bundle_id}: nur Testvarianten")
    socket = Path.home() / "Library/Application Support" / bundle_id / "kernel.sock"
    socket.parent.mkdir(parents=True, exist_ok=True)
    projekt = Path(args.projekt).expanduser().resolve()
    arbeit, kopie = kopieren(projekt, Path(args.katalog).expanduser() if args.katalog else KATALOG)
    log = arbeit / "app.log"
    fotos = Path(args.fotos).resolve() if args.fotos else None
    if fotos:
        fotos.mkdir(parents=True, exist_ok=True)

    import anyio
    from kevcad_kernel.runtime import KernelRuntime
    from kevcad_kernel.server import KevcadHTTPServer
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    ergebnis: dict = {"projekt": projekt.name, "kacheln": {}, "umschalten": {}, "pruefungen": {}}
    fehler: list[str] = []
    durch = False

    def pruefe(ok: bool, text: str) -> None:
        ergebnis["pruefungen"][text] = bool(ok)
        print(f"{'OK    ' if ok else 'FEHLER'} {text}", flush=True)
        if not ok:
            fehler.append(text)

    rt = KernelRuntime(str(socket), MCP_PORT, auto_run=False, run_timeout_s=900, log=lambda line: None)
    server = None
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        server = KevcadHTTPServer(rt, 0).start_in_thread()
        umgebung = ["--env", "KEVCAD_KERNEL_EXTERNAL=1", "--env", f"KEVCAD_PROJECTS_DIR={arbeit}"]
        subprocess.run(["open", "-g", "-n", *umgebung, "--stderr", str(log), str(app_pfad)], check=True)
        ende = time.monotonic() + 30
        while time.monotonic() < ende:
            conn = rt._link.connection
            if conn is not None and not conn.closed and conn.live.gemeldet:
                break
            time.sleep(0.1)
        else:
            raise SystemExit("App meldet sich nicht")
        pruefe("flaeche-1" in conn.live.faehigkeiten, "App meldet flaeche-1")

        async def werkzeug(name_: str, **argumente) -> tuple[str, bool]:
            http = create_mcp_http_client(headers={"x-claude-code-session-id": "kachel-selbsttest"})
            async with http:
                async with Client(streamable_http_client(server.url, http_client=http), mode="legacy", cache=None) as c:
                    r = await c.call_tool(name_, argumente)
            return "\n".join(getattr(b, "text", "") for b in r.content), bool(r.is_error)

        def ruf(name_: str, **argumente) -> str:
            text, fehlgeschlagen = anyio.run(lambda: werkzeug(name_, **argumente))
            if fehlgeschlagen:
                print(f"       {name_} {argumente}: {text[:300]}", flush=True)
            return text

        def lage() -> dict:
            for _ in range(30):
                r = rt.lagebild(1.0)
                if r.get("quelle") == "app":
                    return r
            raise SystemExit(f"Kein LAGE von der App: {r}")

        def pause(aktion, dauer: float = 1.2) -> float:
            """Längste Pause des Hauptfadens, während ``aktion`` läuft und ``dauer`` Sekunden danach."""
            statistik(rt)  # setzt die Messung zurück
            aktion()
            time.sleep(dauer)
            return float(statistik(rt).get("pause_ms", -1))

        def bild(name_: str) -> None:
            if fotos:
                time.sleep(0.5)
                rt.view_command("test_foto", {"pfad": str(fotos / f"{name_}.png")})

        res = rt.project_open(str(kopie))
        pruefe(bool(res.get("ok", True)), f"Projekt offen: {kopie.name}")
        res = rt.run(timeout_s=600)
        rt.wait_idle(120)
        time.sleep(8)  # Prüfung, Statik, Nachlauf
        print(f"Lauf {res.get('run')}: {len(res.get('parts') or [])} Teile", flush=True)
        ruf("view", kacheln=["modell"], kacheln_nur=True, modus="fokus", rand="aus")

        # 1. Fokus, dann kommt eine Kachel
        f = lage()["flaeche"]
        pruefe(f["modus"] == "fokus", f"Start im Fokus: {f}")
        text = ruf("status")
        pruefe("Fläche: Fokus" in text, "status nennt den Fokus")
        bild("01-fokus")
        ms = pause(lambda: ruf("view", kacheln=["stueckliste"]))
        ergebnis["umschalten"]["erste Kachel im Fokus (Werkstatt zum ersten Mal)"] = ms
        f = lage()["flaeche"]
        pruefe(f["modus"] == "werkstatt" and f["kacheln"] == ["modell", "stueckliste"] and f["aktiv"] == "stueckliste",
               f"Kachel im Fokus führt in die Werkstatt: {f}")
        text = ruf("status")
        pruefe("Fläche: Werkstatt, 1 Modell, 2 Stückliste" in text, "status nennt Werkstatt und Kacheln")
        bild("02-stueckliste")

        # 2. Jede Kachel: erstes und zweites Öffnen
        for k in KACHELN:
            erst = pause(lambda: ruf("view", kacheln=["modell", k], kacheln_nur=True), 1.5)
            f = lage()["flaeche"]
            pruefe(k in f["kacheln"], f"Kachel {k} offen")
            bild(f"03-{k}")
            ruf("view", kachel_zu=[k])
            time.sleep(0.4)
            zweit = pause(lambda: ruf("view", kacheln=[k]), 1.2)
            ergebnis["kacheln"][k] = {"erstes_mal_ms": erst, "zweites_mal_ms": zweit}
            print(f"       {k}: erstes Mal {erst:.0f} ms, zweites Mal {zweit:.0f} ms", flush=True)
            pruefe(zweit < GRENZE_KACHEL_MS, f"Kachel {k} beim zweiten Öffnen unter {GRENZE_KACHEL_MS:.0f} ms: {zweit:.0f} ms")

        # 3. Anordnen, groß, schließen, Umschalten
        ruf("view", kacheln=["modell", "zeichnung", "stueckliste", "druck"], kacheln_nur=True)
        time.sleep(1.5)
        bild("04-vier")
        f = lage()["flaeche"]
        pruefe(len(f["kacheln"]) == 4, "vier Kacheln")
        ms = pause(lambda: ruf("view", kachel_gross=2))
        ergebnis["umschalten"]["Kachel 2 groß"] = ms
        f = lage()["flaeche"]
        pruefe(f["gross"] == "zeichnung", f"Kachel 2 groß: {f['gross']}")
        text = ruf("status")
        pruefe("2 Zeichnung (groß)" in text, "status nennt die große Kachel")
        bild("05-gross")
        ms = pause(lambda: ruf("view", kachel_gross="aus"))
        ergebnis["umschalten"]["alle einordnen"] = ms
        ruf("view", kachel_zu=[3])
        f = lage()["flaeche"]
        pruefe(f["kacheln"] == ["modell", "zeichnung", "druck"] and f["gross"] is None, f"Kachel 3 geschlossen: {f['kacheln']}")
        for name_, modus in (("Werkstatt → Fokus", "fokus"), ("Fokus → Werkstatt", "werkstatt"),
                             ("Werkstatt → Fokus, 2. Mal", "fokus"), ("Fokus → Werkstatt, 2. Mal", "werkstatt")):
            ms = pause(lambda m=modus: ruf("view", modus=m), 0.8)
            ergebnis["umschalten"][name_] = ms
            pruefe(ms < GRENZE_UMSCHALTEN_MS, f"{name_}: {ms:.0f} ms")

        # 4. Blatt wechseln
        ruf("view", kacheln=["modell", "zeichnung"], kacheln_nur=True)
        time.sleep(1.5)
        f = lage()["flaeche"]
        print(f"       Blatt: {f.get('blatt')}", flush=True)
        ruf("view", blatt=2)
        time.sleep(0.8)
        f = lage()["flaeche"]
        pruefe(bool(f.get("blatt")) and f["blatt"]["nr"] == 2, f"Blatt 2 gewählt: {f.get('blatt')}")
        text = ruf("status")
        pruefe("Blatt 2 von" in text, "status nennt das Blatt")
        bild("06-blatt2")

        # 5. Zweite Ansicht: Hintergrund, Kamerabefehl
        ruf("view", kacheln=["modell", "ansicht"], kacheln_nur=True)
        time.sleep(2.0)
        vor = statistik(rt).get("zweite_ansicht", 0)
        pruefe(vor > 0, f"zweite Ansicht hat ein Bild ({vor})")
        ms = pause(lambda: ruf("view", zweite_ansicht="front"), 1.5)
        ergebnis["umschalten"]["zweite Ansicht: Richtung"] = ms
        nach = statistik(rt).get("zweite_ansicht", 0)
        pruefe(nach > vor, "andere Richtung rechnet neu")
        pruefe(lage()["flaeche"]["ansicht"] == "front", "Lagebild nennt die Richtung")
        teil = rt.status()["last_run"]["parts"][0]["name"]
        ms = pause(lambda: ruf("view", focus=[teil]), 2.0)
        ergebnis["umschalten"]["zweite Ansicht: Kamerabefehl"] = ms
        fokus = statistik(rt).get("zweite_ansicht", 0)
        pruefe(fokus > nach, "Kamerabefehl rechnet neu")
        pruefe(ms < GRENZE_UMSCHALTEN_MS * 3, f"Kamerabefehl mit zweiter Ansicht: {ms:.0f} ms (Fahrt des Viewers eingeschlossen)")
        bild("07-ansicht")
        ms = pause(lambda: rt.run(timeout_s=600), 6.0)
        rt.wait_idle(120)
        ergebnis["umschalten"]["Lauf mit zweiter Ansicht"] = ms
        print(f"       Lauf mit offener zweiter Ansicht: längste Pause {ms:.0f} ms", flush=True)
        ruf("view", fit=True)

        # 6. Rand: Fokus schmal, Zeitleiste auf Zuruf, Kacheln am Rand, zurück
        ruf("view", kacheln=["modell"], kacheln_nur=True, modus="fokus")
        time.sleep(0.6)
        ms = pause(lambda: ruf("view", rand="rechts"), 1.2)
        ergebnis["umschalten"]["an den Rand"] = ms
        l = lage()
        pruefe(l["flaeche"]["rand"] == "rechts" and l["viewport"]["breite"] <= 462,
               f"am rechten Rand, Viewer {l['viewport']['breite']} pt breit")
        text = ruf("status")
        pruefe("Fenster am rechten Rand" in text, "status nennt den Rand")
        bild("08-rand")
        ruf("view", zeitleiste=True)
        time.sleep(0.6)
        pruefe(lage()["flaeche"]["zeitleiste"] is True, "Zeitleiste auf Zuruf")
        bild("09-rand-zeitleiste")
        ruf("view", zeitleiste=False)
        ruf("view", kacheln=["druck"])
        time.sleep(1.2)
        f = lage()["flaeche"]
        pruefe(f["modus"] == "werkstatt" and f["rand"] == "rechts", f"Kachel am Rand: Werkstatt, Fenster bleibt schmal: {f}")
        bild("10-rand-druck")
        ruf("view", kacheln=["modell", "animation"], kacheln_nur=True)
        time.sleep(1.2)
        bild("11-rand-animation")
        ms = pause(lambda: ruf("view", rand="aus"), 1.2)
        ergebnis["umschalten"]["zurück vom Rand"] = ms
        f = lage()["flaeche"]
        pruefe(f["rand"] is None and f["modus"] == "werkstatt", f"zurück vom Rand: {f}")
        bild("12-animation")
        ruf("view", kacheln=["modell"], kacheln_nur=True, modus="fokus")
        text = ruf("animation", aktion="abspielen")
        time.sleep(1.0)
        a = lage().get("animation")
        print(f"       abspielen: {text[:120]} · Lagebild {a}", flush=True)
        if a and a.get("spielt"):
            bild("13-fokus-spielt")
            ruf("animation", aktion="abspielen", an=False)

        # Bauplan: erzeugen lassen, dann ansehen
        ruf("bauplan", aktion="zeigen")
        ruf("view", kacheln=["modell", "bauplan"], kacheln_nur=True)
        time.sleep(3)
        bild("14-bauplan")
        ruf("view", kachel_gross="bauplan")
        time.sleep(1.5)
        bild("15-bauplan-gross")
        ruf("view", kacheln=["modell", "zeichnung"], kacheln_nur=True, blatt=1)
        time.sleep(1.5)
        bild("16-zeichnung-gross")

        # 7. Benennen
        text = ruf("projekt", name="Kachel Selbsttest")
        ziel = arbeit / "Kachel Selbsttest"
        pruefe(str(ziel) in text, f"projekt(name=…) nennt den neuen Pfad: {text[:160]}")
        pruefe((ziel / "model.py").is_file() and not kopie.exists(), "Projekt liegt am neuen Ort")
        pruefe(rt.projekt_kurz()["name"] == "Kachel Selbsttest", "Kernel hat das Projekt am neuen Ort offen")
        res = rt.run(timeout_s=600)
        rt.wait_idle(120)
        time.sleep(2)
        teile = len(lage()["sichtbar"]) + len(lage()["verborgen"])
        pruefe(bool(res.get("ok")) and teile > 0, f"Lauf am neuen Ort, die App zeigt Teile ({teile})")
        durch = True
    finally:
        subprocess.run(["pkill", "-x", name], check=False)
        time.sleep(1)
        if log.exists():
            zeilen = [z for z in log.read_text(errors="replace").splitlines() if "[error]" in z or "[warning]" in z]
            ergebnis["app_meldungen"] = zeilen[-20:]
            print("\n".join(zeilen[-12:]), flush=True)
        if args.json:
            Path(args.json).write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
        if not durch:
            fehler.append("abgebrochen")
        print(f"\n{len(fehler)} Fehler: {fehler}" if fehler else "\nAlles bestanden", flush=True)
        if server is not None:
            server.stop()
        rt.close()
        shutil.rmtree(arbeit, ignore_errors=True)
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
