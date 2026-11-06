"""Selbsttest V2-5 Live mit echtem Kernel und echter App (Testvariante), immer an einer Kopie.

Der Kernel läuft hier im Prozess (mit Rechenprozess und MCP über HTTP), die Testvariante der App verbindet sich mit ihm
(``KEVCAD_KERNEL_EXTERNAL=1``), im Hintergrund und auf dem zweiten Monitor. Gezählt wird, was wirklich auf den Draht
geht (ganze Rahmen); was die Szene der App dabei getan hat, meldet ihr LAGE in Testvarianten (``statistik``).

    tools/fern.sh testbau live
    kernel/.venv/bin/python -u kernel/tools/live_selbsttest.py "build/Kev CAD Test live.app" \
        "$HOME/Documents/Kev CAD/Kugelschieber Variante B" --param laufrolle_l=90 --json live.json

Geprüft wird: Eine App mit allen Fähigkeiten verbindet sich; ein unveränderter Lauf bleibt unter 50 KB und baut in der App
nichts neu (kein Körper, kein Aufleuchten, keine Weitergabe an den Viewport); eine Parameteränderung schickt nur die
betroffenen Teile; der alte Wert kommt ohne Netze zurück; Selbstheilung über PARTS_REQ und NOCHMAL; ``status`` nimmt das
Lagebild der App; Antwortzeit von LAGE in Ruhe und während eines Laufs; die Agentenspur kommt an.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from messen import KATALOG, MCP_PORT, kopieren  # noqa: E402

ALLE = ["delta-1", "in-arbeit-1", "spur-1", "lage-1", "live-masse-1"]
GRENZE_KB = 50.0
LAGE_GRENZE_MS = 50.0


class Zaehler:
    """Rahmen, die die Verbindung zur App wirklich schreibt (Typ, Byte, Kopf)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rahmen: list[tuple[float, str, int, dict]] = []

    def einhaengen(self) -> None:
        from kevcad_kernel import app_link

        echt = app_link.encode_frame

        def zaehlen(header, payload=b""):
            data = echt(header, payload)
            with self.lock:
                self.rahmen.append((time.perf_counter(), str(header.get("type")), len(data), header))
            return data

        app_link.encode_frame = zaehlen

    def marke(self) -> int:
        with self.lock:
            return len(self.rahmen)

    def seit(self, marke: int) -> list[tuple[float, str, int, dict]]:
        with self.lock:
            return list(self.rahmen[marke:])


def ruhe(z: Zaehler, s: float = 3.0, bis: float = 120.0) -> None:
    """Warten, bis der Kernel ``s`` Sekunden nichts mehr geschickt hat."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < bis:
        with z.lock:
            letzte = z.rahmen[-1][0] if z.rahmen else t0
        if time.perf_counter() - letzte >= s:
            return
        time.sleep(0.2)


def statistik(rt) -> dict:
    """Zähler der App; unter Last kann ihr Hauptfaden gerade beschäftigt sein (die Antwortzeit misst ``lage_messen``)."""
    for _ in range(30):
        lage = rt.lagebild(1.0)
        if lage.get("quelle") == "app":
            return lage.get("statistik") or {}
    raise SystemExit(f"Kein LAGE von der App: {lage}")


def differenz(a: dict, b: dict) -> dict:
    return {k: b.get(k, 0) - a.get(k, 0) for k in ("koerper_gebaut", "aufleuchten", "weitergaben")}


def lauf(rt, z: Zaehler, name: str, params=None) -> dict:
    vor = statistik(rt)
    m = z.marke()
    t0 = time.perf_counter()
    res = rt.run(params=params, timeout_s=600)
    t_zurueck = time.perf_counter() - t0
    rt.wait_idle(120)
    ruhe(z, 10.0)  # Prüfung und Statik kommen nach dem Lauf und zählen mit
    frames = z.seit(m)
    nach = statistik(rt)
    arten: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for _, art, n, _ in frames:
        if art not in ("LAGE_REQ",):  # die Abfrage des Tests zählt nicht
            arten[art][0] += 1
            arten[art][1] += n
    gesamt = sum(v[1] for v in arten.values())
    neu = [h.get("name") for _, art, _, h in frames if art == "PART_UPSERT"]
    teile = [t for t, art, _, _ in frames if art in ("PART_SAME", "PART_UPSERT")]
    out = {
        "lauf": name, "run": res.get("run"), "ok": res.get("ok"), "kb": round(gesamt / 1000, 1),
        "zurueck_s": round(t_zurueck, 2), "teile_gleich": arten.get("PART_SAME", [0])[0], "teile_neu": len(neu),
        "neu": neu[:12], "letztes_teil_s": round(max(teile) - t0, 2) if teile else None, "app": differenz(vor, nach),
        "rahmen": {k: {"anzahl": v[0], "kb": round(v[1] / 1000, 1)} for k, v in sorted(arten.items(), key=lambda kv: -kv[1][1])},
        "teile_app": nach.get("teile"), "marken": nach.get("marken"),
    }
    print(f"{name}: Lauf {out['run']}, {out['kb']} KB, {out['teile_gleich']} PART_SAME, {out['teile_neu']} PART_UPSERT, "
          f"App {out['app']}, letztes Teil {out['letztes_teil_s']} s, zurück {out['zurueck_s']} s", flush=True)
    print("   " + ", ".join(f"{k} {v['anzahl']}× {v['kb']} KB" for k, v in out["rahmen"].items() if v["kb"] >= 0.3), flush=True)
    return out


def lage_messen(rt, anzahl: int) -> dict:
    zeiten, app = [], []
    for _ in range(anzahl):
        r = rt.lagebild(1.0)
        if r.get("quelle") == "app":
            zeiten.append(r["antwort_ms"])
            app.append(r["ms"])
        time.sleep(0.02)
    if not zeiten:
        return {"anzahl": 0}
    zeiten.sort()
    return {"anzahl": len(zeiten), "median_ms": zeiten[len(zeiten) // 2], "p95_ms": zeiten[int(len(zeiten) * 0.95)],
            "max_ms": zeiten[-1], "app_max_ms": max(app), "ohne_antwort": anzahl - len(zeiten)}


def foto(name: str, ziel: str) -> None:
    """Fensterbild der Testvariante (screencapture -l), die Fensternummer holt ein kleines Swift-Skript."""
    skript = Path(ziel).with_name("fenster.swift")
    skript.write_text(f"""import CoreGraphics
let l = CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as! [[String: Any]]
let w = l.filter {{ ($0["kCGWindowOwnerName"] as? String) == "{name}" && ($0["kCGWindowLayer"] as? Int) == 0 }}
    .max {{ a, b in
        let f = {{ (d: [String: Any]) -> Double in
            let r = d["kCGWindowBounds"] as? [String: Double] ?? [:]
            return (r["Width"] ?? 0) * (r["Height"] ?? 0)
        }}
        return f(a) < f(b)
    }}
print(w?["kCGWindowNumber"] ?? "")
""", encoding="utf-8")
    nummer = subprocess.run(["swift", str(skript)], capture_output=True, text=True).stdout.strip()
    if nummer:
        subprocess.run(["screencapture", "-l", nummer, "-o", "-x", ziel], check=False)
    print(f"Fensterbild: {ziel} (Fenster {nummer or 'nicht gefunden'})", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("app", help="Testvariante (Kev CAD Test ….app)")
    ap.add_argument("projekt", help="Projektordner (wird kopiert, nie verändert)")
    ap.add_argument("--param", default=None, help="NAME=WERT für den Lauf mit Parameteränderung")
    ap.add_argument("--katalog", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--behalten", action="store_true")
    ap.add_argument("--foto", default=None, help="Fensterbild zum eigenen Ansehen (PNG), Kevin bekommt es nicht")
    ap.add_argument("--nur-bild", default=None, help="nur Fensterbilder PFAD-1…3.png vor und nach den Läufen, keine Prüfungen")
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

    z = Zaehler()
    z.einhaengen()
    from kevcad_kernel.protocol import check_live_message
    from kevcad_kernel.runtime import KernelRuntime
    from kevcad_kernel.server import KevcadHTTPServer

    ergebnis: dict = {"projekt": projekt.name, "laeufe": [], "pruefungen": {}}
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
        subprocess.run(["open", "-g", "-n", "--env", "KEVCAD_KERNEL_EXTERNAL=1", "--stderr", str(log), str(app_pfad)], check=True)
        ende = time.monotonic() + 30
        while time.monotonic() < ende:
            conn = rt._link.connection
            if conn is not None and not conn.closed and conn.live.gemeldet:
                break
            time.sleep(0.1)
        else:
            raise SystemExit("App meldet sich nicht")
        faeh = sorted(conn.live.faehigkeiten)
        print(f"App verbunden: {faeh}", flush=True)
        pruefe(set(ALLE) <= set(faeh), "App meldet alle Fähigkeiten")
        time.sleep(3)  # die App legt ihr leeres Projekt an
        res = rt.project_open(str(kopie))
        if not res.get("ok"):
            raise SystemExit(f"Projekt nicht geöffnet: {res}")
        rt.wait_idle(60)
        time.sleep(1)

        if args.nur_bild:  # zum eigenen Ansehen: Bild vor und nach einem unveränderten Lauf und einer Änderung
            ruhe(z, 2.0, 60)
            rt.view_command("view", {"standard": "iso", "fit": True})
            time.sleep(3)
            foto(name, f"{args.nur_bild}-1.png")
            rt.run(timeout_s=600)
            rt.wait_idle(120)
            ruhe(z, 2.0, 60)
            foto(name, f"{args.nur_bild}-2.png")
            if args.param:
                pname, _, wert = args.param.partition("=")
                rt.run(params={pname: float(wert)}, timeout_s=600)
                rt.wait_idle(120)
                ruhe(z, 2.0, 60)
                foto(name, f"{args.nur_bild}-3.png")
            durch = True
            return 0

        kalt = lauf(rt, z, "kalt")
        ergebnis["laeufe"].append(kalt)
        teile = len(rt.scene.records())
        schuesse = kalt["teile_neu"] + kalt["teile_gleich"]  # model.py darf ein Teil mehrmals zeigen
        pruefe(kalt["teile_app"] == teile, f"alle {teile} Teile in der App")
        gleich = lauf(rt, z, "gleich")
        ergebnis["laeufe"].append(gleich)
        gleich2 = lauf(rt, z, "gleich")
        ergebnis["laeufe"].append(gleich2)
        pruefe(gleich2["kb"] < GRENZE_KB, f"unveränderter Lauf unter {GRENZE_KB:.0f} KB ({gleich2['kb']} KB)")
        pruefe(gleich2["teile_neu"] == 0 and gleich2["teile_gleich"] == schuesse, "alle Teile als PART_SAME")
        pruefe(gleich2["app"]["koerper_gebaut"] == 0 and gleich2["app"]["aufleuchten"] == 0,
               f"kein Teil flackert: nichts neu gebaut, nichts leuchtet auf ({gleich2['app']})")
        if (gleich2["letztes_teil_s"] or 9) < 1.9:  # länger dunkeln offene Teile ab (Last auf dem Rechner)
            pruefe(gleich2["app"]["weitergaben"] == 0, "nichts an den Viewport")

        if args.param:
            pname, _, wert = args.param.partition("=")
            m = re.search(rf'param\("{re.escape(pname)}",\s*([-0-9.]+)', (kopie / "model.py").read_text(encoding="utf-8"))
            alt = float(m.group(1)) if m else None
            neu = lauf(rt, z, f"param {pname}={wert}", {pname: float(wert)})
            ergebnis["laeufe"].append(neu)
            pruefe(0 < neu["teile_neu"] < teile, f"Parameteränderung schickt nur betroffene Teile ({neu['teile_neu']} von {teile})")
            pruefe(neu["app"]["koerper_gebaut"] == neu["teile_neu"], "die App baut genau diese Teile neu")
            pruefe(any(h.get("cmd") == "annotate" and (h.get("args") or {}).get("art") == "param"
                       for _, art, _, h in z.rahmen if art == "VIEW_CMD"), "geändertes Maß kommt ans Teil")
            if alt is not None:
                zurueck = lauf(rt, z, f"param {pname}={alt:g}", {pname: alt})
                ergebnis["laeufe"].append(zurueck)
                pruefe(zurueck["teile_neu"] == 0, "alter Wert kommt ohne Netze zurück")
                pruefe(zurueck["app"]["koerper_gebaut"] == neu["teile_neu"], "die App tauscht genau diese Teile aus dem Speicher")

        # Neue Version: Das Vorschaubild nimmt die Netze aus der Szene der App
        modell = kopie / "model.py"
        modell.write_text(modell.read_text(encoding="utf-8") + f"\n# Selbsttest {time.time():.0f}\n", encoding="utf-8")
        beginn = time.time()
        rt._ver_letztes_bild = 0.0  # sonst höchstens ein Bild alle drei Minuten
        m = z.marke()
        version = lauf(rt, z, "kommentar")
        ergebnis["laeufe"].append(version)
        bilder = [(h, n) for _, a, n, h in z.seit(m) if a == "VERSION_BILD_REQ"]
        aus_szene = sum(1 for h, _ in bilder for k in h.get("teile") or [] if k.get("aus_szene"))
        png = [p for p in (kopie / ".kevcad/versionen/bilder").glob("*.png") if p.stat().st_mtime >= beginn - 1]
        pruefe(bool(bilder) and aus_szene > 0,
               f"Versionsbild nimmt {aus_szene} Netze aus der Szene ({sum(n for _, n in bilder) / 1000:.1f} KB)")
        pruefe(bool(png) and png[0].stat().st_size > 2000, f"die App liefert das Vorschaubild ({len(png)} PNG)")

        # Selbstheilung am echten Paar
        conn = rt._link.connection
        name_teil = rt.scene.records()[0].name
        m = z.marke()
        conn.send({"type": "PART_SAME", "run": rt._run_no, "name": name_teil, "inhalt": "0" * 16})
        conn.send({"type": "WIE_ZUVOR", "art": "CHECK", "basis": 1, "setzen": [], "weg": []})
        ruhe(z, 1.0, 10)
        arten = [(a, h.get("name")) for _, a, _, h in z.seit(m)]
        pruefe(("PART_UPSERT", name_teil) in arten, "fehlender Inhalt: PARTS_REQ holt das Teil neu")
        pruefe(any(a == "CHECK" for a, _ in arten), "fehlende Basis: NOCHMAL holt die Nachricht neu")

        # Lagebild
        probe = rt.lagebild(1.0)
        roh = {k: v for k, v in probe.items() if k not in ("ok", "quelle", "antwort_ms", "statistik")}
        probleme = check_live_message({"type": "LAGE", "reply_to": "x", **roh})
        pruefe(not probleme, f"LAGE entspricht dem Vertrag {probleme or ''}")
        ruhe(z, 5.0)
        ruhig = lage_messen(rt, 100)
        ergebnis["lage_ruhig"] = ruhig
        print(f"LAGE in Ruhe: {ruhig}", flush=True)
        pruefe(ruhig.get("p95_ms", 1e9) < LAGE_GRENZE_MS, f"LAGE unter {LAGE_GRENZE_MS:.0f} ms (p95 {ruhig.get('p95_ms')} ms)")
        im_lauf: dict = {}
        t = threading.Thread(target=lambda: im_lauf.update(lage_messen(rt, 40)))
        t.start()
        rt.run(timeout_s=600)
        t.join()
        rt.wait_idle(120)
        ruhe(z)
        ergebnis["lage_im_lauf"] = im_lauf
        print(f"LAGE im Lauf: {im_lauf}", flush=True)

        # status über MCP nimmt das Lagebild; die Spur kommt an
        import anyio
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        async def status() -> str:
            http = create_mcp_http_client(headers={"x-claude-code-session-id": "selbsttest"})
            async with http:
                async with Client(streamable_http_client(server.url, http_client=http), mode="legacy", cache=None) as c:
                    r = await c.call_tool("status", {"absicht": "Selbsttest"})
            return "\n".join(getattr(b, "text", "") for b in r.content)

        vor = statistik(rt).get("spur", 0)
        t0 = time.perf_counter()
        text = anyio.run(status)
        ergebnis["status_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        ergebnis["status"] = text[:800]
        print(text[:800], flush=True)
        pruefe("Ansicht:" in text and "Sichtbar:" in text, "status nennt Kamera und Sichtbarkeit aus dem Lagebild")
        time.sleep(0.5)
        pruefe(statistik(rt).get("spur", 0) > vor, "Agentenspur kommt in der App an")

        if args.foto:  # zum eigenen Ansehen: laufender Schritt, Maß mit Ablauf, Hervorhebung
            rt.agent_schritt({"id": "foto-1", "werkzeug": "run", "text": "führt model.py aus",
                              "absicht": "Laufrolle auf 90 mm", "beginn": time.time() - 3})
            teil = rt.scene.records()[0]
            mitte = [(a + b) / 2 for a, b in zip(teil.bbox["min"], teil.bbox["max"])]
            rt.view_command("annotate", {"kind": "label", "points": [mitte], "text": "laufrolle_l 80 → 90 mm",
                                         "art": "param", "dauer_s": 8})
            rt.view_command("highlight", {"refs": [teil.name], "dauer_s": 8})
            time.sleep(2.5)
            foto(name, args.foto)
        durch = True
    finally:
        subprocess.run(["pkill", "-x", name], check=False)
        time.sleep(1)
        if log.exists():
            zeilen = [l for l in log.read_text(errors="replace").splitlines() if "[error]" in l or "[warning]" in l]
            ergebnis["app_meldungen"] = zeilen[-20:]
            print("\n".join(zeilen[-12:]), flush=True)
        if args.json:
            Path(args.json).write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
        if not durch:
            fehler.append("abgebrochen")
        print(f"\n{len(fehler)} Fehler: {fehler}" if fehler else "\nAlles bestanden", flush=True)
        if server is not None:
            server.stop()
        schluss = threading.Thread(target=rt.close, daemon=True)  # beendet den Rechenprozess; kann unter Last hängen
        schluss.start()
        schluss.join(15)
        if args.behalten:
            print(f"Arbeitsordner: {arbeit}", flush=True)
        else:
            shutil.rmtree(arbeit, ignore_errors=True)
    return 1 if fehler else 0


if __name__ == "__main__":
    # Ohne Warten auf Nachläufer (Pool, Rechenprozess, Server): Alles Nötige ist geschrieben
    os._exit(main())
