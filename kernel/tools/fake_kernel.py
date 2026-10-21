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
- Mit --demo-view schickt er nach dem Lauf Ansichtsbefehle (VIEW_CMD) und Bildanfragen (SCREENSHOT_REQ) und
  speichert die Bilder der App als PNG (Vorgabe: <repo>/build/fake_kernel/).
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

    def __init__(self) -> None:
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

    def header(self, name: str) -> dict[str, Any] | None:
        for n, _, h, _ in self.items:
            if n == name:
                return h
        return None


# --------------------------------------------------------------------------------------------------------------------
# Server


class FakeKernel:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = Path(args.out).expanduser().resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.parts = Parts()
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
        self.project = {"path": str(p), "name": p.name, "model": str(p / "model.py")}
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
                self.current[name] = (h, payload)
                self.send(h, payload)
            time.sleep(pause)
            self.current.pop("Hilfsteil", None)
            self.send({"type": "PART_REMOVE", "run": run, "name": "Hilfsteil"})
            tri = sum(h["counts"]["tri"] for h, _ in self.current.values())
            self.send({"type": "RUN_END", "run": run, "duration_ms": int((time.perf_counter() - t0) * 1000),
                       "parts": len(self.current), "triangles": tri, "warnings": [], "params": {"breite": 120},
                       "inventar_regel": True, "inventar_verstoesse": []})
            self.send(self.bom(run))
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
            log(f"Einstellungen: {self.settings}")
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
        elif t == "BOM_REQ":  # Phase 2: Stückliste und Katalog aus den Testdateien
            self.send({**self.bom(self.run_no), "reply_to": header.get("id")})
        elif t == "CATALOG_REQ":
            cat, _ = read_fixture("catalog.frame")
            self.send({**{k: v for k, v in cat.items() if k != "seq"}, "reply_to": header.get("id")})
        elif t in ("CATALOG_SAVE", "CATALOG_DELETE"):
            log(f"{t}: {header.get('kind')} {header.get('entry_id') or (header.get('entry') or {}).get('id')}")
            self.send({"type": "ACK", "reply_to": header.get("id"), "ok": True, "message": "Ersatz-Kernel: gespeichert"})
        elif t == "EXPORT_REQ":
            base = Path(self.project["path"]) if self.project else self.out
            files = [str(base / "output" / f"model.{f}") for f in header.get("formats", [])]
            self.send({"type": "EXPORT_RES", "reply_to": header.get("id"), "files": files})
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

    @staticmethod
    def bom(run: int) -> dict[str, Any]:
        header, _ = read_fixture("bom.frame")
        return {**{k: v for k, v in header.items() if k != "seq"}, "run": run}

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
    args, rest = parser.parse_known_args(argv)
    extra = [a for a in rest if a != "serve"]
    if extra:
        log(f"ignoriere Argumente: {extra}")
    return FakeKernel(args).serve()


if __name__ == "__main__":
    sys.exit(main())
