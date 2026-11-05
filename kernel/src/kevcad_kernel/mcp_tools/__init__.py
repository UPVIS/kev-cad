"""MCP-Werkzeuge von Kev CAD (AP6, V2-2): Kernsatz, Fachwerkzeuge, Ergebnisformat, Anweisungen, Verbindungs- und
Tätigkeitsanzeige."""

from __future__ import annotations

from .fach import FAECHER
from .instructions import INSTRUCTIONS, SERVER_NAME, SERVER_TITLE
from .kern import KERN_NAMEN
from .tools import KevcadTools, register_tools

# V2-2: Kernsatz für die tägliche Arbeit, dazu je Fachbereich ein Werkzeug mit aktion
TOOL_NAMES: tuple[str, ...] = KERN_NAMEN + tuple(f.name for f in FAECHER)

__all__ = ["INSTRUCTIONS", "SERVER_NAME", "SERVER_TITLE", "TOOL_NAMES", "KevcadTools", "register_tools"]
