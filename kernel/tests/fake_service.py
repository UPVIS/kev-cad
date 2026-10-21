"""Attrappe des ``KernelService`` für die MCP-Tests: feste Antworten, zeichnet alle Aufrufe auf.

Wird auch von ``fake_kernel.py`` benutzt, das einen MCP-Server mit dieser Attrappe als eigenen Prozess startet
(für die Tests der stdio-Brücke).
"""

from __future__ import annotations

import struct
import threading
import time
import zlib
from typing import Any


def tiny_png(width: int = 4, height: int = 3, rgb: tuple[int, int, int] = (40, 120, 200)) -> bytes:
    """Kleines, gültiges PNG (einfarbig), damit Tests echte Bilddaten durchreichen."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = tiny_png()


def noisy_png(width: int = 1200, height: int = 900, seed: int = 7) -> bytes:
    """Großes, kaum komprimierbares PNG (einige MB), um Größenlimits auf dem Weg zu prüfen."""
    import random

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    rng = random.Random(seed)
    raw = b"".join(b"\x00" + rng.randbytes(width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))

PARTS = [
    {
        "name": "Grundplatte", "bbox": {"min": [-60.0, -40.0, 0.0], "max": [60.0, 40.0, 5.0], "size": [120.0, 80.0, 5.0]},
        "volume": 47434.5, "area": 20345.2, "mass": 128.07, "material": "aluminium", "color": [0.7, 0.72, 0.75, 1.0],
        "faces": 8, "edges": 18, "triangles": 120, "visible": True,
    },
    {
        "name": "Halter/Lasche", "bbox": {"min": [-20.0, -2.5, 5.0], "max": [20.0, 2.5, 55.0], "size": [40.0, 5.0, 50.0]},
        "volume": 9000.0, "area": 4600.0, "mass": 24.3, "material": "aluminium", "color": [0.7, 0.72, 0.75, 1.0],
        "faces": 10, "edges": 24, "triangles": 200, "visible": True,
    },
]


MATERIALS = [
    {"id": "stahl-s235", "name": "Stahl S235", "gruppe": "Stahl", "dichte": 7.85, "farbe": "#8A9099",
     "preis_je_kg": 2.4, "preis_quelle": "Richtwert", "preis_stand": "2026-10", "aliase": ["stahl"],
     "ebene": "mitgeliefert"},
    {"id": "edelstahl-1.4301", "name": "Edelstahl 1.4301", "gruppe": "Edelstahl", "dichte": 7.9, "farbe": "#C9CED3",
     "ebene": "mitgeliefert"},
]

STOCK = [
    {"id": "vierkantrohr-en10219-40x40x3", "art": "vierkantrohr", "name": "Vierkantrohr 40 × 40 × 3",
     "norm": "DIN EN 10219", "masse": {"a": 40, "s": 3}, "material": "stahl-s235", "kg_je_m": 3.41,
     "stangenlaenge": 6000, "preis": {"je_m": 8.0, "quelle": "Richtwert", "stand": "2026-10"}, "ebene": "mitgeliefert",
     "berechnet": {"kg_je_m": 3.41, "querschnitt_mm2": 420.82, "preis_je_m": 8.0, "preis_text": "8,00 €/m"}},
    {"id": "rohr-en10220-42.4x2.0", "art": "rohr", "name": "Rohr 42,4 × 2,0", "norm": "DIN EN 10220",
     "masse": {"d": 42.4, "s": 2.0}, "material": "stahl-s235", "kg_je_m": 1.99, "stangenlaenge": 6000,
     "ebene": "mitgeliefert",
     "berechnet": {"kg_je_m": 1.99, "querschnitt_mm2": 253.84, "preis_je_m": None, "preis_text": None}},
]

BOM = {
    "lines": [
        {"pos": 1, "art": "vierkantrohr", "stock_id": "vierkantrohr-en10219-40x40x3",
         "benennung": "Vierkantrohr 40 × 40 × 3", "norm": "DIN EN 10219", "material": "Stahl S235", "laenge": 842.0,
         "gehrung": [0.0, 0.0], "masse_text": "842 mm", "anzahl": 4, "kg_je": 2.871, "kg": 11.485, "preis_je": 6.74,
         "preis": 26.94, "teile": ["Gestell/Bein vorn links"], "eigenteil": False},
        {"pos": 2, "art": "vierkantrohr", "stock_id": "vierkantrohr-en10219-40x40x3",
         "benennung": "Vierkantrohr 40 × 40 × 3", "norm": "DIN EN 10219", "material": "Stahl S235", "laenge": 800.0,
         "gehrung": [45.0, 45.0], "masse_text": "800 mm", "anzahl": 2, "kg_je": 2.728, "kg": 5.456, "preis_je": 6.4,
         "preis": 12.8, "teile": ["Gestell/Rahmen hinten", "Gestell/Rahmen vorn"], "eigenteil": False},
        {"pos": 3, "art": "eigenteil", "stock_id": None, "benennung": "Halter", "norm": None, "material": "aluminium",
         "laenge": None, "gehrung": [0.0, 0.0], "masse_text": "60 × 5 × 120 mm", "anzahl": 1, "kg_je": 0.096,
         "kg": 0.096, "preis_je": None, "preis": None, "teile": ["Halter"], "eigenteil": True},
    ],
    "cuts": [{"stock_id": "vierkantrohr-en10219-40x40x3", "benennung": "Vierkantrohr 40 × 40 × 3",
              "stangenlaenge": 6000, "saegeschnitt": 3, "stangen": [[842, 842, 842, 842, 800, 800]],
              "verschnitt_prozent": 17.2, "preis_stangen": 48.0}],
    "totals": {"kg": 17.037, "preis": 39.74, "positionen": 3, "teile": 7, "preis_hinweis": "Richtpreise, Stand 2026-10"},
    "warnings": ["Halter: Eigenteil ohne Preis (Material „aluminium“ steht nicht im Katalog)"],
}

# Bericht der Bedingungen wie die Nachricht CONSTRAINTS (PLAN-BEDINGUNGEN.md)
CONSTRAINTS = {
    "items": [
        {"id": "b1", "art": "auf", "gruppe": "montage", "symbol": "auf", "text": "Halter/Lasche.unten auf Grundplatte.oben",
         "teile": ["Halter/Lasche", "Grundplatte"], "stand": "verletzt", "soll": "Abstand 0 mm, Flächen gegenüber",
         "ist": "Abstand 2 mm (Luft 2 mm)", "abweichung": 2.0, "einheit": "mm", "punkte": [[0, 0, 12], [0, 0, 10]],
         "zeile": 14, "datei": "model.py", "schwere": "fehler",
         "loesung": "Halter/Lasche um 2 mm entlang −Z verschieben"},
        {"id": "b2", "art": "konzentrisch", "gruppe": "montage", "symbol": "konzentrisch",
         "text": "Halter/Bolzen.achse konzentrisch zu Halter/Lasche.Bohrung Ø6,6", "teile": ["Halter/Bolzen", "Halter/Lasche"],
         "stand": "erfuellt", "soll": "Achsen deckungsgleich", "ist": "Versatz 0 mm", "abweichung": 0.0, "einheit": "mm",
         "punkte": [[30, 0, 10], [30, 0, 10]], "zeile": 16, "datei": "model.py", "loesung": None},
    ],
    "teile": [{"name": "Halter/Lasche", "platziert": True, "frei": 0, "freiheitsgrade": [], "gelenke": [],
               "stand": "bestimmt", "bedingungen": ["b1", "b2"], "befestigt": True, "am_boden": True,
               "verbindungen": ["aufliegen"]}],
    "bewegungen": [],
    "befunde": [{"art": "bedingung", "pruefung": "bedingung", "teile": ["Halter/Lasche", "Grundplatte"],
                 "schwere": "fehler", "text": "Halter/Lasche.unten auf Grundplatte.oben: Abstand 2 mm (Luft 2 mm)",
                 "soll": "Abstand 0 mm, Flächen gegenüber", "ist": "Abstand 2 mm (Luft 2 mm)", "wert": 2.0,
                 "einheit": "mm", "ort": [0, 0, 12], "loesung": "Halter/Lasche um 2 mm entlang −Z verschieben",
                 "bedingung": "b1", "unterart": "auf", "zeile": 14}],
    "summe": {"gesamt": 2, "erfuellt": 1, "verletzt": 1, "ungeprueft": 0, "fehler": 1, "warnungen": 0, "hinweise": 0,
              "bewegungen": 0},
    "loese_ms": 1.2, "pruef_ms": 3.4,
}


class FakeService:
    """Implementiert ``KernelService`` mit festen Antworten.

    - ``calls``: Liste ``(methode, args, kwargs)`` aller Aufrufe (threadsicher).
    - ``delays``: Wartezeit je Methode in s, z. B. ``{"run": 1.0}`` für Nebenläufigkeitstests.
    - ``fail_run``: nächster Lauf scheitert mit Syntaxfehler in Zeile 12.
    - ``app_connected``: False lässt Ansichts- und Bildbefehle wie ohne App scheitern.
    """

    def __init__(self, project_name: str = "Wandhalter") -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.lock = threading.Lock()
        self.delays: dict[str, float] = {}
        self.fail_run = False
        self.raise_in: set[str] = set()
        self.app_connected = True
        self.project = {"path": f"/tmp/Kev CAD/{project_name}", "name": project_name,
                        "model": f"/tmp/Kev CAD/{project_name}/model.py"}
        self.code = "from build123d import *\nfrom kevcad import show, step, param\n"
        self.run_no = 0
        self.closed = False
        self.activity: list[str | None] = []
        self.connected: list[bool] = []
        self.sessions: list[list[dict[str, Any]]] = []  # jede gemeldete Sitzungsliste
        self.selection_refs = ["Halter/Lasche#f3", "Grundplatte#f0"]
        self.png = PNG  # Bilddaten für screenshot
        self.violations: list[str] = []  # Inventar-Regel: Teile ohne Lagerteil im nächsten Lauf

    # Hilfen -------------------------------------------------------------------------------------------------------

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        with self.lock:
            self.calls.append((name, args, kwargs))
        if name in self.raise_in:
            raise RuntimeError(f"Attrappe: {name} kaputt")
        delay = self.delays.get(name)
        if delay:
            time.sleep(delay)

    def calls_of(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        with self.lock:
            return [(a, k) for n, a, k in self.calls if n == name]

    # KernelService ------------------------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        self._record("status")
        last = None
        if self.run_no:
            last = {"ok": True, "run": self.run_no, "duration_ms": 1234, "parts": PARTS, "steps": ["Grundplatte"],
                    "warnings": [], "params": {"breite": 120.0}}
        return {"project": self.project, "kernel": "ready", "app_connected": self.app_connected, "last_run": last,
                "selection": {"run": self.run_no, "refs": self.selection_refs},
                "inventar": {"regel": True, "verstoesse": list(self.violations)}}

    def project_open(self, path: str) -> dict[str, Any]:
        self._record("project_open", path)
        if path.endswith("/gibtsnicht"):
            return {"ok": False, "error": f"Kein Projektordner: {path}"}
        name = path.rstrip("/").rsplit("/", 1)[-1]
        self.project = {"path": path, "name": name, "model": f"{path}/model.py"}
        return {"ok": True, **self.project}

    def project_new(self, path: str, template: str = "example") -> dict[str, Any]:
        self._record("project_new", path, template)
        name = path.rstrip("/").rsplit("/", 1)[-1]
        self.project = {"path": path, "name": name, "model": f"{path}/model.py"}
        return {"ok": True, **self.project}

    def model_read(self) -> dict[str, Any]:
        self._record("model_read")
        return {"ok": True, "path": self.project["model"], "code": self.code}

    def model_write(self, code: str) -> dict[str, Any]:
        self._record("model_write", code)
        self.code = code
        return {"ok": True, "path": self.project["model"], "bytes": len(code.encode())}

    def run(self, params: dict[str, float] | None = None, slow_ms: int = 0, timeout_s: float = 120) -> dict[str, Any]:
        self._record("run", params, slow_ms)
        self.run_no += 1
        if self.fail_run:
            return {"ok": False, "run": self.run_no, "duration_ms": 12, "parts": [], "steps": ["Grundplatte"],
                    "warnings": [],
                    "error": {"message": "NameError: name 'platt' is not defined", "line": 12,
                              "excerpt": "  11 | platte = Box(breite, 80, dicke)\n> 12 | show(platt, \"Grundplatte\")",
                              "traceback": "Traceback ...", "hint": "Tippfehler im Variablennamen?"}}
        return {"ok": True, "run": self.run_no, "duration_ms": 1234, "parts": PARTS, "steps": ["Grundplatte", "Lasche"],
                "warnings": ["Lasche: Fläche sehr klein"], "params": {"breite": (params or {}).get("breite", 120.0)},
                "bom": {"totals": BOM["totals"], "warnings": BOM["warnings"], "cuts": 1},
                "inventar_regel": True, "inventar_verstoesse": list(self.violations)}

    def execute(self, code: str, timeout_s: float = 60) -> dict[str, Any]:
        self._record("execute", code)
        if "raise" in code:
            return {"ok": False, "stdout": "vorher\n", "error": "ZeroDivisionError: division by zero"}
        return {"ok": True, "stdout": "47434.5\n", "result": "8"}

    def parts(self) -> list[dict[str, Any]]:
        self._record("parts")
        return PARTS if self.run_no else []

    def measure(self, refs: list[str], show: bool = False) -> dict[str, Any]:
        self._record("measure", refs, show)
        return self._measure_result(refs)

    def _measure_result(self, refs: list[str]) -> dict[str, Any]:
        if any("#f99" in r for r in refs):
            return {"ok": False, "error": f"Unbekannte Referenz {refs[0]} (Lauf {self.run_no})"}
        if len(refs) == 2:
            return {"ok": True, "refs": refs, "run": self.run_no, "kind": "distance",
                    "values": {"distance": 12.5, "dx": 0.0, "dy": 0.0, "dz": 12.5, "parallel": True},
                    "points": [[0, 0, 5], [0, 0, 17.5]], "text": "Abstand 12,500 mm (dz 12,500)"}
        return {"ok": True, "refs": refs, "run": self.run_no, "kind": "face", "values": {"area": 200.0, "type": "plane"},
                "points": [[0, 0, 5]], "text": "Ebene, 200,000 mm²"}

    def selection(self) -> dict[str, Any]:
        self._record("selection")
        details = [self._measure_result([r]) for r in self.selection_refs]
        return {"run": self.run_no, "refs": list(self.selection_refs), "details": details}

    def view_command(self, cmd: str, args: dict[str, Any], timeout_s: float = 10) -> dict[str, Any]:
        self._record("view_command", cmd, args)
        if not self.app_connected:
            return {"ok": False, "error": "App nicht verbunden"}
        return {"ok": True}

    def screenshot(self, width: int = 1280, height: int = 800, source: str = "current", view: str | None = None,
                   hide_overlays: bool = False, timeout_s: float = 15) -> dict[str, Any]:
        self._record("screenshot", width, height, source, view, hide_overlays)
        if not self.app_connected:
            return {"ok": False, "error": "App nicht verbunden"}
        return {"ok": True, "png": self.png, "width": width, "height": height,
                "camera": {"projection": "orthographic", "position": [100.0, -100.0, 80.0], "target": [0.0, 0.0, 20.0]},
                "mm_per_px": 0.125}

    def export(self, formats: list[str], parts: list[str] | None = None) -> dict[str, Any]:
        self._record("export", formats, parts)
        return {"ok": True, "files": [f"{self.project['path']}/output/{self.project['name']}.{f}" for f in formats]}

    # Phase 2 -------------------------------------------------------------------------------------------------------

    def bom(self) -> dict[str, Any]:
        self._record("bom")
        if not self.run_no:
            return {"ok": False, "error": "Noch keine Stückliste: erst run aufrufen."}
        return {"ok": True, "run": self.run_no, **BOM}

    def stock_search(self, query: str = "", art: str | None = None, limit: int = 30) -> dict[str, Any]:
        self._record("stock_search", query, art)
        items = [it for it in STOCK if (art is None or it["art"] == art)
                 and all(w in (it["id"] + " " + it["name"]).lower().replace(",", ".").replace(" × ", "x")
                         for w in query.lower().replace(",", ".").split())]
        return {"ok": True, "items": items, "total": len(items)}

    def stock_get(self, stock_id: str) -> dict[str, Any]:
        self._record("stock_get", stock_id)
        for it in STOCK:
            if it["id"] == stock_id:
                return {"ok": True, "item": it, "material": MATERIALS[0], **it["berechnet"],
                        "beispiel": f"teil = lager.teil({stock_id!r})"}
        return {"ok": False, "error": f"Lagerteil {stock_id!r} gibt es nicht"}

    def stock_define(self, entry: dict[str, Any], ebene: str = "eigen") -> dict[str, Any]:
        self._record("stock_define", entry, ebene)
        if not entry.get("material"):
            return {"ok": False, "error": f"Lagerteil {entry.get('id')!r}: Feld material fehlt\n"
                                          f"Lagerteil {entry.get('id')!r}: masse.s fehlt (Zahl in mm)"}
        item = {**entry, "ebene": ebene}
        return {"ok": True, "item": item, "datei": "/tmp/katalog/eigene.json", "hinweise": [],
                "kg_je_m": 1.56, "querschnitt_mm2": 199.2, "preis_je_m": 14.5, "preis_text": "14,50 €/m"}

    def material_list(self, query: str = "") -> dict[str, Any]:
        self._record("material_list", query)
        mats = [m for m in MATERIALS if query.lower() in (m["id"] + " " + m["name"]).lower()]
        return {"ok": True, "materials": mats, "total": len(mats)}

    def material_define(self, entry: dict[str, Any], ebene: str = "eigen") -> dict[str, Any]:
        self._record("material_define", entry, ebene)
        return {"ok": True, "material": {**entry, "ebene": ebene}, "datei": "/tmp/katalog/eigene.json",
                "hinweise": ["preis_stand fehlte: 2026-10 eingetragen"]}

    def constraints(self, part: str | None = None) -> dict[str, Any]:
        self._record("constraints", part)
        if not self.run_no:
            return {"ok": False, "error": "Noch kein Bericht: erst run aufrufen."}
        return {"ok": True, "run": self.run_no, **CONSTRAINTS}

    def catalog_delete(self, kind: str, entry_id: str, ebene: str = "eigen") -> dict[str, Any]:
        self._record("catalog_delete", kind, entry_id, ebene)
        if entry_id == "gibtsnicht":
            return {"ok": False, "error": f"Lagerteil {entry_id!r} gibt es nicht."}
        return {"ok": True, "message": f"Lagerteil {entry_id!r} aus eigene.json gelöscht.",
                "datei": "/tmp/katalog/eigene.json"}

    # Phase 5: Animation ------------------------------------------------------------------------------------------

    ANIM = {"name": "Fahrt", "dauer": 8.0, "fps": 30.0, "bilder": 241, "teile": 12, "kamerafahrt": True, "spuren": 6,
            "standard": True}

    def animation_list(self) -> dict[str, Any]:
        self._record("animation_list")
        return {"ok": True, "animationen": [dict(self.ANIM)], "stand": {"name": "Fahrt", "zeit": 2.5, "spielt": False}}

    def animation_play(self, name: str | None = None, an: bool = True, schleife: bool = False,
                       geschwindigkeit: float = 1.0, von_vorn: bool = False) -> dict[str, Any]:
        self._record("animation_play", name, an, schleife, geschwindigkeit, von_vorn)
        if name not in (None, "Fahrt"):
            return {"ok": False, "error": f"Animation {name!r} gibt es nicht. Vorhanden: 'Fahrt'"}
        return {"ok": True, "name": "Fahrt", "an": an, "schleife": schleife, "geschwindigkeit": geschwindigkeit,
                "dauer": 8.0}

    def animation_seek(self, zeit: float, name: str | None = None) -> dict[str, Any]:
        self._record("animation_seek", zeit, name)
        if zeit > 8:
            return {"ok": False, "error": f"zeit {zeit:g} s liegt außerhalb der Animation 'Fahrt' (0 bis 8 s)"}
        return {"ok": True, "name": "Fahrt", "zeit": zeit, "bild": int(round(zeit * 30)), "dauer": 8.0}

    def animation_video(self, name: str | None = None, breite: int = 1920, hoehe: int | None = None,
                        fps: float | None = None, kamera: str | None = None, format: str = "mp4") -> dict[str, Any]:  # noqa: A002
        self._record("animation_video", name, breite, hoehe, fps, kamera, format)
        if not self.app_connected:
            return {"ok": False, "error": "App nicht verbunden"}
        return {"ok": True, "name": "Fahrt", "path": f"{self.project['path']}/output/animationen/Fahrt.mp4",
                "width": breite, "height": breite * 9 // 16, "fps": fps or 30.0, "bilder": 241, "format": format,
                "ms": 12000}

    def collision_check(self, name: str | None = None, schritt: int = 3) -> dict[str, Any]:
        self._record("collision_check", name, schritt)
        return {"ok": True, "name": "Fahrt", "run": self.run_no, "kollisionen": [
            {"teile": ["Bowlingball", "Pfosten"], "von": 5.1, "bis": 5.6, "zeit": 5.4, "bild": 162, "tiefe": 12.5,
             "volumen": 830.0, "ort": [1500.0, -340.0, 100.0], "bilder": [153, 156, 159, 162, 165, 168]}],
                "geprueft": {"paare": 40, "geprueft_bilder": 81, "schritt": schritt, "ms": 640.0}}

    # Phase 6: Zeichnungen -------------------------------------------------------------------------------------------

    BLATT = {"id": "seitenstange", "ok": True, "neu": True, "titel": "Seitenstange", "inhalt": {"art": "teil",
             "teile": ["Gestell/Seitenstange"]}, "format": "A4 quer", "massstab": "1:1",
             "ansichten": [{"id": "v1", "art": "vorn"}],
             "masse": [{"id": "m1", "art": "linear", "ansicht": "v1", "text": "1000", "wert": 1000.0, "quelle": "auto",
                        "verwaist": False, "bezuege": ["seite:x-", "seite:x+"]},
                       {"id": "m2", "art": "bohrung", "ansicht": "v1", "text": "3× Ø4,2", "wert": None,
                        "quelle": "auto", "verwaist": False, "bezuege": ["bohrung:1"]}],
             "verwaist": [], "allgemein": ["Halbzeug: Alurohr 12 × 1,0"], "hinweise": [], "pruefung": [], "ms": 80.0}

    def drawings(self) -> dict[str, Any]:
        self._record("drawings")
        return {"ok": True, "ordner": "/tmp/p/dokumente/zeichnungen", "blaetter": [dict(self.BLATT)]}

    def drawing_create(self, teile: list[str] | None = None, art: str = "teil", format: str | None = None) \
            -> dict[str, Any]:  # noqa: A002
        self._record("drawing_create", teile, art, format)
        return {"ok": True, "ordner": "/tmp/p/dokumente/zeichnungen", "blaetter": [dict(self.BLATT)]}

    def drawing_edit(self, blatt: str, ops: list[dict[str, Any]], von: str = "agent") -> dict[str, Any]:
        self._record("drawing_edit", blatt, ops, von)
        if blatt != "seitenstange":
            return {"ok": False, "error": f"Blatt {blatt!r} gibt es nicht"}
        return {"ok": True, "ergebnisse": [{"op": o.get("op"), "ok": True, "id": "m3"} for o in ops],
                "blatt": dict(self.BLATT)}

    def drawing_image(self, blatt: str, breite: int = 1800) -> dict[str, Any]:
        self._record("drawing_image", blatt, breite)
        return {"ok": True, "png": PNG, "breite": breite, "hoehe": int(breite * 210 / 297), "blatt": dict(self.BLATT)}

    def set_agent_activity(self, text: str | None) -> None:
        with self.lock:
            self.activity.append(text)

    def set_agent_connected(self, connected: bool) -> None:
        with self.lock:
            self.connected.append(connected)

    def set_agent_sessions(self, sessions: list[dict[str, Any]]) -> None:
        with self.lock:
            self.sessions.append([dict(s) for s in sessions])

    def close(self) -> None:
        self._record("close")
        self.closed = True
