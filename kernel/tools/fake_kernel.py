"""Ersatz-Kernel für Tests der App ohne echten Kernel (AP3).

Spricht das Protokoll aus PROTOCOL.md über den Unix-Socket (nutzt kevcad_kernel/protocol.py dieses Repos), lauscht
wie der echte Kernel und lässt sich deshalb über KEVCAD_KERNEL_CMD in die App einsetzen:

    KEVCAD_KERNEL_CMD="'<repo>/kernel/.venv/bin/python' '<repo>/kernel/tools/fake_kernel.py' --demo-view"

Die App hängt `serve --socket <pfad> --port <port>` an. Ablauf:

- Nach dem Verbinden: HELLO, STATUS, PROJECT und alle bekannten Teile (wie der echte Kernel).
- Beim ersten Verbinden öffnet er ein Ersatzprojekt und spielt einen Lauf ab: RUN_START, STEP, PART_UPSERT mit
  kleinen Pausen (Teile aus den Protokoll-Testdateien, dazu eine fein vernetzte Kugel mit über 16.000 Dreiecken und
  ein Hilfsteil, das am Ende per PART_REMOVE verschwindet), RUN_END.
- RUN_REQ spielt den Lauf erneut ab, MEASURE_REQ bekommt Beispielwerte, EXPORT_REQ erfundene Pfade.
- Phase 2: nach RUN_END eine Stückliste (BOM, auch auf BOM_REQ) mit Zuschnitt, einem 3D-Druckteil (die Kugel aus
  PETG) und, solange die Inventar-Regel an ist (SETTINGS ``inventar_regel``), einem Verstoß (Grundplatte:
  PART_UPSERT ``inventar: "fehlt"``, RUN_END ``inventar_verstoesse``). CATALOG_REQ liefert einen kleinen Katalog mit
  allen drei Ebenen und zwei Vorschlägen von Claude (``status: "vorgeschlagen"``); CATALOG_SAVE und CATALOG_DELETE
  ändern ihn im Speicher und schreiben jede Änderung nach ``<out>/katalog-aenderungen.jsonl``. EXPORT_REQ mit
  ``bom_csv`` schreibt eine echte CSV-Datei. Mit --lager kommt ein Lagerteil (Vierkantrohr aus part_stock.frame) dazu.
- Mit --demo-view schickt er nach dem Lauf Ansichtsbefehle (VIEW_CMD) und Bildanfragen (SCREENSHOT_REQ) und
  speichert die Bilder der App als PNG (Vorgabe: <repo>/build/fake_kernel/).
- Phase 3 mit --zukauf: ein verbautes Zukaufteil „Rollwagen (vereinfacht)“ (PART_UPSERT ``zukauf``, erst
  ``cad: "vereinfacht"``, Name wie beim echten Kernel), Stücklistenzeile ``art: "zukaufteil"`` wie bom_zukauf.frame,
  zwei Zukaufteile im Katalog (eins frei, eins von Claude vorgeschlagen). ZUKAUF_NEU legt das Teil im Katalog an (ACK,
  Ablehnung als ACK ok false), dann folgen ZUKAUF_STATUS ``angelegt`` und ``wartet_auf_cad`` mit ``cad_links``.
  DOWNLOAD_SEEN wird nach ``<out>/downloads.jsonl`` geschrieben. ZUKAUF_CAD antwortet mit ACK und ZUKAUF_STATUS
  ``importiert``; für den Rollwagen rechnet er danach mit ``cad: "hersteller"`` neu (Teil heißt dann „Rollwagen“).
  Eine leere oder fehlende Datei ergibt ``fehler`` und, wenn das Teil wartete, wieder ``wartet_auf_cad``. Nach dem
  Verbinden schickt er ZUKAUF_STATUS (mit ``name``) für jedes Teil, das noch auf CAD wartet.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
# Immer die protocol.py dieses Repos nehmen, auch wenn eine andere Umgebung das Paket installiert hat
sys.path.insert(0, str(HERE.parents[1] / "src"))

from kevcad_kernel.protocol import FrameReader, PartGeometry, encode_frame, pack_part, unpack_part  # noqa: E402

FIXTURES = REPO / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def log(text: str) -> None:
    print(f"[ersatz-kernel] {text}", file=sys.stderr, flush=True)


def de(value: float, digits: int = 3) -> str:
    """Zahl im deutschen Format (Komma)."""
    s = f"{value:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------------------------------------------------
# Teile


def read_fixture(name: str) -> tuple[dict[str, Any], bytes]:
    reader = FrameReader()
    frames = reader.feed((FIXTURES / name).read_bytes())
    assert len(frames) == 1, name
    return frames[0]


def sphere_part(radius: float = 15.0, center=(-40.0, 0.0, 0.0), nlat: int = 110, nlon: int = 180):
    """UV-Kugel wie build123d: eine Fläche, eine Nahtkante (Halbkreis), zwei Punkte an den Polen."""
    c = np.asarray(center, dtype=np.float64)
    theta = np.linspace(0.0, math.pi, nlat + 1)  # 0 = Nordpol (+Z), pi = Südpol
    phi = np.linspace(0.0, 2 * math.pi, nlon + 1)
    th, ph = np.meshgrid(theta, phi, indexing="ij")
    n = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], axis=-1).reshape(-1, 3)
    pos = c + radius * n
    tris = []
    row = nlon + 1
    for i in range(nlat):
        for j in range(nlon):
            a = i * row + j
            b = a + row
            if i != 0:
                tris.append((a, b, a + 1))
            if i != nlat - 1:
                tris.append((a + 1, b, b + 1))
    tris = np.asarray(tris, dtype=np.uint32)
    seam = pos[np.arange(nlat + 1) * row]  # Meridian bei phi = 0 vom Nord- zum Südpol
    geo = PartGeometry(
        positions=pos.astype(np.float32),
        normals=n.astype(np.float32),
        triangles=tris,
        tri_face=np.zeros(len(tris), dtype=np.int32),
        edge_points=seam.astype(np.float32),
        edge_offsets=np.asarray([0, len(seam)], dtype=np.uint32),
        vertices=np.asarray([c + (0, 0, radius), c - (0, 0, radius)], dtype=np.float32),
        faces=[{"t": "sphere", "a": round(4 * math.pi * radius**2, 4), "r": radius, "c": [float(x) for x in c]}],
        edges=[{"t": "circle", "l": round(math.pi * radius, 4), "r": radius, "c": [float(x) for x in c]}],
    )
    lo, hi = c - radius, c + radius
    bbox = {"min": [float(x) for x in lo], "max": [float(x) for x in hi]}
    props = {
        "volume": round(4 / 3 * math.pi * radius**3, 4),
        "area": round(4 * math.pi * radius**2, 4),
        "center": [float(x) for x in c],
    }
    return geo, bbox, props


class Parts:
    """Die Teile des Ersatzlaufs als (Name, Schritt, Kopf ohne seq/run, Nutzlast)."""

    def __init__(self, lager: bool = False, zukauf: bool = False) -> None:
        self.items: list[tuple[str, str, dict[str, Any], bytes]] = []
        box_h, box_p = read_fixture("part_box.frame")
        cyl_h, cyl_p = read_fixture("part_cylinder.frame")
        self.items.append(("Grundplatte", "Grundplatte", box_h, box_p))
        self.items.append(("Halter/Bolzen", "Bolzen", cyl_h, cyl_p))

        geo, bbox, props = sphere_part()
        sph_h, sph_p = pack_part(run=0, name="Kugel", geometry=geo, color=(0.35, 0.6, 0.85, 1.0), bbox=bbox,
                                 props=props, material=None)
        self.items.append(("Kugel", "Kugel (fein vernetzt)", sph_h, sph_p))
        log(f"Kugel: {sph_h['counts']['tri']} Dreiecke, {len(sph_p) // 1024} kB")

        # Hilfsteil: die Grundplatte, um 30 mm in y verschoben (verschwindet am Ende des Laufs wieder)
        arrays = unpack_part(box_h, box_p)
        g = PartGeometry(
            positions=arrays["positions"] + np.float32([0, 30, 0]),
            normals=arrays["normals"], triangles=arrays["triangles"], tri_face=arrays["tri_face"],
            edge_points=arrays["edge_points"] + np.float32([0, 30, 0]), edge_offsets=arrays["edge_offsets"],
            vertices=arrays["vertices"] + np.float32([0, 30, 0]), faces=box_h["faces"], edges=box_h["edges"],
        )
        aux_h, aux_p = pack_part(run=0, name="Hilfsteil", geometry=g, color=(0.6, 0.6, 0.6, 1.0),
                                 bbox={"min": [-5, 20, -15], "max": [5, 40, 15]},
                                 props={"volume": 6000.0, "area": 2200.0, "center": [0, 30, 0]})
        self.items.append(("Hilfsteil", "Hilfsteil", aux_h, aux_p))

        # Phase 2: die Kugel ist ein 3D-Druckteil aus PETG
        for _, _, h, _ in self.items:
            if h["name"] == "Kugel":
                h["material"] = "petg-schwarz"
        if zukauf:
            # Zukaufteil: die Grundplatte als Ersatzkörper, per transform hinter die anderen Teile gerückt
            zk_h = dict(box_h)
            zk_h["name"] = "Rollwagen"
            zk_h["color"] = [0.55, 0.62, 0.72, 1.0]
            zk_h["material"] = None
            zk_h["transform"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 45, 0, 1]
            self.items.append(("Rollwagen", "Zukaufteil verbauen", zk_h, box_p))
        if lager:
            # Lagerteil aus der Testdatei, per transform neben die anderen Teile gerückt (spaltenweise Matrix)
            st_h, st_p = read_fixture("part_stock.frame")
            st_h = dict(st_h)
            st_h["transform"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -90, 0, -15, 1]
            self.items.insert(2, ("Gestell/Bein vorn links", "Lagerteil verbauen", st_h, st_p))

    def header(self, name: str) -> dict[str, Any] | None:
        for n, _, h, _ in self.items:
            if n == name:
                return h
        return None


# --------------------------------------------------------------------------------------------------------------------
# Server


def initial_catalog() -> dict[str, list[dict[str, Any]]]:
    """Kleiner Katalog nach KATALOG.md: alle drei Ebenen, zwei Vorschläge von Claude, ein Filament."""
    def preis(unit: str, v: float, quelle: str = "Richtwert") -> dict[str, Any]:
        return {unit: v, "quelle": quelle, "stand": "2026-10"}

    materials = [
        {"id": "stahl-s235", "name": "Stahl S235", "gruppe": "Stahl", "dichte": 7.85, "farbe": "#8A9099",
         "preis_je_kg": 2.4, "preis_quelle": "Richtwert", "preis_stand": "2026-10", "aliase": ["stahl"],
         "ebene": "mitgeliefert"},
        {"id": "aluminium-6060", "name": "Aluminium EN AW-6060", "gruppe": "Aluminium", "dichte": 2.7,
         "farbe": "#C9CDD2", "preis_je_kg": 7.5, "preis_quelle": "Richtwert", "preis_stand": "2026-10",
         "ebene": "mitgeliefert"},
        {"id": "petg-schwarz", "name": "PETG schwarz", "gruppe": "Kunststoff", "dichte": 1.27, "farbe": "#34373B",
         "druckbar": True, "preis_je_kg": 24, "preis_quelle": "Filament", "preis_stand": "2026-10", "ebene": "eigen",
         "status": "frei"},
        {"id": "pla-grau", "name": "PLA grau", "gruppe": "Kunststoff", "dichte": 1.24, "farbe": "#8E9196",
         "druckbar": True, "preis_je_kg": 20, "preis_quelle": "Claude", "preis_stand": "2026-10", "ebene": "eigen",
         "status": "vorgeschlagen"},
    ]
    items = [
        {"id": "vierkantrohr-en10219-40x40x3", "art": "vierkantrohr", "name": "Vierkantrohr 40 × 40 × 3",
         "norm": "DIN EN 10219", "masse": {"a": 40, "s": 3}, "material": "stahl-s235", "kg_je_m": 3.41,
         "stangenlaenge": 6000, "preis": preis("je_m", 8.0), "tags": ["quadrat"], "ebene": "mitgeliefert"},
        {"id": "rund-en10060-10", "art": "rund", "name": "Rundstahl Ø 10", "norm": "DIN EN 10060",
         "masse": {"d": 10}, "material": "stahl-s235", "kg_je_m": 0.617, "stangenlaenge": 6000,
         "preis": preis("je_m", 1.5), "ebene": "mitgeliefert"},
        {"id": "rohr-edelstahl-33.7x2", "art": "rohr", "name": "Edelstahlrohr 33,7 × 2", "norm": "ISO 1127",
         "masse": {"d": 33.7, "s": 2.0}, "material": "stahl-s235", "preis": preis("je_m", 14.5, "Kevin"),
         "ebene": "eigen", "status": "frei"},
        {"id": "winkel-alu-30x30x3", "art": "winkel", "name": "Alu-Winkel 30 × 30 × 3", "masse": {"a": 30, "b": 30, "s": 3},
         "material": "aluminium-6060", "kg_je_m": 0.47, "stangenlaenge": 3000, "preis": preis("je_m", 6.9, "Claude"),
         "ebene": "eigen", "status": "vorgeschlagen"},
        {"id": "platte-siebdruck-21", "art": "platte", "name": "Siebdruckplatte 21 mm", "masse": {"s": 21},
         "material": "aluminium-6060", "platte": [2500, 1250], "preis": preis("je_m2", 39), "ebene": "projekt"},
    ]
    return {"materials": materials, "items": items}


ROLLWAGEN_URL = "https://www.beispiel-shop.de/p/alutec-05200"


def zukauf_catalog() -> list[dict[str, Any]]:
    """Phase 3: ein freigegebenes Zukaufteil im Projekt und ein Vorschlag von Claude (KATALOG.md, Zukaufteil)."""
    return [
        {"id": "alutec-05200", "art": "zukaufteil", "name": "ALUTEC Transportroller 05200", "hersteller": "ALUTEC",
         "mpn": "05200", "gtin": "4005187052008", "url": ROLLWAGEN_URL,
         "preis": {"je_stueck": 24.99, "waehrung": "EUR", "brutto": True, "stand": "2026-10-21",
                   "quelle": ROLLWAGEN_URL},
         "masse": {"l": 610, "b": 410, "h": 128}, "gewicht": 1800,
         "ersatz": {"form": "quader", "masse": {"l": 610, "b": 410, "h": 128}},
         "einbaupunkt": {"pos": [0, 0, 0], "richtung": [0, 0, 1], "hinweis": "Mitte der Aufstandsfläche"},
         "status": "frei", "ebene": "projekt"},
        {"id": "hettich-9258946", "art": "zukaufteil", "name": "Hettich Quadro V6 Vollauszug 500 mm",
         "hersteller": "Hettich", "mpn": "9258946", "url": "https://www.beispiel-shop.de/p/hettich-9258946",
         "preis": {"je_stueck": 18.4, "waehrung": "EUR", "brutto": True, "stand": "2026-10-21"},
         "masse": {"l": 500, "b": 43, "h": 45}, "ersatz": {"form": "quader", "masse": {"l": 500, "b": 43, "h": 45}},
         "status": "vorgeschlagen", "vorgeschlagen_von": "agent", "vorgeschlagen_am": "2026-10-21",
         "ebene": "projekt"},
    ]


class FakeKernel:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = Path(args.out).expanduser().resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.parts = Parts(lager=args.lager, zukauf=args.zukauf)
        self.inventar_regel = True
        self.catalog = initial_catalog()
        # Phase 3: Zukaufteile
        self.rollwagen_cad = "vereinfacht"
        self.waiting: dict[str, dict[str, Any]] = {}  # Zukaufteil-id → letzter ZUKAUF_STATUS (wartet_auf_cad)
        if args.zukauf:
            self.catalog["items"] += zukauf_catalog()
        self.last_bom: dict[str, Any] | None = None
        self.conn: socket.socket | None = None
        self.send_lock = threading.Lock()
        self.seq = 0
        self.run_no = 0
        self.current: dict[str, tuple[dict[str, Any], bytes]] = {}  # gezeigte Teile (für Wiederverbinden)
        self.project: dict[str, str] | None = None
        self.settings = {"auto_run": True, "slow_ms": 0}
        self.running = threading.Lock()
        self.acks: dict[str, threading.Event] = {}
        self.ack_results: dict[str, dict[str, Any]] = {}
        self.shot_names: dict[str, str] = {}
        self.first_connection = True
        self.demo_started = False
        self.req = 0

    # Senden ---------------------------------------------------------------------------------------------------------

    def send(self, header: dict[str, Any], payload: bytes = b"") -> None:
        conn = self.conn
        if conn is None:
            return
        with self.send_lock:
            self.seq += 1
            header = dict(header)
            header["seq"] = self.seq
            try:
                conn.sendall(encode_frame(header, payload))
            except OSError as e:
                log(f"Senden fehlgeschlagen: {e}")

    def next_id(self) -> str:
        self.req += 1
        return f"k-{self.req}"

    def view(self, cmd: str, args: dict[str, Any], wait: float = 5.0) -> dict[str, Any] | None:
        """VIEW_CMD schicken und auf das ACK warten."""
        rid = self.next_id()
        ev = threading.Event()
        self.acks[rid] = ev
        self.send({"type": "VIEW_CMD", "id": rid, "cmd": cmd, "args": args})
        if not ev.wait(wait):
            log(f"VIEW_CMD {cmd}: kein ACK")
            return None
        res = self.ack_results.pop(rid, {})
        log(f"VIEW_CMD {cmd}: ok={res.get('ok')} {res.get('message') or ''}")
        return res

    def screenshot(self, name: str, **kw: Any) -> bool:
        rid = self.next_id()
        ev = threading.Event()
        self.acks[rid] = ev
        self.shot_names[rid] = name
        req = {"type": "SCREENSHOT_REQ", "id": rid, "width": kw.get("width", 1280), "height": kw.get("height", 800),
               "source": kw.get("source", "current"), "view": kw.get("view"),
               "hide_overlays": kw.get("hide_overlays", False)}
        t0 = time.perf_counter()
        self.send(req)
        ok = ev.wait(15)
        log(f"SCREENSHOT {name}: {'da' if ok else 'keine Antwort'} nach {(time.perf_counter() - t0) * 1000:.0f} ms")
        return ok

    # Projekt und Lauf ---------------------------------------------------------------------------------------------

    def open_project(self, path: str, reply_to: str | None = None) -> None:
        p = Path(path)
        self.project = {"path": str(p), "name": p.name, "model": str(p / "model.py"),
                        "inventar_regel": self.inventar_regel}
        msg = {"type": "PROJECT", **self.project}
        if reply_to:
            msg["reply_to"] = reply_to
        self.current.clear()
        self.send(msg)

    def start_run(self, slow_ms: int | None = None) -> None:
        if not self.running.acquire(blocking=False):
            log("Lauf läuft schon")
            return
        threading.Thread(target=self._run, args=(slow_ms,), daemon=True).start()

    def _run(self, slow_ms: int | None) -> None:
        try:
            self.run_no += 1
            run = self.run_no
            slow = self.settings.get("slow_ms", 0) if slow_ms is None else slow_ms
            pause = self.args.pause + slow / 1000
            t0 = time.perf_counter()
            self.send({"type": "STATUS", "state": "busy", "message": None})
            self.send({"type": "RUN_START", "run": run, "file_hash": f"ersatz{run}", "params": {"breite": 120},
                       "slow_ms": slow})
            for i, (name, step, header, payload) in enumerate(self.parts.items, start=1):
                self.send({"type": "STEP", "run": run, "index": i, "text": step})
                time.sleep(pause)
                h = dict(header)
                h["run"] = run
                h["inventar"] = "fehlt" if name in self.violations() else "ok"
                if name == "Rollwagen":
                    h["zukauf"] = {"id": "alutec-05200", "hersteller": "ALUTEC", "mpn": "05200",
                                   "cad": self.rollwagen_cad, "preis": 24.99, "url": ROLLWAGEN_URL}
                    # wie der echte Kernel: Ersatzkörper heißen „… (vereinfacht)“; der andere Name verschwindet
                    name = self.rollwagen_name()
                    h["name"] = name
                    for alt in ("Rollwagen", "Rollwagen (vereinfacht)"):
                        if alt != name and self.current.pop(alt, None) is not None:
                            self.send({"type": "PART_REMOVE", "run": run, "name": alt})
                self.current[name] = (h, payload)
                self.send(h, payload)
            time.sleep(pause)
            self.current.pop("Hilfsteil", None)
            self.send({"type": "PART_REMOVE", "run": run, "name": "Hilfsteil"})
            tri = sum(h["counts"]["tri"] for h, _ in self.current.values())
            self.send({"type": "RUN_END", "run": run, "duration_ms": int((time.perf_counter() - t0) * 1000),
                       "parts": len(self.current), "triangles": tri, "warnings": [], "params": {"breite": 120},
                       "inventar_verstoesse": self.violations()})
            self.last_bom = self.bom(run)
            self.send({"type": "BOM", **self.last_bom})
            self.send({"type": "STATUS", "state": "ready", "message": None})
            log(f"Lauf {run} fertig: {len(self.current)} Teile, {tri} Dreiecke")
        finally:
            self.running.release()
        if self.args.demo_view and not self.demo_started:
            self.demo_started = True
            threading.Thread(target=self.demo_view, daemon=True).start()

    # Vorführung der Ansichtsbefehle ----------------------------------------------------------------------------------

    def demo_view(self) -> None:
        time.sleep(1.0)
        self.send({"type": "AGENT", "connected": True, "activity": "prüft die Ansicht"})
        self.view("view", {"standard": "iso", "projection": "perspective", "display": "shaded_edges", "fit": True})
        time.sleep(0.6)
        self.view("highlight", {"refs": ["Grundplatte#f5", "Halter/Bolzen#e0"], "color": [0.1, 0.75, 0.3, 1.0],
                                "label": "Deckfläche", "clear": True})
        self.view("annotate", {"kind": "dimension", "points": [[5, 0, 15], [25, 0, 15]],
                               "text": "Abstand 20,000 mm (dx 20,000)", "id": "m1"})
        self.view("annotate", {"kind": "label", "points": [[-40, 0, 15]], "text": "Kugel: 3 Körper", "id": "l1"})
        self.view("highlight", {"refs": ["Kugel#f0", "Gibt/Es/Nicht"], "color": None, "label": None,
                                "clear": False})
        self.view("focus", {"refs": ["Halter/Bolzen"], "animate": True})
        time.sleep(0.8)
        self.view("view", {"standard": "iso", "projection": None, "display": None, "fit": True})
        time.sleep(0.8)
        self.screenshot("bild_aktuell")
        self.view("section", {"enabled": True, "axis": "y", "offset": 0})
        time.sleep(0.3)
        self.screenshot("bild_schnitt")
        self.view("section", {"enabled": False})
        self.view("explode", {"factor": 0.8})
        time.sleep(0.3)
        self.screenshot("bild_explosion")
        self.view("explode", {"factor": 0})
        self.screenshot("bild_oben_offscreen", source="offscreen", view="top", width=1000, height=800,
                        hide_overlays=False)
        self.view("view", {"standard": "front", "projection": "orthographic", "display": "xray", "fit": True})
        time.sleep(0.6)
        self.screenshot("bild_vorn_roentgen", width=1000, height=700)
        self.view("view", {"standard": "iso_back_left", "projection": "perspective", "display": "wireframe",
                           "fit": True})
        time.sleep(0.6)
        self.screenshot("bild_hinten_links_drahtgitter", width=1000, height=700, hide_overlays=True)
        self.view("view", {"standard": "iso", "projection": "perspective", "display": "shaded_edges", "fit": True})
        time.sleep(0.6)
        self.view("visibility", {"mode": "hide", "refs": ["Kugel"]})
        time.sleep(0.4)
        self.view("visibility", {"mode": "show_all", "refs": None})
        self.view("xyz", {})  # unbekannter Befehl: die App antwortet mit ok=false
        self.send({"type": "AGENT", "connected": True, "activity": None})
        (self.out / "fertig.txt").write_text("Vorführung abgeschlossen\n")
        log("Vorführung abgeschlossen")

    # Empfang ------------------------------------------------------------------------------------------------------

    def handle(self, header: dict[str, Any], payload: bytes) -> None:
        t = header.get("type")
        if t == "HELLO_APP":
            log(f"App verbunden: {header.get('bundle_id')} {header.get('app_version')}")
        elif t == "SETTINGS":
            self.settings.update({k: header[k] for k in ("auto_run", "slow_ms") if k in header})
            if isinstance(header.get("inventar_regel"), bool):
                self.inventar_regel = header["inventar_regel"]
                if self.project:
                    self.project["inventar_regel"] = self.inventar_regel
            log(f"Einstellungen: {self.settings}, Inventar-Regel {'an' if self.inventar_regel else 'aus'}")
        elif t in ("PROJECT_OPEN", "PROJECT_NEW"):
            self.open_project(header["path"], reply_to=header.get("id"))
            if self.settings.get("auto_run", True):
                self.start_run()
        elif t == "RUN_REQ":
            self.send({"type": "ACK", "reply_to": header.get("id"), "ok": True, "message": None})
            self.start_run(header.get("slow_ms") or None)
        elif t == "MEASURE_REQ":
            self.send({"type": "MEASURE_RES", "reply_to": header.get("id"), "result": self.measure(header)})
        elif t == "SELECTION":
            log(f"Auswahl (Lauf {header.get('run')}): {header.get('refs')}")
        elif t == "EXPORT_REQ":
            base = Path(self.project["path"]) if self.project else self.out
            files = []
            for f in header.get("formats", []):
                if f == "bom_csv":
                    files.append(str(self.write_bom_csv(base)))
                else:
                    files.append(str(base / "output" / f"model.{f}"))
            self.send({"type": "EXPORT_RES", "reply_to": header.get("id"), "files": files})
        elif t == "BOM_REQ":
            bom = self.last_bom or self.bom(self.run_no)
            self.send({"type": "BOM", "reply_to": header.get("id"), **bom})
        elif t == "CATALOG_REQ":
            self.send({"type": "CATALOG", "reply_to": header.get("id"),
                       **self.catalog_view(header.get("query"), header.get("art"))})
        elif t == "CATALOG_SAVE":
            self.catalog_save(header)
        elif t == "CATALOG_DELETE":
            self.catalog_delete(header)
        elif t == "ZUKAUF_NEU":
            self.zukauf_neu(header)
        elif t == "DOWNLOAD_SEEN":
            with (self.out / "downloads.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({k: header.get(k) for k in ("pfad", "groesse", "zeit")}, ensure_ascii=False) + "\n")
            log(f"DOWNLOAD_SEEN {header.get('pfad')} ({header.get('groesse')} Byte, {header.get('zeit')})")
        elif t == "ZUKAUF_CAD":
            self.zukauf_cad(header)
        elif t == "SCREENSHOT_RES":
            rid = header.get("reply_to", "")
            name = self.shot_names.pop(rid, f"bild_{rid}")
            if header.get("ok") and payload:
                (self.out / f"{name}.png").write_bytes(payload)
            meta = {k: v for k, v in header.items() if k not in ("type", "seq")}
            (self.out / f"{name}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
            log(f"Bild {name}: {header.get('width')} × {header.get('height')}, {len(payload) // 1024} kB, "
                f"mm/px {header.get('mm_per_px')}")
            ev = self.acks.pop(rid, None)
            if ev:
                ev.set()
        elif t == "ACK":
            rid = header.get("reply_to", "")
            self.ack_results[rid] = header
            ev = self.acks.pop(rid, None)
            if ev:
                ev.set()
        else:
            log(f"Unbekannte Nachricht {t}")

    # Phase 2: Stückliste, Katalog ------------------------------------------------------------------------------

    def violations(self) -> list[str]:
        """Teile, die die Inventar-Regel verletzen: hier immer die frei modellierte Grundplatte."""
        return ["Grundplatte"] if self.inventar_regel else []

    def bom(self, run: int) -> dict[str, Any]:
        names = set(self.current) or {n for n, _, _, _ in self.parts.items if n != "Hilfsteil"}
        lines: list[dict[str, Any]] = []
        cuts: list[dict[str, Any]] = []
        warnings: list[str] = []
        if "Gestell/Bein vorn links" in names:
            lines.append({"art": "vierkantrohr", "stock_id": "vierkantrohr-en10219-40x40x3",
                          "benennung": "Vierkantrohr 40 × 40 × 3", "norm": "DIN EN 10219", "material": "Stahl S235",
                          "laenge": 882.0, "gehrung": [0, 45], "masse_text": "882 mm", "anzahl": 1, "kg_je": 2.98,
                          "kg": 2.98, "preis_je": 7.06, "preis": 7.06, "teile": ["Gestell/Bein vorn links"],
                          "eigenteil": False})
            cuts.append({"stock_id": "vierkantrohr-en10219-40x40x3", "benennung": "Vierkantrohr 40 × 40 × 3",
                         "stangenlaenge": 6000, "saegeschnitt": 3, "stangen": [[882]], "verschnitt_prozent": 85.3})
        if "Halter/Bolzen" in names:
            lines.append({"art": "rund", "stock_id": "rund-en10060-10", "benennung": "Rundstahl Ø 10",
                          "norm": "DIN EN 10060", "material": "Stahl S235", "laenge": 20.0, "gehrung": [0, 0],
                          "masse_text": "20 mm", "anzahl": 1, "kg_je": 0.012, "kg": 0.012, "preis_je": 0.03,
                          "preis": 0.03, "teile": ["Halter/Bolzen"], "eigenteil": False})
            cuts.append({"stock_id": "rund-en10060-10", "benennung": "Rundstahl Ø 10", "stangenlaenge": 6000,
                         "saegeschnitt": 3, "stangen": [[20]], "verschnitt_prozent": 99.6})
        if "Kugel" in names:
            kg = round(4 / 3 * math.pi * 15 ** 3 / 1e6 * 1.27, 3)
            lines.append({"art": "druckteil", "stock_id": None, "benennung": "Kugel", "material": "PETG schwarz",
                          "laenge": None, "gehrung": [0, 0], "masse_text": "Ø 30 mm", "anzahl": 1, "kg_je": kg,
                          "kg": kg, "preis_je": round(kg * 24, 2), "preis": round(kg * 24, 2), "teile": ["Kugel"],
                          "eigenteil": False})
        if "Grundplatte" in names:
            if self.inventar_regel:
                warnings.append("Grundplatte: nicht aus dem Inventar (weder Lagerteil noch 3D-Druckteil)")
            else:
                lines.append({"art": "eigenteil", "stock_id": None, "benennung": "Grundplatte", "material": "Aluminium",
                              "laenge": None, "gehrung": [0, 0], "masse_text": "10 × 20 × 30 mm", "anzahl": 1,
                              "kg_je": 0.016, "kg": 0.016, "preis_je": 0.12, "preis": 0.12, "teile": ["Grundplatte"],
                              "eigenteil": True})
        if names & {"Rollwagen", "Rollwagen (vereinfacht)"}:
            # Zeile wie bom_zukauf.frame des echten Kernels
            simple = self.rollwagen_cad == "vereinfacht"
            lines.append({"art": "zukaufteil", "stock_id": "alutec-05200", "benennung": "ALUTEC Transportroller 05200",
                          "norm": None, "material": None, "laenge": None, "gehrung": [0, 0],
                          "masse_text": "610 × 410 × 128 mm", "anzahl": 1, "kg_je": 1.8, "kg": 1.8, "preis_je": 24.99,
                          "preis": 24.99, "teile": [self.rollwagen_name()], "eigenteil": False, "hersteller": "ALUTEC",
                          "mpn": "05200", "gtin": "4005187052008", "url": ROLLWAGEN_URL,
                          "bild": "https://www.beispiel-shop.de/bilder/05200.jpg",
                          "preis_stand": "2026-10-21", "preis_brutto": True,
                          "cad_quelle": "keins" if simple else "download", "vereinfacht": simple})
        for i, line in enumerate(lines, start=1):
            line["pos"] = i
        kg = round(sum(line["kg"] or 0 for line in lines), 3)
        preis = round(sum(line["preis"] or 0 for line in lines), 2)
        hinweis = "Richtpreise, Stand 2026-10"
        if any(line["art"] == "zukaufteil" for line in lines):
            hinweis += "; Zukaufteile zum Shoppreis brutto"
        return {"run": run, "lines": lines, "cuts": cuts, "warnings": warnings,
                "totals": {"kg": kg, "preis": preis, "positionen": len(lines),
                           "teile": sum(line["anzahl"] for line in lines),
                           "preis_hinweis": hinweis + " (Ersatz-Kernel)"}}

    def write_bom_csv(self, base: Path) -> Path:
        bom = self.last_bom or self.bom(self.run_no)
        out = base / "output"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{base.name}-stueckliste.csv"
        rows = ["Pos;Benennung;Maß;Gehrung;Material;Anzahl;Gewicht kg;Preis €"]
        for line in bom["lines"]:
            g = line.get("gehrung") or [0, 0]
            rows.append(";".join([str(line["pos"]), line["benennung"], line["masse_text"],
                                  "" if g == [0, 0] else f"{g[0]}° / {g[1]}°", line.get("material") or "",
                                  str(line["anzahl"]), de(line.get("kg") or 0, 3), de(line.get("preis") or 0, 2)]))
        path.write_text("\ufeff" + "\n".join(rows) + "\n", encoding="utf-8")
        log(f"Stückliste als CSV: {path}")
        return path

    def catalog_view(self, query: str | None, art: str | None) -> dict[str, Any]:
        q = (query or "").lower().split()

        def hit(entry: dict[str, Any]) -> bool:
            text = json.dumps(entry, ensure_ascii=False).lower()
            return all(w in text for w in q)

        items = [e for e in self.catalog["items"] if (not art or e.get("art") == art) and hit(e)]
        materials = [m for m in self.catalog["materials"] if hit(m)]
        arten = sorted({e.get("art") for e in self.catalog["items"]})
        return {"materials": materials, "items": items, "arten": arten}

    def catalog_save(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        kind = header.get("kind")
        entry = dict(header.get("entry") or {})
        ebene = header.get("ebene")
        need = ["id", "art", "name", "masse", "material"] if kind == "teil" else ["id", "name", "gruppe", "dichte", "farbe"]
        missing = [k for k in need if entry.get(k) in (None, "", {})]
        if kind not in ("teil", "material"):
            self.send({"type": "ERROR", "reply_to": rid, "message": f"Unbekannte Art {kind!r}"})
        elif ebene not in ("eigen", "projekt"):
            self.send({"type": "ERROR", "reply_to": rid, "message": "Nur in den eigenen oder den Projektkatalog"})
        elif missing:
            self.send({"type": "ERROR", "reply_to": rid, "message": "Pflichtfelder fehlen: " + ", ".join(missing)})
        else:
            entry["ebene"] = ebene
            entry.setdefault("status", "frei")
            key = "items" if kind == "teil" else "materials"
            self.catalog[key] = [e for e in self.catalog[key] if e.get("id") != entry["id"]] + [entry]
            self.note_change("gespeichert", kind, entry)
            datei = "eigene.json" if ebene == "eigen" else "katalog.json im Projekt"
            self.send({"type": "ACK", "reply_to": rid, "ok": True, "message": f"{datei} (Ersatz-Kernel)"})
            log(f"Katalog: {entry['id']} gespeichert ({ebene}, status {entry.get('status')})")

    def catalog_delete(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        key = "items" if header.get("kind") == "teil" else "materials"
        eid, ebene = header.get("entry_id"), header.get("ebene")
        before = len(self.catalog[key])
        self.catalog[key] = [e for e in self.catalog[key] if not (e.get("id") == eid and e.get("ebene") == ebene)]
        if len(self.catalog[key]) == before:
            self.send({"type": "ERROR", "reply_to": rid, "message": f"{eid} gibt es in der Ebene {ebene} nicht"})
            return
        self.note_change("gelöscht", header.get("kind"), {"id": eid, "ebene": ebene})
        self.send({"type": "ACK", "reply_to": rid, "ok": True, "message": None})
        log(f"Katalog: {eid} gelöscht ({ebene})")

    def note_change(self, what: str, kind: Any, entry: dict[str, Any]) -> None:
        with (self.out / "katalog-aenderungen.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"aktion": what, "kind": kind, "entry": entry}, ensure_ascii=False) + "\n")

    # Phase 3: Zukaufteile -------------------------------------------------------------------------------------

    def zukauf_status(self, teil: str, zustand: str, text: str | None = None, **extra: Any) -> None:
        name = next((e.get("name") for e in self.catalog["items"] if e.get("id") == teil), teil)
        msg = {"type": "ZUKAUF_STATUS", "id": teil, "zustand": zustand, "text": text, "name": name, **extra}
        if zustand == "wartet_auf_cad":
            self.waiting[teil] = msg
        else:
            self.waiting.pop(teil, None)
        self.send(msg)
        log(f"ZUKAUF_STATUS {teil}: {zustand}")

    def rollwagen_name(self) -> str:
        return "Rollwagen (vereinfacht)" if self.rollwagen_cad == "vereinfacht" else "Rollwagen"

    def zukauf_neu(self, header: dict[str, Any]) -> None:
        # Antworten wie der echte Kernel (zukauf/dienst.py): Ablehnung als ACK ok false, nicht als ERROR
        rid = header.get("id")
        felder = dict(header.get("felder") or {})
        ebene = header.get("ebene")
        teil = felder.get("id")
        if not teil or felder.get("art") != "zukaufteil":
            self.send({"type": "ACK", "reply_to": rid, "ok": False, "message": "felder braucht id und art zukaufteil"})
            return
        if ebene not in ("eigen", "projekt"):
            self.send({"type": "ACK", "reply_to": rid, "ok": False,
                       "message": f"Ebene {ebene!r} geht nicht (projekt oder eigen)"})
            return
        felder["ebene"] = ebene
        felder.setdefault("status", "frei")
        self.catalog["items"] = [e for e in self.catalog["items"] if e.get("id") != teil] + [felder]
        self.note_change("zukauf_neu", "teil", {**felder, "eingabe": header.get("eingabe")})
        datei = "eigene.json" if ebene == "eigen" else "katalog.json im Projekt"
        self.send({"type": "ACK", "reply_to": rid, "ok": True, "message": f"{datei} (Ersatz-Kernel)"})

        def later() -> None:
            time.sleep(0.4)
            self.zukauf_status(teil, "angelegt", "Im Katalog gespeichert, CAD wird gesucht (Ersatz-Kernel)")
            time.sleep(0.8)
            mpn = felder.get("mpn") or felder.get("shop_nr") or teil
            self.zukauf_status(
                teil, "wartet_auf_cad", "Kein Modell bei TraceParts, bitte beim Hersteller herunterladen",
                cad_links=[{"titel": f"{felder.get('hersteller') or 'Hersteller'}-Portal",
                            "url": f"https://www.example.com/cad?mpn={mpn}"},
                           {"titel": "PARTcommunity", "url": f"https://www.example.org/partcommunity?q={mpn}"}],
                erwartet=["step", "stp", "zip"])

        threading.Thread(target=later, daemon=True).start()

    def zukauf_cad(self, header: dict[str, Any]) -> None:
        rid, teil, pfad = header.get("id"), header.get("teil"), header.get("pfad") or ""
        entry = next((e for e in self.catalog["items"] if e.get("id") == teil), None)
        if entry is None:
            self.send({"type": "ACK", "reply_to": rid, "ok": False, "message": f"Zukaufteil {teil!r} gibt es nicht"})
            return
        self.send({"type": "ACK", "reply_to": rid, "ok": True, "message": "CAD wird übernommen"})
        if not os.path.isfile(pfad) or os.path.getsize(pfad) == 0:
            # wie der echte Kernel: fehler, und wartete das Teil, wieder wartet_auf_cad (App beobachtet weiter)
            warte = self.waiting.get(teil)
            grund = f"Datei {Path(pfad).name} fehlt oder ist leer"
            self.zukauf_status(teil, "fehler", grund)
            if warte is not None:
                self.zukauf_status(teil, "wartet_auf_cad", f"{Path(pfad).name} nicht übernommen: {grund}. Bitte die "
                                   "passende STEP-Datei herunterladen.", cad_links=warte.get("cad_links") or [],
                                   erwartet=["step", "stp", "zip"])
            return
        entry["cad"] = {"quelle": "download", "datei": f"zukauf/{teil}/{Path(pfad).name}",
                        "lizenz": "Herstellerbedingungen", "stand": time.strftime("%Y-%m-%d")}
        self.note_change("zukauf_cad", "teil", {"id": teil, "pfad": pfad})

        def later() -> None:
            time.sleep(0.6)
            self.zukauf_status(teil, "importiert", "STEP geprüft, Maße passen zum Shop (Ersatz-Kernel)")
            if teil == "alutec-05200":
                self.rollwagen_cad = "hersteller"
                self.start_run()

        threading.Thread(target=later, daemon=True).start()

    def measure(self, req: dict[str, Any]) -> dict[str, Any]:
        refs = req.get("refs", [])
        points = []
        for r in refs[:2]:
            name, _, sub = r.partition("#")
            h = self.parts.header(name)
            p = None
            if h is not None and sub.startswith("f"):
                try:
                    p = h["faces"][int(sub[1:])].get("c")
                except (IndexError, ValueError):
                    p = None
            if p is None and h is not None:
                bb = h.get("bbox") or {"min": [0, 0, 0], "max": [0, 0, 0]}
                p = [(a + b) / 2 for a, b in zip(bb["min"], bb["max"])]
            points.append([float(x) for x in (p or [0, 0, 0])])
        if len(points) == 2:
            d = [b - a for a, b in zip(points[0], points[1])]
            dist = math.sqrt(sum(x * x for x in d))
            return {"refs": refs, "run": req.get("run"), "kind": "distance",
                    "values": {"distance": dist, "dx": d[0], "dy": d[1], "dz": d[2]}, "points": points,
                    "text": f"Abstand {de(dist)} mm (Ersatz-Kernel)"}
        return {"refs": refs, "run": req.get("run"), "kind": "face", "values": {}, "points": points,
                "text": f"{refs[0] if refs else '?'} (Ersatz-Kernel)"}

    # Verbindung ---------------------------------------------------------------------------------------------------

    def serve(self) -> int:
        path = self.args.socket
        if os.path.exists(path):
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)
        log(f"lauscht auf {path} (MCP-Port {self.args.port} wird nicht bedient)")

        def stop(*_: Any) -> None:
            log("beendet")
            try:
                os.unlink(path)
            except OSError:
                pass
            os._exit(0)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while True:
            conn, _ = srv.accept()
            self.conn = conn
            log("App hat sich verbunden")
            self.send({"type": "HELLO", "protocol": 1, "kernel_version": "0.0-ersatz", "build123d": "keins",
                       "mcp_port": self.args.port})
            self.send({"type": "STATUS", "state": "ready", "message": "Ersatz-Kernel"})
            if self.project:
                self.send({"type": "PROJECT", **self.project})
                for h, p in self.current.values():
                    self.send(h, p)
            if self.first_connection:
                self.first_connection = False
                self.open_project(str(self.out / "Ersatzprojekt"))
                self.start_run()
            for status in list(self.waiting.values()):
                self.send(status)
            reader = FrameReader()
            try:
                while True:
                    data = conn.recv(1 << 20)
                    if not data:
                        break
                    for header, payload in reader.feed(data):
                        self.handle(header, payload)
            except OSError as e:
                log(f"Verbindung abgebrochen: {e}")
            self.conn = None
            conn.close()
            log("App hat die Verbindung beendet")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ersatz-Kernel für Tests der App")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--demo-view", action="store_true", help="nach dem Lauf Ansichtsbefehle und Bilder abspielen")
    parser.add_argument("--out", default=str(REPO / "build" / "fake_kernel"), help="Ordner für die Bilder")
    parser.add_argument("--pause", type=float, default=0.35, help="Pause je Schritt eines Laufs in s")
    parser.add_argument("--lager", action="store_true", help="zusätzlich ein Lagerteil (Vierkantrohr) verbauen")
    parser.add_argument("--zukauf", action="store_true", help="Phase 3: Zukaufteil verbauen, ZUKAUF_* beantworten")
    args, rest = parser.parse_known_args(argv)
    extra = [a for a in rest if a != "serve"]
    if extra:
        log(f"ignoriere Argumente: {extra}")
    return FakeKernel(args).serve()


if __name__ == "__main__":
    sys.exit(main())
