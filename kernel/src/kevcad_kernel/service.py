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
    # Zwangsbedingungen (additiv): Kurzfassung des Berichts, vollständig über constraints()
    bedingungen: dict[str, Any]  # {"summe", "befunde", "befunde_gesamt", "pruef_ms", "loese_ms", ...}


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

    # Zwangsbedingungen (PLAN-BEDINGUNGEN.md, additiv)
    def constraints(self, part: str | None = None) -> dict[str, Any]:
        """Bericht des letzten erfolgreichen Laufs wie die Nachricht CONSTRAINTS: {"ok", "run", "items", "teile",
        "befunde", "bewegungen", "summe", "pruef_ms", "loese_ms"}; mit ``part`` zusätzlich "teil"."""
    # Phase 5: Animation (siehe PROTOCOL.md, Abschnitt „Phase 5: Animation“; umgesetzt in anim_runtime.py)
    def animation_list(self) -> dict[str, Any]:
        """{"ok", "animationen": [{"name", "dauer", "fps", "bilder", "teile", "kamerafahrt", "spuren", "standard",
        "warnungen"?, "kollisionen"?}], "stand": {"name", "zeit", "bild", "spielt", …} | None}"""

    def animation_play(self, name: str | None = None, an: bool = True, schleife: bool = False,
                       geschwindigkeit: float = 1.0, von_vorn: bool = False) -> dict[str, Any]:
        """Abspielen oder anhalten in der App. {"ok", "name", "an", "schleife", "dauer"}"""

    def animation_seek(self, zeit: float, name: str | None = None) -> dict[str, Any]:
        """Zur Zeit springen (s). {"ok", "name", "zeit", "bild"}"""

    def animation_video(self, name: str | None = None, breite: int = 1920, hoehe: int | None = None,
                        fps: float | None = None, kamera: str | None = None, format: str = "mp4") -> dict[str, Any]:  # noqa: A002
        """Video aus der App nach <projekt>/output/animationen/. {"ok", "path", "width", "height", "fps", "bilder",
        "ms", "kamera"}; ``kamera`` None = Viewer-Kamera bzw. Kamerafahrt aus anim.ansicht, sonst eine Kamera aus
        model.py (Kurzname oder „Kamera/<name>“), Höhe dann aus dem Seitenverhältnis ihres Formats."""

    def collision_check(self, name: str | None = None, schritt: int = 3) -> dict[str, Any]:
        """Kollisionen an jedem ``schritt``-ten Bild. {"ok", "name", "kollisionen": [{"teile", "von", "bis", "zeit",
        "bild", "tiefe", "volumen", "ort"}], "geprueft": {…}}"""
    # Phase 5: Kameras (PROTOCOL.md „Phase 5: Kameras“, Umsetzung in kevcad_kernel.kamera.CameraRuntime)
    def cameras(self) -> dict[str, Any]:
        """Kameras des letzten Laufs: {"ok", "cameras": [CAMERA_UPSERT-Kopf + "vorschlag" (oder None)]}"""

    def camera_info(self, name: str) -> dict[str, Any]:
        """Eine Kamera (Name „FX6“ oder „Kamera/FX6“): {"ok", "camera", "vorschlag", "vorschlag_code"?}"""

    def camera_view(self, name: str | None, timeout_s: float = 10) -> dict[str, Any]:
        """Durch die Kamera schauen (VIEW_CMD camera_view), None = zurück zur freien Ansicht. {"ok", "message"?}"""

    def camera_image(self, name: str, width: int = 1920, save: bool = True, return_png: bool = False,
                     overlays: bool = False, timeout_s: float = 60) -> dict[str, Any]:
        """Bild durch die Kamera (Höhe aus dem Seitenverhältnis des Formats), gespeichert unter
        <projekt>/output/kameras/. {"ok", "file", "width", "height", "camera", "kamera", "png"? (nur mit return_png)}"""

    def camera_catalog(self, query: str = "", art: str | None = None, limit: int = 40) -> dict[str, Any]:
        """Kameras, Objektive und Kamerazubehör aus dem Katalog: {"ok", "items", "total"}"""

    def camera_suggestion(self, name: str = "", timeout_s: float = 10) -> dict[str, Any]:
        """Aktuelle Ansicht der App als neue Lage vorschlagen: {"ok", "name", "vorschlag", "code"}"""

    # Phase 6: Bauplan (DOKUMENTE.md, Abschnitt „Bauplan“; umgesetzt in bauplan/dienst.py)
    def bauplan(self, neu: bool = False) -> dict[str, Any]:
        """Bauplan des letzten Laufs, bei Bedarf erzeugt und als <projekt>/dokumente/bauplan.json gespeichert:
        {"ok", "datei", "bauplan" (Inhalt der Datei mit Prüfung), "zusammenfassung", "zeiten"}"""

    def bauplan_bearbeiten(self, ops: list[dict[str, Any]], von: str = "agent") -> dict[str, Any]:
        """Operationen wie BAUPLAN_EDIT, danach Simulation: {"ok", "meldungen", "zusammenfassung", "befunde"}"""

    def bauplan_pruefen(self, schritt: str | None = None) -> dict[str, Any]:
        """Simulation aller Montageschritte oder eines: {"ok", "befunde", "zusammenfassung", "ms", "schritt"}"""

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
