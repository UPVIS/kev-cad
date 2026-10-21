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
        self.selection_refs = ["Halter/Lasche#f3", "Grundplatte#f0"]
        self.png = PNG  # Bilddaten für screenshot

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
                "selection": {"run": self.run_no, "refs": self.selection_refs}}

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
                "warnings": ["Lasche: Fläche sehr klein"], "params": {"breite": (params or {}).get("breite", 120.0)}}

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

    def set_agent_activity(self, text: str | None) -> None:
        with self.lock:
            self.activity.append(text)

    def set_agent_connected(self, connected: bool) -> None:
        with self.lock:
            self.connected.append(connected)

    def close(self) -> None:
        self._record("close")
        self.closed = True
