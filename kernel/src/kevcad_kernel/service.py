"""Fassade zwischen MCP-Werkzeugen (server.py) und Kernel-Laufzeit (runtime.py).

Vertrag für die parallele Entwicklung: Die MCP-Seite programmiert nur gegen ``KernelService`` (und testet mit einer
Attrappe), die Laufzeit implementiert ihn in ``kevcad_kernel.runtime``. Alle Methoden sind synchron und
threadsicher; sie dürfen blockieren (die MCP-Seite ruft sie in einem Worker-Thread auf). Rückgaben sind
JSON-taugliche Wörterbücher mit den hier beschriebenen Schlüsseln; Fehler, die der Agent beheben kann (Syntaxfehler,
unbekannte Referenz, App nicht verbunden), kommen als ``{"ok": False, "error": "..."}`` zurück, nicht als Ausnahme.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class PartSummary(TypedDict, total=False):
    name: str  # vollständiger Name aus show(), z. B. "Halter/Lasche"
    bbox: dict[str, list[float]]  # {"min": [x,y,z], "max": [x,y,z], "size": [dx,dy,dz]}
    volume: float  # mm³
    area: float  # mm²
    mass: float | None  # g, nur mit Material
    material: str | None
    color: list[float]  # RGBA 0..1
    faces: int
    edges: int
    triangles: int
    visible: bool


class RunError(TypedDict, total=False):
    message: str
    line: int | None
    excerpt: str
    traceback: str
    hint: str  # kurzer Reparaturhinweis, falls bekannt


class RunResult(TypedDict, total=False):
    ok: bool
    run: int
    duration_ms: int
    parts: list[PartSummary]
    steps: list[str]
    warnings: list[str]
    params: dict[str, float]
    error: RunError
    # Phase 2 (additiv): Summen der Stückliste und Inventar-Regel
    bom: dict[str, Any]  # {"totals", "warnings", "cuts"}
    inventar_regel: bool
    inventar_verstoesse: list[str]  # gezeigte Teile ohne verbauen()/druckteil()


class MeasureResult(TypedDict, total=False):
    ok: bool
    refs: list[str]
    run: int
    kind: str  # distance | angle | face | edge | vertex | part
    values: dict[str, Any]
    points: list[list[float]]
    text: str
    error: str


class Screenshot(TypedDict, total=False):
    ok: bool
    png: bytes
    width: int
    height: int
    camera: dict[str, Any]
    mm_per_px: float | None
    error: str


class KernelService(Protocol):
    # Projekt
    def status(self) -> dict[str, Any]:
        """{"project": {"path","name","model"} | None, "kernel": "ready"|"busy"|"error", "app_connected": bool,
        "last_run": RunResult | None, "selection": {"run", "refs"}}"""

    def project_open(self, path: str) -> dict[str, Any]:
        """Öffnet einen Projektordner (legt nichts an). {"ok", "path", "name", "model", "error"?}"""

    def project_new(self, path: str, template: str = "example") -> dict[str, Any]:
        """Legt einen Projektordner mit model.py an (template "empty" oder "example") und öffnet ihn."""

    def model_read(self) -> dict[str, Any]:
        """{"ok", "path", "code"}"""

    def model_write(self, code: str) -> dict[str, Any]:
        """Schreibt model.py des offenen Projekts. {"ok", "path", "bytes"}"""

    # Lauf
    def run(self, params: dict[str, float] | None = None, slow_ms: int = 0, timeout_s: float = 120) -> RunResult:
        """Führt model.py aus; Teile gehen dabei live an die App. Läuft für denselben Dateistand schon ein Lauf,
        wird auf dessen Ergebnis gewartet."""

    def execute(self, code: str, timeout_s: float = 60) -> dict[str, Any]:
        """Python im Namensraum des letzten Laufs. {"ok", "stdout", "result" (repr des letzten Ausdrucks), "error"?}
        Mit show() erzeugte Teile erscheinen als Skizze im Viewer."""

    def parts(self) -> list[PartSummary]:
        """Teile des letzten Laufs."""

    # Messen und Auswahl
    def measure(self, refs: list[str], show: bool = False) -> MeasureResult:
        """Exakt messen, 1 oder 2 Referenzen (siehe PROTOCOL.md). show=True blendet das Maß im Viewer ein."""

    def selection(self) -> dict[str, Any]:
        """Auswahl in der App: {"run", "refs": [...], "details": [MeasureResult je Referenz]}"""

    # Ansicht (geht über die App, siehe VIEW_CMD in PROTOCOL.md)
    def view_command(self, cmd: str, args: dict[str, Any], timeout_s: float = 10) -> dict[str, Any]:
        """{"ok", "message"?}; {"ok": False, "error": "App nicht verbunden"} wenn keine App da ist."""

    def screenshot(self, width: int = 1280, height: int = 800, source: str = "current", view: str | None = None,
                   hide_overlays: bool = False, timeout_s: float = 15) -> Screenshot:
        """Bild aus der App: aktuelle Ansicht oder offscreen mit Standardansicht."""

    # Export
    def export(self, formats: list[str], parts: list[str] | None = None) -> dict[str, Any]:
        """{"ok", "files": [...]} in <projekt>/output/"""

    # Phase 2: Lagerteile, Materialien, Stückliste (siehe KATALOG.md und PROTOCOL.md, Abschnitt Phase 2)
    def bom(self) -> dict[str, Any]:
        """Stückliste des letzten Laufs: {"ok", "run", "lines", "cuts", "totals", "warnings"} wie die BOM-Nachricht."""

    def stock_search(self, query: str = "", art: str | None = None, limit: int = 30) -> dict[str, Any]:
        """Lagerteile suchen (alle drei Ebenen): {"ok", "items": [Lagerteil + "ebene"], "total"}"""

    def stock_get(self, stock_id: str) -> dict[str, Any]:
        """Ein Lagerteil mit berechneten Werten: {"ok", "item", "kg_je_m", "querschnitt_mm2", "preis_je_m"}"""

    def stock_define(self, entry: dict[str, Any], ebene: str = "eigen") -> dict[str, Any]:
        """Lagerteil anlegen oder ersetzen (KATALOG.md). Prüft Pflichtfelder und Maße. {"ok", "item", "datei"}
        Inventar-Regel: über MCP immer als Vorschlag (status "vorgeschlagen"), verbaubar erst nach Kevins Freigabe;
        freigegebene Einträge ersetzt es nicht."""

    def material_list(self, query: str = "") -> dict[str, Any]:
        """{"ok", "materials": [Material + "ebene"]}"""

    def material_define(self, entry: dict[str, Any], ebene: str = "eigen") -> dict[str, Any]:
        """Material anlegen oder ersetzen (KATALOG.md). {"ok", "material", "datei"}
        Wie stock_define über MCP immer als Vorschlag."""

    def catalog_delete(self, kind: str, entry_id: str, ebene: str = "eigen") -> dict[str, Any]:
        """Eintrag aus dem eigenen oder Projekt-Katalog löschen. {"ok"}"""

    # Anzeige in der App, was der Agent gerade tut
    def set_agent_activity(self, text: str | None) -> None: ...

    def set_agent_connected(self, connected: bool) -> None: ...

    def set_agent_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Claude-Sitzungen, die Kev CAD bedienen (MIRROR.md, „Sitzungen“): je ``session_id``, ``aktiv``, ``seit``,
        ``taetigkeit``, optional ``zuletzt``; geht an die App im Rahmen AGENT als ``sessions``. Optional: der
        MCP-Server ruft es nur, wenn der Dienst es anbietet."""

    def close(self) -> None: ...


def create_service(socket_path: str, mcp_port: int) -> KernelService:
    """Startet die Laufzeit (Unix-Socket zur App, Rechenprozess) und liefert die Fassade."""
    from kevcad_kernel.runtime import create

    return create(socket_path=socket_path, mcp_port=mcp_port)
